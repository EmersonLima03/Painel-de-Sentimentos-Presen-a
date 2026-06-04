"""Pipeline de detecção de presença."""

import json
import time
from datetime import datetime
from typing import Optional, Tuple
import numpy as np
import cv2

from app.vision.detector import FaceDetector
from app.vision.embedder import FaceEmbedder
from app.vision.matcher import (
    FaceMatcher,
    FAISSMatcher,
    load_embeddings_from_face_embeddings,
)
from app.vision.quality import calculate_face_quality
from app.vision.tracker import BboxTracker
from app.db.repo import (
    EventRepository,
    AttendanceRepository,
    FaceEmbeddingRepository,
)
from app.vision.face_mesh_refiner import FaceMeshRefiner
from app.vision.face_filters import stabilize_face_detections
from app.vision.face_alignment import crop_aligned_face
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.vision.face_pipeline import FacePipeline
from app.utils.ids import generate_event_id
from app.utils.time import get_date_key, is_in_active_window, parse_active_windows
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

def _face_aspect_limits():
    """Limites w/h do bbox — mais largos para câmera de teto (DVR)."""
    s = get_settings()
    return (
        float(getattr(s, "vision_face_aspect_min", 0.45) or 0.45),
        float(getattr(s, "vision_face_aspect_max", 1.55) or 1.55),
    )


