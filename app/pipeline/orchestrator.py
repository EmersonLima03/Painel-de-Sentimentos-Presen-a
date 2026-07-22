"""Orquestrador: captura assíncrona + IA em intervalos (presença 2s) sem bloquear vídeo."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import numpy as np

from app.rtsp.reader import RTSPReader
from app.rtsp.watchdog import RTSPWatchdog
from app.vision.detector import create_detector
from app.vision.embedder import create_embedder
from app.vision.face_pipeline import FacePipeline
from app.vision.matcher import (
    FaceMatcher,
    FAISSMatcher,
    load_embeddings_from_face_embeddings,
)
from app.pipeline.presence import PresencePipeline
from app.pipeline.analytics import EngagementAnalytics
from app.db import student_cache
from app.db.init_db import get_session
from app.db.repo import (
    EventRepository,
    AttendanceRepository,
    FaceEmbeddingRepository,
)
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_CAPTURE_HZ = 20.0
_DETECT_HZ = 6.0  # overlay; presença (2s) usa pipeline separado


def _iou_xywh(box_a: tuple, box_b: tuple) -> float:
    """IoU entre retângulos (x, y, w, h)."""
    ax, ay, aw, ah = (float(box_a[0]), float(box_a[1]), float(box_a[2]), float(box_a[3]))
    bx, by, bw, bh = (float(box_b[0]), float(box_b[1]), float(box_b[2]), float(box_b[3]))
    a_x2, a_y2 = ax + aw, ay + ah
    b_x2, b_y2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(a_x2, b_x2), min(a_y2, b_y2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def _merge_overlay_boxes_with_prev(
    boxes: List[tuple],
    prev: List[dict],
    *,
    iou_threshold: float = 0.08,
) -> List[dict]:
    """
    Preserva student_id no overlay quando YuNet muda a ordem das caixas.
    Associa cada caixa nova ao registro anterior com maior IoU (greedy global).
    """
    if not boxes:
        return []
    if not prev:
        return [
            {
                "track_id": i,
                "bbox": [int(x), int(y), int(w), int(h)],
                "student_id": None,
                "full_name": None,
                "confidence": 0.0,
                "provável": False,
                "top2_score": None,
                "margin": None,
            }
            for i, (x, y, w, h) in enumerate(boxes)
        ]

    pairs: List[tuple] = []
    for i, box in enumerate(boxes):
        for j, p in enumerate(prev):
            pb = p.get("bbox")
            if not pb or len(pb) < 4:
                continue
            bbt = (int(pb[0]), int(pb[1]), int(pb[2]), int(pb[3]))
            iou = _iou_xywh(tuple(box[:4]), bbt)
            if iou > 0:
                pairs.append((iou, i, j))

    pairs.sort(key=lambda t: t[0], reverse=True)
    used_i: set = set()
    used_j: set = set()
    box_to_old: Dict[int, dict] = {}
    for iou, i, j in pairs:
        if iou < iou_threshold:
            break
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        box_to_old[i] = prev[j]

    merged: List[dict] = []
    for i, (x, y, w, h) in enumerate(boxes):
        old = box_to_old.get(i, {})
        merged.append(
            {
                "track_id": i,
                "bbox": [int(x), int(y), int(w), int(h)],
                "student_id": old.get("student_id"),
                "full_name": old.get("full_name"),
                "confidence": float(old.get("confidence") or 0.0),
                "provável": bool(old.get("provável", False)),
                "top2_score": old.get("top2_score"),
                "margin": old.get("margin"),
            }
        )
    return merged


class PipelineOrchestrator:
    """Orquestra captura em tempo real e processamento de IA em background."""

    def __init__(self):
        self.settings = get_settings()
        self.running = False

        self.readers: Dict[str, RTSPReader] = {}
        self.watchdog: Optional[RTSPWatchdog] = None
        self.face_pipeline: Optional[FacePipeline] = None

        self.presence_pipelines: Dict[str, PresencePipeline] = {}
        self.engagement_analytics: Dict[str, EngagementAnalytics] = {}

        self.last_presence_sample: Dict[str, float] = {}
        self.last_engagement_sample: Dict[str, float] = {}
        self.last_detect_sample: Dict[str, float] = {}

        self.faces_detected_last: Dict[str, int] = {}
        self.last_presence_match: Dict[str, dict] = {}
        self.last_presence_event_id: Dict[str, Optional[str]] = {}

        self._latest_frames: Dict[str, np.ndarray] = {}
        self._overlay_matches: Dict[str, List[dict]] = {}
        self._overlay_boxes: Dict[str, List[tuple]] = {}
        self._overlay_engagement: Dict[str, List[dict]] = {}  # emoção/engajamento por face (RTCMS+ER)
        self._overlay_source_size: Dict[str, tuple] = {}  # (width, height) do frame na última detecção
        self._engagement_calc = None
        self._engagement_model_version: str = "eng-v0"
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="edge-vision")
        self._presence_busy: Dict[str, bool] = {}

    def initialize(self) -> None:
        logger.info("orchestrator_initializing")

        if getattr(self.settings, "disable_rtsp", False) or not self.settings.cameras:
            logger.info("rtsp_disabled_by_config", cameras_count=len(self.settings.cameras))
            self.watchdog = None
            return

        default_idx = getattr(self.settings, "default_camera_index", 0)
        for cam_config in self.settings.cameras:
            reader = RTSPReader(
                camera_id=cam_config.camera_id,
                rtsp_url=cam_config.rtsp_url,
                default_camera_index=default_idx,
                webcam_width=getattr(cam_config, "webcam_width", None),
                webcam_height=getattr(cam_config, "webcam_height", None),
            )
            self.readers[cam_config.camera_id] = reader
            self.last_presence_sample[cam_config.camera_id] = 0.0
            self.last_engagement_sample[cam_config.camera_id] = 0.0
            self.last_detect_sample[cam_config.camera_id] = 0.0
            self._presence_busy[cam_config.camera_id] = False

        self.watchdog = RTSPWatchdog(self.readers) if self.readers else None

        # Câmera primeiro: preview/cadastro funcionam enquanto modelos carregam
        for camera_id, reader in self.readers.items():
            try:
                if reader.connect():
                    logger.info("camera_connected_early", camera_id=camera_id)
            except Exception as e:
                logger.warning("camera_connect_early_failed", camera_id=camera_id, error=str(e))

        detector = create_detector()
        try:
            embedder = create_embedder()
        except Exception as e:
            logger.error("embedder_init_failed", error=str(e))
            from app.vision.embedder import DeterministicEmbedder

            embedder = DeterministicEmbedder()
        self.face_pipeline = FacePipeline(detector=detector, embedder=embedder)

        session = get_session()
        event_repo = EventRepository(session)
        attendance_repo = AttendanceRepository(session)
        face_embedding_repo = FaceEmbeddingRepository(session)

        face_embeddings = face_embedding_repo.get_all_active_embeddings(
            school_id=self.settings.school_id
        )
        embeddings = load_embeddings_from_face_embeddings(face_embeddings)
        logger.info("orchestrator_loading_embeddings", source="face_embeddings", count=len(embeddings))

        try:
            if len(embeddings) > 0:
                embedding_dim = len(embeddings[0][1])
                base_matcher = FAISSMatcher(embeddings, dim=embedding_dim)
                logger.info("orchestrator_using_faiss", count=len(embeddings), dim=embedding_dim)
            else:
                base_matcher = FAISSMatcher([], dim=512)
                logger.info("orchestrator_using_faiss_empty")
        except Exception as e:
            logger.warning("FAISS disabled: %s (using linear fallback)", str(e))
            base_matcher = FaceMatcher(embeddings)

        for cam_config in self.settings.cameras:
            camera_id = cam_config.camera_id
            room_id = cam_config.room_id

            presence_pipeline = PresencePipeline(
                detector=detector,
                embedder=embedder,
                matcher=base_matcher,
                event_repo=event_repo,
                attendance_repo=attendance_repo,
                face_embedding_repo=face_embedding_repo,
                camera_id=camera_id,
                room_id=room_id,
                device_id=self.settings.device_id,
                school_id=self.settings.school_id,
                face_pipeline=self.face_pipeline,
            )
            self.presence_pipelines[camera_id] = presence_pipeline

            window_sec = int(
                getattr(self.settings, "vision_engagement_window_seconds", None) or 10
            )
            engagement = EngagementAnalytics(
                detector=detector,
                event_repo=event_repo,
                camera_id=camera_id,
                room_id=room_id,
                device_id=self.settings.device_id,
                school_id=self.settings.school_id,
                window_seconds=window_sec,
            )
            self.engagement_analytics[camera_id] = engagement

        try:
            n = student_cache.load_all(school_id=self.settings.school_id)
            logger.info("student_name_cache_loaded", count=n)
        except Exception as e:
            logger.warning("student_name_cache_load_failed", error=str(e))

        logger.info("orchestrator_initialized", num_cameras=len(self.readers))

    def get_latest_frame(self, camera_id: str) -> Optional[np.ndarray]:
        frame = self._latest_frames.get(camera_id)
        if frame is None:
            return None
        return frame.copy()

    def has_latest_frame(self, camera_id: str) -> bool:
        return self._latest_frames.get(camera_id) is not None

    def get_overlay_matches(self, camera_id: str) -> List[dict]:
        return list(self._overlay_matches.get(camera_id) or [])

    def get_overlay_boxes(self, camera_id: str) -> List[tuple]:
        return list(self._overlay_boxes.get(camera_id) or [])

    def get_overlay_engagement(self, camera_id: str) -> List[dict]:
        return list(self._overlay_engagement.get(camera_id) or [])

    def get_integrations_status(self, camera_id: str) -> dict:
        """Status visível das integrações (5 projetos GitHub) para debug/UI."""
        from app.vision.emotion_engagement import is_emotion_backend_available

        if self._engagement_calc is None:
            try:
                from app.vision.engagement_service import get_engagement_calculator

                self._engagement_calc, self._engagement_model_version = get_engagement_calculator()
            except Exception:
                pass
        room_id = None
        for c in self.settings.cameras:
            if c.camera_id == camera_id:
                room_id = c.room_id
                break
        from app.vision.head_pose_engagement import is_head_pose_available

        return {
            "detector": getattr(self.settings, "vision_detector_backend", "yunet"),
            "embedder": getattr(self.settings, "vision_embedder_backend", "facenet"),
            "engagement_backend": getattr(self.settings, "vision_engagement_backend", "head_pose"),
            "engagement_model_version": self._engagement_model_version,
            "head_pose_available": is_head_pose_available(),
            "emotion_model_available": is_emotion_backend_available(),
            "room_id": room_id,
            "per_face_engagement": self.get_overlay_engagement(camera_id),
        }

    def get_overlay_source_size(self, camera_id: str) -> Optional[tuple]:
        return self._overlay_source_size.get(camera_id)

    def _stamp_overlay_frame(self, camera_id: str, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self._overlay_source_size[camera_id] = (w, h)

    @staticmethod
    def _enrich_match_display(m: dict) -> dict:
        sid = m.get("student_id")
        full_name = student_cache.get_display_name(sid) if sid else None
        return {**m, "full_name": full_name}

    def _run_presence_sync(self, camera_id: str, frame: np.ndarray) -> None:
        if self._presence_busy.get(camera_id):
            return
        self._presence_busy[camera_id] = True
        try:
            pipeline = self.presence_pipelines.get(camera_id)
            if not pipeline:
                return
            result = pipeline.process_frame(frame)
            if result and result.get("matches") is not None:
                match_list = result["matches"]
                self._stamp_overlay_frame(camera_id, frame)
                if match_list:
                    self.last_presence_match[camera_id] = [
                        {
                            "student_id": m.get("student_id"),
                            "confidence": m.get("confidence", 0.0),
                            "timestamp": time.time(),
                            "bbox": m.get("bbox"),
                            "full_name": student_cache.get_display_name(m.get("student_id"))
                            if m.get("student_id")
                            else None,
                        }
                        for m in match_list
                    ]
                    self._overlay_matches[camera_id] = [
                        self._enrich_match_display(
                            {
                                "track_id": i,
                                "bbox": m.get("bbox"),
                                "student_id": m.get("student_id"),
                                "confidence": m.get("confidence", 0.0),
                                "provável": m.get("provável", False),
                                "top2_score": m.get("top2_score"),
                                "margin": m.get("margin"),
                            }
                        )
                        for i, m in enumerate(match_list)
                    ]
                    self._overlay_boxes[camera_id] = [
                        tuple(m["bbox"]) for m in match_list if m.get("bbox")
                    ]
                    logger.info(
                        "presence_match_detected",
                        camera_id=camera_id,
                        student_ids=[m.get("student_id") for m in match_list],
                    )
                elif self._overlay_boxes.get(camera_id):
                    self._overlay_matches[camera_id] = [
                        {
                            "track_id": i,
                            "bbox": [x, y, w, h],
                            "student_id": None,
                            "confidence": 0.0,
                            "provável": False,
                        }
                        for i, (x, y, w, h) in enumerate(self._overlay_boxes[camera_id])
                    ]
        except Exception as e:
            logger.warning("presence_pipeline_error", camera_id=camera_id, error=str(e))
        finally:
            self._presence_busy[camera_id] = False

    def _run_detect_sync(self, camera_id: str, frame: np.ndarray) -> None:
        """Detecção + reconhecimento para overlay (~10 Hz), alinhado ao que o viewer mostra."""
        try:
            self._stamp_overlay_frame(camera_id, frame)
            pipeline = self.presence_pipelines.get(camera_id)
            if pipeline and hasattr(pipeline, "recognize_frame_for_overlay"):
                match_list = pipeline.recognize_frame_for_overlay(frame)
                self.faces_detected_last[camera_id] = len(match_list)
                self._overlay_boxes[camera_id] = [
                    tuple(m["bbox"]) for m in match_list if m.get("bbox")
                ]
                enriched = [
                    self._enrich_match_display(
                        {
                            "track_id": m.get("track_id", i),
                            "bbox": m.get("bbox"),
                            "student_id": m.get("student_id"),
                            "confidence": float(m.get("confidence") or 0.0),
                            "provável": bool(m.get("provável", False)),
                            "top2_score": m.get("top2_score"),
                            "margin": m.get("margin"),
                        }
                    )
                    for i, m in enumerate(match_list)
                ]
                self._overlay_matches[camera_id] = enriched
                self._overlay_boxes[camera_id] = [
                    tuple(m["bbox"]) for m in enriched if m.get("bbox")
                ]
                return
            if self.face_pipeline:
                boxes = self.face_pipeline.detect_only(frame)
                self._overlay_boxes[camera_id] = boxes
                self.faces_detected_last[camera_id] = len(boxes)
                prev = self._overlay_matches.get(camera_id) or []
                if boxes:
                    self._overlay_matches[camera_id] = _merge_overlay_boxes_with_prev(boxes, prev)
        except Exception as e:
            logger.warning("detect_only_error", camera_id=camera_id, error=str(e))

    def _run_engagement_sync(self, camera_id: str, frame: np.ndarray) -> None:
        analytics = self.engagement_analytics.get(camera_id)
        bboxes = self._overlay_boxes.get(camera_id) or []
        # Engajamento por face no overlay (Mini-XCEPTION / híbrido — repos RTCMS + ER)
        try:
            if self._engagement_calc is None:
                from app.vision.engagement_service import get_engagement_calculator

                self._engagement_calc, self._engagement_model_version = get_engagement_calculator()
            calc = self._engagement_calc
            if calc and bboxes:
                ih, iw = frame.shape[:2]
                per_face = []
                for (x, y, w, h) in bboxes:
                    x1, y1 = max(0, int(x)), max(0, int(y))
                    x2, y2 = min(iw, x1 + int(w)), min(ih, y1 + int(h))
                    if x2 <= x1 or y2 <= y1:
                        continue
                    roi = frame[y1:y2, x1:x2]
                    emotion_raw = None
                    emotion_conf = None
                    pose_dbg = {}
                    backend = (
                        getattr(self.settings, "vision_engagement_backend", None) or "head_pose"
                    ).strip().lower()
                    try:
                        if backend == "emotion":
                            from app.vision.emotion_engagement import predict_emotion_detail

                            emotion_raw, emotion_conf, state, _, emotion_src = predict_emotion_detail(roi)
                        else:
                            from app.vision.head_pose_engagement import calculate_head_pose_engagement

                            state, label_pt, pose_dbg = calculate_head_pose_engagement(roi, (x1, y1, w, h))
                            emotion_src = pose_dbg.get("backend", "head_pose")
                    except Exception:
                        emotion_src = None
                        state = calc(roi, (x1, y1, w, h))
                        label_pt = {
                            "attentive": "Engajado",
                            "neutral": "Neutro",
                            "distracted": "Distraido",
                        }.get(state, state)
                    if backend != "emotion":
                        pass  # label_pt já veio do head_pose
                    else:
                        label_pt = {
                            "attentive": "Engajado",
                            "neutral": "Neutro",
                            "distracted": "Distraido",
                        }.get(state, state)
                        if emotion_src == "smile":
                            label_pt = f"{label_pt} (sorriso)"
                        elif emotion_raw:
                            label_pt = f"{label_pt} ({emotion_raw})"
                    if pose_dbg and pose_dbg.get("yaw") is not None:
                        label_pt = f"{label_pt} [olhar]"
                    per_face.append({
                        "bbox": [x1, y1, w, h],
                        "state": state,
                        "label_pt": label_pt,
                        "emotion": emotion_raw,
                        "emotion_conf": emotion_conf,
                    })
                self._overlay_engagement[camera_id] = per_face
                for i, m in enumerate(self._overlay_matches.get(camera_id) or []):
                    if i < len(per_face):
                        m["engagement_state"] = per_face[i]["state"]
                        m["engagement_label"] = per_face[i]["label_pt"]
        except Exception as e:
            logger.debug("overlay_engagement_error", camera_id=camera_id, error=str(e))

        if analytics:
            try:
                analytics.process_frame(
                    frame,
                    face_count=len(bboxes),
                    face_bboxes=bboxes if bboxes else None,
                )
            except Exception as e:
                logger.warning("engagement_error", camera_id=camera_id, error=str(e))

    async def start(self) -> None:
        self.running = True

        if not self.readers:
            logger.info("orchestrator_no_cameras", message="RTSP desabilitado ou sem câmeras")
            while self.running:
                await asyncio.sleep(10)
            return

        loop = asyncio.get_event_loop()
        connect_timeout = getattr(self.settings, "camera_connect_timeout_seconds", 15)
        for camera_id, reader in self.readers.items():
            try:
                await asyncio.wait_for(loop.run_in_executor(None, reader.connect), timeout=connect_timeout)
            except asyncio.TimeoutError:
                logger.warning("rtsp_connect_timeout", camera_id=camera_id, timeout_seconds=connect_timeout)
            except Exception as e:
                logger.warning("rtsp_connect_error", camera_id=camera_id, error=str(e))

        logger.info("orchestrator_started", capture_hz=_CAPTURE_HZ)
        frame_interval = 1.0 / _CAPTURE_HZ
        detect_interval = 1.0 / _DETECT_HZ

        while self.running:
            try:
                if self.watchdog:
                    await loop.run_in_executor(None, self.watchdog.check_all)

                now = time.time()
                for camera_id, reader in list(self.readers.items()):
                    if not reader.is_connected:
                        continue

                    ret, frame = reader.read_frame()
                    if ret and frame is not None:
                        self._latest_frames[camera_id] = frame

                    latest = self._latest_frames.get(camera_id)
                    if latest is None:
                        continue

                    if (
                        not self._presence_busy.get(camera_id)
                        and now - self.last_detect_sample.get(camera_id, 0) >= detect_interval
                    ):
                        self.last_detect_sample[camera_id] = now
                        loop.run_in_executor(
                            self._executor,
                            self._run_detect_sync,
                            camera_id,
                            latest.copy(),
                        )

                    if now - self.last_presence_sample.get(camera_id, 0) >= self.settings.presence_sampling_seconds:
                        self.last_presence_sample[camera_id] = now
                        loop.run_in_executor(
                            self._executor,
                            self._run_presence_sync,
                            camera_id,
                            latest.copy(),
                        )

                    if now - self.last_engagement_sample.get(camera_id, 0) >= self.settings.engagement_sampling_seconds:
                        self.last_engagement_sample[camera_id] = now
                        loop.run_in_executor(
                            self._executor,
                            self._run_engagement_sync,
                            camera_id,
                            latest.copy(),
                        )

                await asyncio.sleep(frame_interval)

            except Exception as e:
                logger.error("orchestrator_error", error=str(e))
                await asyncio.sleep(1.0)

    def stop(self) -> None:
        self.running = False
        self._executor.shutdown(wait=False, cancel_futures=True)
        for reader in self.readers.values():
            reader.disconnect()
        logger.info("orchestrator_stopped")

    def get_status(self) -> dict:
        camera_status = {}
        for camera_id, reader in self.readers.items():
            camera_status[camera_id] = {
                **reader.get_status(),
                "faces_detected_last": self.faces_detected_last.get(camera_id, 0),
                "last_presence_match": self.last_presence_match.get(camera_id),
                "last_presence_event_id": self.last_presence_event_id.get(camera_id),
            }

        return {
            "running": self.running,
            "cameras": camera_status,
        }

    def get_vision_backends(self) -> dict:
        if not self.presence_pipelines:
            return {
                "detector_backend": "none",
                "embedder_backend": "none",
                "faiss_enabled": False,
            }
        pipeline = next(iter(self.presence_pipelines.values()))
        detector = pipeline.detector
        embedder = pipeline.embedder
        matcher = pipeline.matcher

        detector_map = {
            "MediaPipeDetector": "mediapipe_tasks",
            "InsightFaceDetector": "insightface",
            "YuNetDetector": "yunet",
            "OpenCVHaarDetector": "opencv_haar",
            "SimulationDetector": "simulation",
        }
        embedder_map = {
            "FaceNetEmbedder": "facenet",
            "InsightFaceEmbedder": "insightface",
            "OnnxFaceEmbedder": "onnx",
            "DeterministicEmbedder": "deterministic",
            "SimulationEmbedder": "simulation",
        }

        detector_backend = detector_map.get(type(detector).__name__, type(detector).__name__.lower())
        embedder_backend = embedder_map.get(type(embedder).__name__, type(embedder).__name__.lower())
        faiss_enabled = type(matcher).__name__ == "FAISSMatcher"

        return {
            "detector_backend": detector_backend,
            "embedder_backend": embedder_backend,
            "faiss_enabled": faiss_enabled,
        }
