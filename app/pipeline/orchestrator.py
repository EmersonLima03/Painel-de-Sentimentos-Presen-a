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
from app.pipeline.climate import ClimateAnalytics
from app.pipeline.behavioral import BehavioralSignalsPipeline
from app.db import student_cache
from app.db.init_db import get_session
from app.db.repo import (
    EventRepository,
    AttendanceRepository,
    FaceEmbeddingRepository,
    BehavioralEventRepository,
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
        self.climate_analytics: Dict[str, object] = {}
        self.behavioral_pipelines: Dict[str, object] = {}
        self.active_session_id: Optional[str] = None

        self.last_presence_sample: Dict[str, float] = {}
        self.last_engagement_sample: Dict[str, float] = {}
        self.last_detect_sample: Dict[str, float] = {}
        self.last_behavioral_sample: Dict[str, float] = {}
        self.last_climate_sample: Dict[str, float] = {}
        self.last_phone_sample: Dict[str, float] = {}
        self._phone_visible_since: Dict[str, Optional[float]] = {}
        self._overlay_signals: Dict[str, List[dict]] = {}
        self._overlay_phones: Dict[str, List[tuple]] = {}
        self._latest_climate: Dict[str, dict] = {}

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
        self._analytics_engine = None
        self._analytics_tracks: Dict[str, List[dict]] = {}
        self.last_analytics_sample: Dict[str, float] = {}
        self._analytics_counts: Dict[str, dict] = {}
        self._person_trackers: Dict[str, object] = {}
        self._overlay_person_tracks: Dict[str, List[dict]] = {}
        self._person_tracker_debug: Dict[str, dict] = {}

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
            self.last_behavioral_sample[cam_config.camera_id] = 0.0
            self.last_climate_sample[cam_config.camera_id] = 0.0
            self.last_phone_sample[cam_config.camera_id] = 0.0
            self.last_analytics_sample[cam_config.camera_id] = 0.0
            self._phone_visible_since[cam_config.camera_id] = None
            self._presence_busy[cam_config.camera_id] = False
            self._analytics_tracks[cam_config.camera_id] = []

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
        behavioral_repo = BehavioralEventRepository(session)

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

        # Sessão ativa automática por room (presença periódica)
        try:
            from app.db.repo import ClassSessionRepository
            from app.utils.ids import generate_event_id

            sess_repo = ClassSessionRepository(session)
            active = sess_repo.get_active()
            if active:
                self.active_session_id = active.session_id
            else:
                sid = generate_event_id()
                room0 = self.settings.cameras[0].room_id if self.settings.cameras else "DEV"
                sess_repo.create_session(
                    session_id=sid,
                    school_id=self.settings.school_id,
                    room_id=room0,
                    device_id=self.settings.device_id,
                    title="Sessão automática",
                )
                self.active_session_id = sid
                logger.info("class_session_auto_started", session_id=sid)
        except Exception as e:
            logger.warning("class_session_init_failed", error=str(e))

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
            presence_pipeline.set_session_id(self.active_session_id)
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

            climate = ClimateAnalytics(
                event_repo=event_repo,
                camera_id=camera_id,
                room_id=room_id,
                device_id=self.settings.device_id,
                school_id=self.settings.school_id,
                session_id=self.active_session_id,
                window_seconds=int(getattr(self.settings, "climate_window_seconds", 15) or 15),
            )
            self.climate_analytics[camera_id] = climate

            if getattr(self.settings, "behavioral_signals_enabled", True):
                self.behavioral_pipelines[camera_id] = BehavioralSignalsPipeline(
                    event_repo=event_repo,
                    behavioral_repo=behavioral_repo,
                    camera_id=camera_id,
                    room_id=room_id,
                    device_id=self.settings.device_id,
                    school_id=self.settings.school_id,
                    session_id=self.active_session_id,
                )

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

    def publish_live_debug(self, camera_id: str) -> None:
        """Atualiza /debug/vision sem embeddings, RTSP ou frames."""
        try:
            from app.api.v1 import update_live_debug_state

            analytics_tracks = list(self._analytics_tracks.get(camera_id) or [])
            matches = self.get_overlay_matches(camera_id)
            if not analytics_tracks:
                # fallback mínimo (só presença) até o primeiro ciclo analytics
                analytics_tracks = [
                    {
                        "student_id": m.get("student_id"),
                        "identity_confidence": m.get("confidence"),
                        "confidence": m.get("confidence"),
                        "bbox": m.get("bbox") or m.get("box"),
                        "observation_quality": {"status": "sem_dado"},
                        "facial_features": {"status": "sem_dado"},
                        "latencies_ms": {},
                        "expression": {"status": "not_implemented"},
                        "visual_attention": {"status": "not_implemented"},
                        "drowsiness": {"status": "not_implemented"},
                        "phone": {"status": "disabled"},
                    }
                    for m in matches
                ]
            counts = self._analytics_counts.get(camera_id) or {}
            lat_agg = {}
            for t in analytics_tracks:
                for k, v in (t.get("latencies_ms") or {}).items():
                    if isinstance(v, (int, float)):
                        lat_agg.setdefault(k, []).append(float(v))
            latencies_ms = {
                k: round(sum(vs) / len(vs), 2) for k, vs in lat_agg.items() if vs
            }
            update_live_debug_state(
                camera_id=camera_id,
                tracks=analytics_tracks,
                bindings=[],
                live_event_buffer=(
                    self._analytics_engine.live_event_buffer_snapshot()
                    if self._analytics_engine is not None
                    and hasattr(self._analytics_engine, "live_event_buffer_snapshot")
                    else []
                ),
                data_freshness_meta={"poll_hint_ms": 1500, "storage": "live_event_buffer"},
                signals=self._overlay_signals.get(camera_id) or [],
                phones=[
                    {"bbox": list(p[:4]), "conf": p[4] if len(p) > 4 else None}
                    for p in (self._overlay_phones.get(camera_id) or [])
                ],
                visible_people=counts.get("visible", len(analytics_tracks)),
                recognized_people=counts.get("present", sum(1 for m in matches if m.get("student_id"))),
                observable_people=counts.get("observable"),
                inconclusive_people=counts.get("inconclusive"),
                attention_index=counts.get("attention_index"),
                apparent_climate=counts.get("climate"),
                observation_quality={
                    "note": "per_track_in_tracks[].observation_quality",
                    "aggregate_observable": counts.get("observable"),
                    "aggregate_inconclusive": counts.get("inconclusive"),
                },
                latencies_ms=latencies_ms or {"quality": None, "landmarks": None, "total_analytics": None},
                module_modes={
                    "expression": getattr(self.settings, "module_expression_mode", "disabled"),
                    "face_landmarks": getattr(self.settings, "module_face_landmarks_mode", "disabled"),
                    "phone": getattr(self.settings, "module_phone_mode", "disabled"),
                    "pose": getattr(self.settings, "module_pose_mode", "disabled"),
                    "temporal_fusion": getattr(self.settings, "module_temporal_fusion_mode", "disabled"),
                    "person_tracking": getattr(self.settings, "module_person_tracking_mode", "disabled"),
                },
                camera_status="webcam_or_rtsp",
                is_simulated=False,
                runtime_mode="rtsp",
                classroom_counts={
                    **counts,
                    "person_detector": self._person_tracker_debug.get(camera_id),
                },
            )
        except Exception:
            pass

    def _ensure_person_tracker(self, camera_id: str):
        if camera_id in self._person_trackers:
            return self._person_trackers[camera_id]
        if not getattr(self.settings, "person_tracking_enabled", True):
            return None
        mode = str(getattr(self.settings, "module_person_tracking_mode", "disabled") or "disabled").lower()
        if mode == "disabled":
            return None
        from app.vision.person_tracker import create_person_tracker

        model = getattr(self.settings, "person_tracking_model_path", None) or "data/models/yolov8n.pt"
        tracker = create_person_tracker(
            camera_id,
            prefer_bytetrack=bool(getattr(self.settings, "person_tracking_prefer_bytetrack", True)),
            model_path=str(model),
            ttl_seconds=float(getattr(self.settings, "person_tracking_ttl_seconds", 8.0) or 8.0),
            max_time_lost_seconds=float(
                getattr(self.settings, "person_tracking_max_time_lost_seconds", 8.0) or 8.0
            ),
            minimum_detection_confidence=float(
                getattr(self.settings, "person_tracking_min_detection_confidence", 0.25) or 0.25
            ),
            minimum_reassociation_iou=float(
                getattr(self.settings, "person_tracking_min_reassociation_iou", 0.30) or 0.30
            ),
            maximum_center_distance_ratio=float(
                getattr(self.settings, "person_tracking_max_center_distance_ratio", 0.35) or 0.35
            ),
            tracker_yaml=getattr(self.settings, "person_tracking_bytetrack_yaml", None),
        )
        self._person_trackers[camera_id] = tracker
        return tracker

    def get_overlay_person_tracks(self, camera_id: str) -> List[dict]:
        return list(self._overlay_person_tracks.get(camera_id) or [])

    def get_person_tracker_debug(self, camera_id: str) -> dict:
        return dict(self._person_tracker_debug.get(camera_id) or {})

    def _ensure_analytics_engine(self):
        if self._analytics_engine is None:
            from app.pipeline.analytics_track import RealtimeAnalyticsEngine

            self._analytics_engine = RealtimeAnalyticsEngine(self.settings)
            self._analytics_engine.set_event_sink(self._on_analytics_event)
        return self._analytics_engine

    def _on_analytics_event(self, lifecycle: str, event: dict) -> None:
        """Persiste eventos do motor oficial (sem duplicar agregador legado)."""
        try:
            from datetime import datetime
            import json
            from app.db.models import BehavioralEvent
            from app.utils.ids import generate_event_id

            room_id = self.settings.room_id if hasattr(self.settings, "room_id") else "DEV"
            if self.settings.cameras:
                room_id = self.settings.cameras[0].room_id or room_id

            session = get_session()
            try:
                beh_repo = BehavioralEventRepository(session)
                event_repo = EventRepository(session)
                event_id = event.get("event_id") or generate_event_id()
                event["event_id"] = event_id
                started = float(event.get("started_at") or time.time())
                ended = float(event.get("ended_at") or started)
                if lifecycle == "opened":
                    payload = {
                        **event,
                        "lifecycle": lifecycle,
                        "disclaimer": "Indicadores estimados; não constituem diagnóstico.",
                    }
                    event_repo.create_event(
                        event_id=event_id,
                        event_type="behavioral_event",
                        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
                    )
                    beh_repo.create(
                        event_id=event_id,
                        event_type=event.get("event_type") or "behavioral",
                        school_id=str(self.settings.school_id),
                        room_id=str(room_id),
                        device_id=str(self.settings.device_id),
                        camera_id=event.get("camera_id"),
                        session_id=None,
                        student_id=event.get("student_id"),
                        anonymous_track_id=event.get("track_id"),
                        started_at=datetime.utcfromtimestamp(started),
                        ended_at=datetime.utcfromtimestamp(ended),
                        duration_seconds=float(event.get("duration_seconds") or 0.0),
                        confidence=float(event.get("confidence") or 0.0),
                        observation_quality=event.get("observation_quality"),
                        source_model="realtime_analytics_engine",
                        model_version="analytics-v1",
                        status="pending_review"
                        if event.get("requires_human_review")
                        else (event.get("status") or "observed"),
                        metadata_json=json.dumps(
                            {
                                "provenance": event.get("provenance"),
                                "reasons": event.get("reasons"),
                                "lifecycle": lifecycle,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                elif lifecycle in ("updated", "closed"):
                    row = session.query(BehavioralEvent).filter_by(event_id=event_id).first()
                    if row:
                        row.ended_at = datetime.utcfromtimestamp(ended)
                        row.duration_seconds = float(event.get("duration_seconds") or 0.0)
                        row.confidence = float(event.get("confidence") or row.confidence or 0.0)
                        row.metadata_json = json.dumps(
                            {
                                "provenance": event.get("provenance"),
                                "reasons": event.get("reasons"),
                                "lifecycle": lifecycle,
                            },
                            ensure_ascii=False,
                            default=str,
                        )
                        session.commit()
            finally:
                try:
                    from app.db.init_db import close_session

                    close_session(session)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("analytics_event_persist_error", error=str(e), lifecycle=lifecycle)

    def _run_analytics_sync(self, camera_id: str, frame: np.ndarray) -> None:
        """Person tracks + faces → analytics. Não altera presença."""
        try:
            eng = self._ensure_analytics_engine()
            matches = self.get_overlay_matches(camera_id)
            boxes = self.get_overlay_boxes(camera_id)

            person_tracks = []
            tracker_debug = {}
            tracker = self._ensure_person_tracker(camera_id)
            if tracker is not None:
                # ByteTrack: detecção interna — update([], frame). Fallback detecta se preciso.
                person_tracks = tracker.update([], frame, time.time())
                tracker_debug = dict(getattr(tracker, "last_debug", {}) or {})
                self._person_tracker_debug[camera_id] = tracker_debug
                self._overlay_person_tracks[camera_id] = [
                    {
                        "person_track_id": p.track_id,
                        "bbox": [
                            int(p.bounding_box[0]),
                            int(p.bounding_box[1]),
                            int(p.bounding_box[2]),
                            int(p.bounding_box[3]),
                        ],
                        "confidence": float(p.tracking_confidence or 0.0),
                        "tracking_state": getattr(p, "tracking_state", "active"),
                        "seconds_since_person_detection": getattr(
                            p, "seconds_since_person_detection", 0.0
                        ),
                    }
                    for p in person_tracks
                ]

            tracks = eng.process_camera(
                camera_id=camera_id,
                frame=frame,
                matches=matches,
                boxes=boxes,
                person_tracks=person_tracks or None,
                person_tracker_debug=tracker_debug,
            )
            present = sum(1 for m in matches if m.get("student_id"))
            self._analytics_tracks[camera_id] = tracks
            self._analytics_counts[camera_id] = eng.classroom_counts(tracks, present)
            # phones from engine debug for overlay
            try:
                from app.vision.phone_yolo import get_phone_detector_debug

                dbg = get_phone_detector_debug()
                self._overlay_phones[camera_id] = [
                    tuple(d.get("bbox") or []) + (float(d.get("confidence") or 0),)
                    for d in (dbg.get("detections") or [])
                    if d.get("bbox")
                ]
            except Exception:
                pass
            from app.pipeline.analytics_track import ascii_overlay_label

            per_face = []
            for t in tracks:
                va = t.get("visual_attention") or {}
                state = va.get("state") or "inconclusive"
                ident = t.get("identity") or {}
                src = ident.get("source") or "unknown"
                label = {
                    "high": "Atencao visual alta",
                    "moderate": "Atencao visual moderada",
                    "low": "Atencao visual baixa",
                    "inconclusive": "Estado inconclusivo",
                }.get(state, "Estado inconclusivo")
                q = t.get("observation_quality") or {}
                if q.get("status") in ("inconclusive", "low_quality", "error", "sem_dado", "not_visible"):
                    label = "Estado inconclusivo"
                elif q.get("status") == "partially_observable":
                    hs = (t.get("head_state") or {}).get("state")
                    if hs and "head_down" in str(hs):
                        label = "Cabeca baixa"
                    elif (t.get("face_occlusion") or {}).get("state", "none") != "none":
                        label = "Possivel oclusao por mao"
                    else:
                        label = "Rosto temporariamente oculto"
                if not ident.get("face_visible") and ident.get("student_id"):
                    label = "Identidade mantida pelo track"
                elif not ident.get("student_id"):
                    if not ident.get("face_visible"):
                        label = "Identidade desconhecida"
                ph = (t.get("phone") or {}).get("state")
                if ph in ("possible_phone_interaction", "probable_phone_interaction"):
                    label = "Possivel interacao com celular"
                elif ph in ("phone_visible", "phone_near_person", "phone_in_hand"):
                    label = "Celular visivel"
                per_face.append(
                    {
                        "bbox": t.get("person_bbox") or t.get("bbox"),
                        "face_bbox": t.get("face_bbox"),
                        "person_track_id": t.get("person_track_id"),
                        "identity": ident,
                        "state": state,
                        "label_pt": ascii_overlay_label(label),
                        "emotion": (t.get("expression") or {}).get("normalized_state"),
                        "source": src,
                    }
                )
            self._overlay_engagement[camera_id] = per_face
            self.publish_live_debug(camera_id)
        except Exception as e:
            logger.warning("analytics_sync_error", camera_id=camera_id, error=str(e))

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
                self.publish_live_debug(camera_id)
                return
            if self.face_pipeline:
                boxes = self.face_pipeline.detect_only(frame)
                self._overlay_boxes[camera_id] = boxes
                self.faces_detected_last[camera_id] = len(boxes)
                prev = self._overlay_matches.get(camera_id) or []
                if boxes:
                    self._overlay_matches[camera_id] = _merge_overlay_boxes_with_prev(boxes, prev)
            self.publish_live_debug(camera_id)
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
                    label_pt_txt = "Atenção não conclusiva"
                    backend = (
                        getattr(self.settings, "vision_engagement_backend", None) or "head_pose"
                    ).strip().lower()
                    try:
                        # Pose / sinais faciais (atenção visual estimada)
                        from app.vision.facial_signals import analyze_face_roi
                        from app.vision.behavioral_taxonomy import LEGACY_STATE_TO_OBSERVABLE, label_pt as lp

                        sample = analyze_face_roi(roi)
                        if sample:
                            state = {
                                "orientation_forward": "attentive",
                                "orientation_away": "distracted",
                                "eyes_closed_persistent": "distracted",
                            }.get(sample.orientation, "neutral")
                            label_pt_txt = sample.label_pt
                            pose_dbg = {"yaw": sample.yaw, "backend": "facial_signals"}
                            emotion_src = "facial_signals"
                        else:
                            from app.vision.head_pose_engagement import calculate_head_pose_engagement

                            state, label_pt_txt, pose_dbg = calculate_head_pose_engagement(roi, (x1, y1, w, h))
                            code = LEGACY_STATE_TO_OBSERVABLE.get(state, state)
                            label_pt_txt = lp(code)
                            emotion_src = pose_dbg.get("backend", "head_pose")

                        # Expressão aparente (emotion | hybrid) — nunca diagnóstico
                        if backend in ("emotion", "hybrid"):
                            try:
                                from app.vision.emotion_engagement import predict_emotion_detail
                                from app.vision.expressions.normalization import (
                                    normalize_expression_label,
                                    display_expression_pt,
                                )

                                emotion_raw, emotion_conf, _st, _, emotion_src = predict_emotion_detail(roi)
                                if emotion_raw:
                                    label_pt_txt = (
                                        f"{label_pt_txt} · {display_expression_pt(emotion_raw)}"
                                    )
                                    emotion_raw = normalize_expression_label(emotion_raw)
                            except Exception:
                                pass
                        if backend == "emotion" and emotion_raw is None:
                            # fallback já preenchido por pose acima
                            pass
                    except Exception:
                        emotion_src = None
                        state = calc(roi, (x1, y1, w, h))
                        from app.vision.behavioral_taxonomy import LEGACY_STATE_TO_OBSERVABLE, label_pt as lp

                        label_pt_txt = lp(LEGACY_STATE_TO_OBSERVABLE.get(state, state))
                    per_face.append({
                        "bbox": [x1, y1, w, h],
                        "state": state,
                        "label_pt": label_pt_txt,
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

        # Sinais comportamentais legado: desativado quando RealtimeAnalyticsEngine está ativo
        # (motor temporal único — evita eventos equivalentes em paralelo)
        try:
            if (
                getattr(self.settings, "behavioral_signals_enabled", True)
                and self._analytics_engine is None
            ):
                beh = self.behavioral_pipelines.get(camera_id)
                if beh:
                    signals = beh.process_frame(frame, bboxes or [])
                    self._overlay_signals[camera_id] = signals
        except Exception as e:
            logger.debug("behavioral_error", camera_id=camera_id, error=str(e))

        try:
            climate = self.climate_analytics.get(camera_id)
            if climate:
                ev = climate.process_frame(frame, face_bboxes=bboxes if bboxes else None)
                if ev:
                    self._latest_climate[camera_id] = ev
        except Exception as e:
            logger.debug("climate_error", camera_id=camera_id, error=str(e))

        # Phone YOLO (opcional)
        try:
            if getattr(self.settings, "phone_yolo_enabled", False):
                from app.vision.phone_yolo import detect_phones, phone_near_face
                import time as _t

                phones = detect_phones(frame)
                self._overlay_phones[camera_id] = phones
                now = _t.time()
                if phones:
                    if self._phone_visible_since.get(camera_id) is None:
                        self._phone_visible_since[camera_id] = now
                    elif now - (self._phone_visible_since[camera_id] or now) >= 30 and phone_near_face(phones, bboxes or []):
                        # Emite behavioral via pipeline se disponível
                        beh = self.behavioral_pipelines.get(camera_id)
                        if beh:
                            from app.pipeline.temporal_aggregator import BehavioralEventDraft
                            from app.vision.behavioral_taxonomy import ObservableSignal, label_pt

                            draft = BehavioralEventDraft(
                                event_type=ObservableSignal.POSSIBLE_PHONE_INTERACTION.value,
                                anonymous_track_id="zone",
                                started_at=self._phone_visible_since[camera_id] or now,
                                ended_at=now,
                                duration_seconds=now - (self._phone_visible_since[camera_id] or now),
                                confidence=0.6,
                                observation_quality="fair",
                                label_pt=label_pt(ObservableSignal.POSSIBLE_PHONE_INTERACTION.value),
                                metadata={"requires_human_review": True, "phones": len(phones)},
                            )
                            beh._persist(draft)
                        self._phone_visible_since[camera_id] = now
                else:
                    self._phone_visible_since[camera_id] = None
        except Exception as e:
            logger.debug("phone_yolo_error", camera_id=camera_id, error=str(e))

    async def start(self) -> None:
        self.running = True

        if not self.readers:
            logger.info("orchestrator_no_cameras", message="RTSP desabilitado ou sem câmeras")
            while self.running:
                await asyncio.sleep(10)
            return

        loop = asyncio.get_event_loop()
        connect_timeout = float(getattr(self.settings, "camera_connect_timeout_seconds", 15) or 15)
        # Webcam no Windows costuma precisar >3s se o driver ainda está liberando o device.
        connect_timeout = max(connect_timeout, 10.0)
        for camera_id, reader in self.readers.items():
            try:
                if reader.is_connected:
                    logger.info("camera_already_ready", camera_id=camera_id)
                    continue
                await asyncio.wait_for(
                    loop.run_in_executor(None, reader.connect),
                    timeout=connect_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "rtsp_connect_timeout",
                    camera_id=camera_id,
                    timeout_seconds=connect_timeout,
                )
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

                    analytics_iv = float(
                        getattr(self.settings, "analytics_quality_interval_seconds", 0.5) or 0.5
                    )
                    if now - self.last_analytics_sample.get(camera_id, 0) >= analytics_iv:
                        self.last_analytics_sample[camera_id] = now
                        loop.run_in_executor(
                            self._executor,
                            self._run_analytics_sync,
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