class PresencePipeline:
    """Pipeline para detecção de presença (check-in)."""
    
    def __init__(
        self,
        detector: FaceDetector,
        embedder: FaceEmbedder,
        matcher,  # FaceMatcher ou FAISSMatcher
        event_repo: EventRepository,
        attendance_repo: AttendanceRepository,
        face_embedding_repo: FaceEmbeddingRepository,
        camera_id: str,
        room_id: str,
        device_id: str,
        school_id: str,
        face_pipeline: Optional["FacePipeline"] = None,
    ):
        self.detector = detector
        self.embedder = embedder
        self.face_pipeline = face_pipeline
        self.matcher = matcher
        self.event_repo = event_repo
        self.attendance_repo = attendance_repo
        self.face_embedding_repo = face_embedding_repo
        self.camera_id = camera_id
        self.room_id = room_id
        self.device_id = device_id
        self.school_id = school_id
        
        settings = get_settings()
        self.threshold = settings.presence_threshold
        self.match_margin = getattr(settings, "presence_match_margin", 0.0)
        self.th_on = getattr(settings, "presence_th_on", 0.72)
        self.th_off = getattr(settings, "presence_th_off", 0.66)
        self.min_face_size = settings.face_min_size
        self.dedup_mode = settings.presence_dedup_mode
        self.active_windows = parse_active_windows(settings.presence_active_windows)
        track_ttl = getattr(settings, "track_ttl_seconds", 2.5)
        self.tracker = BboxTracker(ttl_seconds=track_ttl, iou_threshold=0.35, max_tracks=16)
        self.single_subject_mode = bool(getattr(settings, "vision_single_subject_mode", False))
        self._aspect_min, self._aspect_max = _face_aspect_limits()
        self.min_face_area_ratio = float(getattr(settings, "vision_min_face_area_ratio", 0.0015) or 0.0015)
        self.vision_max_faces = int(getattr(settings, "vision_max_faces", 12) or 12)

        # Refino de ROI para melhorar distância/ângulo (Landmarks do Face Mesh).
        # Ativamos só quando o bbox está relativamente pequeno (típico de distância),
        # para reduzir custo computacional.
        try:
            self.face_mesh_refiner: Optional[FaceMeshRefiner] = FaceMeshRefiner(refine_landmarks=True)
            logger.info("face_mesh_refiner_initialized")
        except Exception as e:
            self.face_mesh_refiner = None
            logger.warning("face_mesh_refiner_disabled", error=str(e))

        self.face_mesh_refine_min_dim_factor = 2.0

    def _detect_faces(self, frame: np.ndarray) -> list:
        """Detecção + filtros anti-fantasma (parede, gola, caixas minúsculas)."""
        raw = self.detector.detect(frame)
        h, w = frame.shape[:2]
        return stabilize_face_detections(
            raw,
            h,
            w,
            min_face_size=self.min_face_size,
            min_area_ratio=self.min_face_area_ratio,
            aspect_min=self._aspect_min,
            aspect_max=self._aspect_max,
            single_subject_mode=self.single_subject_mode,
            max_faces=self.vision_max_faces,
        )

    def _refine_face_roi_for_embedding(
        self,
        frame: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
        fallback_face_roi: np.ndarray,
    ) -> np.ndarray:
        """Refina ROI (face crop) via Face Mesh antes do embedding. Retorna fallback se falhar."""
        if not self.face_mesh_refiner:
            return fallback_face_roi
        if self.min_face_size <= 0:
            return fallback_face_roi

        # Só refinar quando bbox é pequeno: melhora distância sem ficar muito pesado.
        if min(w, h) > int(self.min_face_size * self.face_mesh_refine_min_dim_factor):
            return fallback_face_roi

        refined = self.face_mesh_refiner.refine_bbox(frame, (x, y, w, h), padding_ratio=0.15)
        if not refined or refined.w <= 0 or refined.h <= 0:
            return fallback_face_roi

        ry = refined.y
        rx = refined.x
        return frame[ry : ry + refined.h, rx : rx + refined.w]
    
    def process_frame(self, frame: np.ndarray) -> Optional[dict]:
        """
        Processa frame para detecção de presença.
        
        Presença não é garantida: depende de face detectada + embedding gerado +
        match acima do threshold + dedup (sem check-in duplicado no dia).
        
        Processa todas as faces do frame. Retorna lista de matches para observabilidade
        e cria check-in para cada match novo (sem duplicata no dia).
        
        Retorna: {"matches": [{student_id, confidence}, ...]} ou None se nenhum match.
        """
        settings = get_settings()
        
        # Verificar se está em janela ativa (ou se modo DEV está ativo)
        if not settings.presence_always_on and not is_in_active_window(self.active_windows):
            logger.debug("presence_window_inactive", camera_id=self.camera_id, always_on=settings.presence_always_on)
            return None
        
        if self.face_pipeline is not None:
            return self._process_frame_via_face_pipeline(frame)

        faces = self._detect_faces(frame)
        if not faces:
            logger.debug("presence_no_faces", camera_id=self.camera_id)
            return None

        logger.debug("presence_faces_detected", camera_id=self.camera_id, num_faces=len(faces))

        valid: list = []
        frame_h, frame_w = frame.shape[:2]
        frame_area = float(frame_h * frame_w) if frame_h and frame_w else 1.0
        for (x, y, w, h) in faces:
            if w <= 0 or h <= 0:
                continue
            # 1) Proporção do bbox: descartar tronco/objetos (faixa mais apertada que antes)
            aspect = w / float(h)
            if aspect < self._aspect_min or aspect > self._aspect_max:
                continue
            # 2) Área relativa: descartar bboxes que ocupam área exagerada do frame (corpo colado na câmera)
            area_ratio = (w * h) / frame_area
            if area_ratio > 0.35:
                continue
            # 3) Tamanho mínimo absoluto
            if min(w, h) < self.min_face_size:
                continue
            # 4) ROI da face: usar o bbox completo (como antes), apenas com novos filtros acima
            y_end = min(frame_h, y + h)
            face_roi_raw = frame[y:y_end, x:x+w]
            face_roi = self._refine_face_roi_for_embedding(frame, x, y, w, h, face_roi_raw)
            quality_label, _ = calculate_face_quality(face_roi, self.min_face_size)
            if quality_label == "poor":
                rh, rw = face_roi.shape[:2]
                # A ~2 m ainda há rosto grande no frame: não descartar só por blur/luz fraca
                if min(rh, rw) < int(self.min_face_size * 1.6):
                    continue
            valid.append((x, y, w, h, face_roi, quality_label))

        if not valid:
            return None

        bboxes = [(x, y, w, h) for (x, y, w, h, _, _) in valid]
        now = time.time()
        tracked = self.tracker.update(bboxes, now=now)

        matches: list = []
        date_key = get_date_key()

        for idx, ((x, y, w, h), track_id, track) in enumerate(tracked):
            _, _, _, _, face_roi, quality_label = valid[idx]
            embedding = self.embedder.embed(face_roi, frame=frame, bbox=(x, y, w, h))
            if embedding is None:
                track.update_recognition(None, 0.0, now)
                continue

            topk = self.matcher.find_match_topk(embedding, k=3) if hasattr(self.matcher, "find_match_topk") else []
            if not topk:
                track.update_recognition(None, 0.0, now)
                continue

            top1_id, top1_sim = topk[0]
            was_recognized = track.last_student_id is not None

            # Histerese: TH_ON para aceitar, TH_OFF para perder
            if was_recognized:
                if top1_sim >= self.th_off and top1_id == track.last_student_id:
                    display_id, display_conf = top1_id, top1_sim
                else:
                    display_id = top1_id if top1_sim >= self.th_on else None
                    display_conf = top1_sim if display_id else 0.0
            else:
                display_id = top1_id if top1_sim >= self.th_on else None
                display_conf = top1_sim if display_id else 0.0

            track.update_bbox((x, y, w, h), now)
            track.update_recognition(display_id, display_conf, now)

            top2_sim = topk[1][1] if len(topk) >= 2 else None
            margin_val = (top1_sim - top2_sim) if top2_sim is not None else None
            matches.append(
                {
                    "student_id": display_id,
                    "confidence": display_conf if display_id else top1_sim,
                    "bbox": [x, y, w, h],
                    "top2_score": round(top2_sim, 4) if top2_sim is not None else None,
                    "margin": round(margin_val, 4) if margin_val is not None else None,
                }
            )

            # Check-in só quando passar threshold + margin (segurança)
            match_result = self.matcher.find_match(embedding, self.threshold, margin=self.match_margin, k=3)
            if not match_result or match_result[0] != display_id:
                continue
            student_id, confidence = match_result
            logger.info("presence_match_found",
                        camera_id=self.camera_id, student_id=student_id, confidence=confidence,
                        threshold=self.threshold)

            has_attendance = self.attendance_repo.has_attendance_today(student_id, self.room_id, date_key)
            logger.info("attendance_dedup_check", student_id=student_id, room_id=self.room_id,
                       date_key=date_key, has_attendance=has_attendance)
            if has_attendance:
                logger.info("attendance_duplicate", student_id=student_id, room_id=self.room_id, date_key=date_key)
                continue

            self.attendance_repo.create_attendance(
                student_id=student_id, room_id=self.room_id, confidence=confidence,
                device_id=self.device_id, date_key=date_key
            )
            event = self._create_checkin_event(student_id, confidence, quality_label)
            event_json = json.dumps(event)
            self.event_repo.create_event(event_id=event["event_id"], event_type="attendance_checkin", payload_json=event_json)
            logger.info("attendance_checkin", student_id=student_id, room_id=self.room_id,
                        confidence=confidence, event_id=event["event_id"])
        
        if matches:
            return {"matches": matches}
        return {"matches": []}

    def _process_frame_via_face_pipeline(self, frame: np.ndarray) -> Optional[dict]:
        """YuNet + alinhamento + ONNX batch (face_pipeline)."""
        fp_result = self.face_pipeline.process_frame(frame, skip_if_busy=True)
        if fp_result.get("skipped"):
            return None

        embedded = fp_result.get("embedded") or []
        if not embedded:
            return None

        frame_h, frame_w = frame.shape[:2]
        frame_area = float(frame_h * frame_w) if frame_h and frame_w else 1.0
        valid: list = []
        for det, embedding in embedded:
            if embedding is None:
                continue
            x, y, w, h = det.bbox
            if w <= 0 or h <= 0:
                continue
            aspect = w / float(h)
            if aspect < self._aspect_min or aspect > self._aspect_max:
                continue
            area_ratio = (w * h) / frame_area
            if area_ratio > 0.35:
                continue
            if min(w, h) < self.min_face_size:
                continue
            crop = crop_aligned_face(frame, det.bbox, det.landmarks, output_size=(112, 112))
            if crop is None:
                continue
            quality_label, _ = calculate_face_quality(crop, self.min_face_size)
            if quality_label == "poor" and min(crop.shape[:2]) < int(self.min_face_size * 1.6):
                continue
            valid.append((x, y, w, h, crop, quality_label, embedding))

        if not valid:
            return None

        bboxes = [(x, y, w, h) for (x, y, w, h, _, _, _) in valid]
        now = time.time()
        tracked = self.tracker.update(bboxes, now=now)
        matches: list = []
        date_key = get_date_key()

        for idx, ((x, y, w, h), track_id, track) in enumerate(tracked):
            _, _, _, _, _crop, quality_label, embedding = valid[idx]
            self._match_and_checkin(
                track, x, y, w, h, embedding, quality_label, now, date_key, matches
            )

        if matches:
            return {"matches": matches}
        return {"matches": []}

    def _match_and_checkin(
        self,
        track,
        x: int,
        y: int,
        w: int,
        h: int,
        embedding: np.ndarray,
        quality_label: str,
        now: float,
        date_key: str,
        matches: list,
    ) -> None:
        topk = self.matcher.find_match_topk(embedding, k=3) if hasattr(self.matcher, "find_match_topk") else []
        if not topk:
            track.update_recognition(None, 0.0, now)
            return

        top1_id, top1_sim = topk[0]
        was_recognized = track.last_student_id is not None

        if was_recognized:
            if top1_sim >= self.th_off and top1_id == track.last_student_id:
                display_id, display_conf = top1_id, top1_sim
            else:
                display_id = top1_id if top1_sim >= self.th_on else None
                display_conf = top1_sim if display_id else 0.0
        else:
            display_id = top1_id if top1_sim >= self.th_on else None
            display_conf = top1_sim if display_id else 0.0

        track.update_bbox((x, y, w, h), now)
        track.update_recognition(display_id, display_conf, now)

        top2_sim = topk[1][1] if len(topk) >= 2 else None
        margin_val = (top1_sim - top2_sim) if top2_sim is not None else None
        match_entry = {
            "student_id": display_id,
            "confidence": display_conf if display_id else top1_sim,
            "bbox": [x, y, w, h],
            "top2_score": round(top2_sim, 4) if top2_sim is not None else None,
            "margin": round(margin_val, 4) if margin_val is not None else None,
        }
        matches.append(match_entry)

        match_result = self.matcher.find_match(embedding, self.threshold, margin=self.match_margin, k=3)
        if not match_result or match_result[0] != display_id:
            return
        student_id, confidence = match_result
        logger.info(
            "presence_match_found",
            camera_id=self.camera_id,
            student_id=student_id,
            confidence=confidence,
            threshold=self.threshold,
        )

        has_attendance = self.attendance_repo.has_attendance_today(student_id, self.room_id, date_key)
        if has_attendance:
            logger.info("attendance_duplicate", student_id=student_id, room_id=self.room_id, date_key=date_key)
            return

        self.attendance_repo.create_attendance(
            student_id=student_id,
            room_id=self.room_id,
            confidence=confidence,
            device_id=self.device_id,
            date_key=date_key,
        )
        event = self._create_checkin_event(student_id, confidence, quality_label)
        event_json = json.dumps(event)
        self.event_repo.create_event(
            event_id=event["event_id"], event_type="attendance_checkin", payload_json=event_json
        )
        logger.info(
            "attendance_checkin",
            student_id=student_id,
            room_id=self.room_id,
            confidence=confidence,
            event_id=event["event_id"],
        )

    def recognize_frame_for_overlay(self, frame: np.ndarray, use_margin: bool = False) -> list:
        """
        Reconhece faces no frame para overlay com tracker + histerese (TH_ON/TH_OFF).
        Retorna: [{"bbox", "student_id"|None, "confidence", "provável": bool}, ...].
        provável=True quando entre th_off e th_on (mantém nome estável sem oscilar).
        """
        now = time.time()
        out = []
        th_on = self.th_on
        th_off = self.th_off
        faces = self._detect_faces(frame)
        valid = []
        frame_h, frame_w = frame.shape[:2]
        for (x, y, w, h) in faces:
            if w <= 0 or h <= 0:
                continue
            y_end = min(frame_h, y + h)
            face_roi_raw = frame[y:y_end, x:x+w]
            face_roi = self._refine_face_roi_for_embedding(frame, x, y, w, h, face_roi_raw)
            quality_label, _ = calculate_face_quality(face_roi, self.min_face_size)
            rh, rw = face_roi.shape[:2]
            # DVR/teto: aceitar rosto menor ou "poor" se ainda há pixels suficientes para embedding
            good_quality = quality_label != "poor" or min(rh, rw) >= max(20, int(self.min_face_size * 1.2))
            if min(rh, rw) < max(18, int(self.min_face_size * 0.85)):
                continue
            valid.append((x, y, w, h, face_roi, good_quality))

        if not valid:
            self.tracker.update([], now=now)
            if faces:
                return [
                    {
                        "track_id": i,
                        "bbox": [x, y, w, h],
                        "student_id": None,
                        "confidence": 0.0,
                        "provável": False,
                        "top2_score": None,
                        "margin": None,
                    }
                    for i, (x, y, w, h) in enumerate(faces)
                ]
            return self._overlay_hold_recent_tracks(now, th_on, th_off)

        bboxes = [(x, y, w, h) for (x, y, w, h, _, _) in valid]
        tracked = self.tracker.update(bboxes, now=now)

        overlay_min_conf = max(0.45, th_off - 0.08)  # mostrar nome provável mais cedo no viewer (DVR)
        recognition_cache_seconds = 1.0

        for idx, ((x, y, w, h), track_id, track) in enumerate(tracked):
            _, _, _, _, face_roi, good_quality = valid[idx]
            overlay_bbox = [x, y, w, h]
            if not good_quality:
                out.append({"track_id": track_id, "bbox": overlay_bbox, "student_id": None, "confidence": 0.0, "provável": False, "top2_score": None, "margin": None})
                continue

            # Cache: se o track foi reconhecido recentemente e o score ainda é "pelo menos razoável",
            # reaproveita sem recomputar embedding/matcher (melhora fluidez no viewer).
            if (
                track.last_student_id
                and track.last_recognition_ts > 0
                and (now - track.last_recognition_ts) <= recognition_cache_seconds
                and track.last_confidence >= overlay_min_conf
            ):
                display_id = track.last_student_id
                display_conf = track.last_confidence
                # No overlay, "provável" é quando está abaixo do th_off mas ainda acima do mínimo visual
                provavel = display_conf < th_off
                out.append({
                    "track_id": track_id,
                    "bbox": overlay_bbox,
                    "student_id": display_id,
                    "confidence": display_conf,
                    "provável": provavel,
                    "top2_score": None,
                    "margin": None,
                })
                continue

            # face_roi ja veio refinado no mesmo passo que process_frame (sem segundo refine)
            embedding = self.embedder.embed(face_roi, frame=frame, bbox=(x, y, w, h))
            if embedding is None:
                track.update_recognition(None, 0.0, now)
                out.append({"track_id": track_id, "bbox": overlay_bbox, "student_id": None, "confidence": 0.0, "provável": False, "top2_score": None, "margin": None})
                continue

            topk = self.matcher.find_match_topk(embedding, k=3) if hasattr(self.matcher, "find_match_topk") else []
            if not topk:
                track.update_recognition(None, 0.0, now)
                out.append({"track_id": track_id, "bbox": overlay_bbox, "student_id": None, "confidence": 0.0, "provável": False, "top2_score": None, "margin": None})
                continue

            top1_id, top1_sim = topk[0]
            top2_sim = topk[1][1] if len(topk) >= 2 else 0.0
            margin_val = (top1_sim - top2_sim) if len(topk) >= 2 else None
            margin = round(margin_val, 4) if margin_val is not None else None
            match_margin = getattr(self, "match_margin", 0.08)
            # Segurança: só atribuir student_id se score >= th_on E (margin ausente ou >= match_margin)
            margin_ok = margin is None or margin >= match_margin
            was_recognized = track.last_student_id is not None

            if was_recognized:
                if top1_id == track.last_student_id and margin_ok:
                    if top1_sim >= th_off:
                        # reconhecimento firme (mesmo comportamento da histerese principal)
                        display_id, display_conf = top1_id, top1_sim
                        provavel = False
                    elif top1_sim >= overlay_min_conf:
                        # abaixo de th_off mas ainda parecido: manter nome como "provável" no overlay
                        display_id, display_conf = top1_id, top1_sim
                        provavel = True
                    else:
                        display_id, display_conf, provavel = None, top1_sim, False
                else:
                    if top1_sim >= th_on and margin_ok:
                        display_id, display_conf, provavel = top1_id, top1_sim, False
                    elif top1_sim >= overlay_min_conf and margin_ok:
                        display_id, display_conf, provavel = top1_id, top1_sim, True
                    else:
                        display_id, display_conf, provavel = None, top1_sim, False
            else:
                if top1_sim >= th_on and margin_ok:
                    display_id, display_conf, provavel = top1_id, top1_sim, False
                elif top1_sim >= overlay_min_conf and margin_ok:
                    display_id, display_conf, provavel = top1_id, top1_sim, True
                else:
                    display_id, display_conf, provavel = None, top1_sim, False

            track.update_bbox((x, y, w, h), now)
            track.update_recognition(display_id, display_conf if display_id else top1_sim, now)
            show_conf = display_conf if display_id else top1_sim
            out.append({
                "track_id": track_id,
                "bbox": overlay_bbox,
                "student_id": display_id,
                "confidence": show_conf,
                "provável": provavel,
                "top2_score": round(top2_sim, 4) if len(topk) >= 2 else None,
                "margin": margin,
            })
        return out

    def _overlay_hold_recent_tracks(self, now: float, th_on: float, th_off: float) -> list:
        """
        Quando o detector falha 1–2 frames (comum de longe), mantém caixa/nome do último track.
        Só para overlay de debug — não gera check-in.
        """
        hold_seconds = 0.85
        out = []
        for track in getattr(self.tracker, "_tracks", []):
            gap = now - track.last_seen_ts
            if gap > hold_seconds:
                continue
            x, y, w, h = track.last_bbox
            sid = track.last_student_id
            conf = track.last_confidence
            if not sid and conf < 0.45:
                continue
            provavel = bool(sid and conf < th_off and conf >= max(0.45, th_off - 0.12))
            out.append({
                "track_id": track.track_id,
                "bbox": [x, y, w, h],
                "student_id": sid,
                "confidence": conf,
                "provável": provavel,
                "top2_score": None,
                "margin": None,
                "held": True,
            })
        return out

    def _create_checkin_event(self, student_id: str, confidence: float, face_quality: str) -> dict:
        """Cria evento de check-in."""
        settings = get_settings()
        
        return {
            "event_id": generate_event_id(),
            "event_type": "attendance_checkin",
            "student_id": student_id,
            "school_id": self.school_id,
            "room_id": self.room_id,
            "device_id": self.device_id,
            "timestamp": int(time.time()),
            "confidence": round(confidence, 2),
            "model_version": self.embedder.get_model_version() if hasattr(self.embedder, 'get_model_version') else "emb-v1",
            "template_version": "tpl-v1",
            "face_quality": face_quality
        }
    
    def reload_matcher(self) -> None:
        """Recarrega matcher com embeddings atualizados."""
        face_embeddings = self.face_embedding_repo.get_all_active_embeddings(
            school_id=self.school_id,
            device_id=self.device_id
        )
        embeddings = load_embeddings_from_face_embeddings(face_embeddings)
        logger.info("matcher_reloading_from_face_embeddings", num_embeddings=len(embeddings))

        if len(embeddings) > 0:
            # Se matcher é FAISSMatcher, precisa reconstruir
            if isinstance(self.matcher, FAISSMatcher):
                embedding_dim = len(embeddings[0][1])
                self.matcher = FAISSMatcher(embeddings, dim=embedding_dim)
            else:
                self.matcher.update_embeddings(embeddings)
        
        logger.info("matcher_reloaded", num_embeddings=len(embeddings))
