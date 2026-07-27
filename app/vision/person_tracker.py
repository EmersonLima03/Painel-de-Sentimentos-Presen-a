"""
Person tracker — contrato person-first.

Fluxo preferido (ByteTrack / Ultralytics):
  frame → YOLO.track(classes=[0], tracker=bytetrack) → raw tracks
       → StablePersonTrackManager → person_tracks estáveis

Fallback:
  frame → detect_persons → BboxPersonTrackerAdapter → StablePersonTrackManager

Nunca considerar tracking implementado se update([], frame) for chamado
no fallback sem detecção prévia.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.logging import get_logger
from app.vision.person_track_continuity import StablePersonTrackManager
from app.vision.tracking_types import PersonTrack
from app.vision.tracker import BboxTracker

logger = get_logger(__name__)

PersonDetection = Tuple[float, float, float, float, float]  # x, y, w, h, conf

_DEFAULT_BT_YAML = str(
    Path(__file__).resolve().parents[2] / "data" / "trackers" / "bytetrack_person.yaml"
)


def detect_persons(
    frame: np.ndarray,
    *,
    model_path: str = "yolov8n.pt",
    conf: float = 0.25,
    model=None,
) -> Tuple[List[PersonDetection], Dict[str, Any]]:
    """YOLO classe COCO 0 (person) no frame completo."""
    debug: Dict[str, Any] = {
        "provider": "yolo",
        "class_id": 0,
        "class_name": "person",
        "status": "unavailable",
        "detections_count": 0,
        "inference_ms": 0.0,
        "frame_width": int(frame.shape[1]) if frame is not None else 0,
        "frame_height": int(frame.shape[0]) if frame is not None else 0,
        "conf_threshold": conf,
    }
    if frame is None:
        debug["status"] = "error"
        debug["reason"] = "no_frame"
        return [], debug
    try:
        import time

        t0 = time.perf_counter()
        if model is None:
            from ultralytics import YOLO

            model = YOLO(model_path)
        results = model.predict(frame, verbose=False, conf=conf, classes=[0])
        out: List[PersonDetection] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                xyxy = box.xyxy[0].tolist()
                x1, y1, x2, y2 = [float(v) for v in xyxy]
                c = float(box.conf[0]) if box.conf is not None else 0.0
                out.append((x1, y1, x2 - x1, y2 - y1, c))
        debug["status"] = "available"
        debug["detections_count"] = len(out)
        debug["inference_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        return out, debug
    except Exception as e:
        debug["status"] = "unavailable"
        debug["reason"] = str(e)
        logger.warning("person_detect_failed", error=str(e))
        return [], debug


class BboxPersonTrackerAdapter:
    """Fallback: person_detections → IoU tracker → person_tracks brutos."""

    backend = "bbox_iou"

    def __init__(self, camera_id: str = "cam", ttl_seconds: float = 8.0):
        self.camera_id = camera_id
        self._tracker = BboxTracker(iou_threshold=0.3, ttl_seconds=ttl_seconds, max_tracks=32)
        self._first_seen: Dict[str, datetime] = {}
        self.last_debug: Dict[str, Any] = {
            "tracker_backend": self.backend,
            "detections_count": 0,
            "person_tracks_count": 0,
            "detects_internally": False,
        }

    def update(self, detections, frame, timestamp) -> List[PersonTrack]:
        boxes = [tuple(int(x) for x in d[:4]) for d in (detections or [])]
        pairs = self._tracker.update(boxes)
        now = datetime.now(timezone.utc)
        out: List[PersonTrack] = []
        for bbox, track_id, track in pairs:
            tid = f"raw-bbox-{int(track_id)}"
            if tid not in self._first_seen:
                self._first_seen[tid] = now
            conf = 0.5
            if track is not None:
                conf = float(getattr(track, "last_confidence", 0.5) or 0.5)
            if detections:
                for d in detections:
                    if len(d) >= 5 and abs(d[0] - bbox[0]) < 3 and abs(d[1] - bbox[1]) < 3:
                        conf = float(d[4])
                        break
            out.append(
                PersonTrack(
                    track_id=tid,
                    camera_id=self.camera_id,
                    first_seen_at=self._first_seen[tid],
                    last_seen_at=now,
                    bounding_box=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                    tracking_confidence=conf,
                    visible=True,
                    observation_quality=min(1.0, conf),
                    raw_tracker_id=tid,
                )
            )
        active = {t.track_id for t in out}
        for k in list(self._first_seen.keys()):
            if k not in active:
                self._first_seen.pop(k, None)
        self.last_debug = {
            "tracker_backend": self.backend,
            "detections_count": len(boxes),
            "person_tracks_count": len(out),
            "detects_internally": False,
        }
        return out


class ByteTrackAdapter:
    """
    ByteTrack via Ultralytics YOLO.track — detecção INTERNA.
    IDs brutos (bt-N) são estabilizados depois pelo StablePersonTrackManager.
    """

    backend = "bytetrack"

    def __init__(
        self,
        camera_id: str = "cam",
        model_path: str = "yolov8n.pt",
        *,
        conf: float = 0.25,
        tracker_yaml: Optional[str] = None,
    ):
        self.camera_id = camera_id
        self.model_path = model_path
        self.conf = conf
        self.tracker_yaml = tracker_yaml or _DEFAULT_BT_YAML
        self._model = None
        self._failed = False
        self._fail_reason: Optional[str] = None
        self.last_debug: Dict[str, Any] = {
            "tracker_backend": self.backend,
            "detections_count": 0,
            "person_tracks_count": 0,
            "detects_internally": True,
        }

    @property
    def failed(self) -> bool:
        return self._failed

    def update(self, detections, frame, timestamp) -> List[PersonTrack]:
        if self._failed or frame is None:
            self.last_debug = {
                "tracker_backend": self.backend,
                "detections_count": 0,
                "person_tracks_count": 0,
                "detects_internally": True,
                "status": "failed" if self._failed else "error",
                "reason": self._fail_reason or "no_frame",
            }
            return []
        try:
            import time

            t0 = time.perf_counter()
            if self._model is None:
                from ultralytics import YOLO

                self._model = YOLO(self.model_path)
            tracker_arg = self.tracker_yaml
            if not Path(tracker_arg).is_file():
                tracker_arg = "bytetrack.yaml"
            results = self._model.track(
                frame,
                persist=True,
                classes=[0],
                tracker=tracker_arg,
                verbose=False,
                conf=self.conf,
            )
            now = datetime.now(timezone.utc)
            out: List[PersonTrack] = []
            det_count = 0
            for r in results:
                if r.boxes is None:
                    continue
                det_count += len(r.boxes)
                if r.boxes.id is None:
                    continue
                confs = r.boxes.conf
                for i, (box, tid) in enumerate(zip(r.boxes.xywh, r.boxes.id)):
                    x, y, w, h = [float(v) for v in box.tolist()]
                    conf = float(confs[i]) if confs is not None else 0.6
                    raw_id = f"bt-{int(tid)}"
                    out.append(
                        PersonTrack(
                            track_id=raw_id,
                            camera_id=self.camera_id,
                            first_seen_at=now,
                            last_seen_at=now,
                            bounding_box=(x - w / 2.0, y - h / 2.0, w, h),
                            tracking_confidence=conf,
                            visible=True,
                            observation_quality=min(1.0, conf),
                            raw_tracker_id=raw_id,
                        )
                    )
            self.last_debug = {
                "tracker_backend": self.backend,
                "detections_count": det_count,
                "person_tracks_count": len(out),
                "detects_internally": True,
                "status": "available",
                "inference_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "frame_width": int(frame.shape[1]),
                "frame_height": int(frame.shape[0]),
                "conf_threshold": self.conf,
                "tracker_yaml": tracker_arg,
                "note": "IDs brutos; StablePersonTrackManager estabiliza person_track_id",
            }
            return out
        except Exception as e:
            self._failed = True
            self._fail_reason = str(e)
            logger.warning("bytetrack_failed", error=str(e))
            self.last_debug = {
                "tracker_backend": self.backend,
                "detections_count": 0,
                "person_tracks_count": 0,
                "detects_internally": True,
                "status": "failed",
                "reason": self._fail_reason,
            }
            return []


class PersonTrackerFacade:
    """ByteTrack/bbox bruto + continuidade estável (uma instância por câmera)."""

    def __init__(
        self,
        camera_id: str,
        *,
        prefer_bytetrack: bool = True,
        model_path: str = "yolov8n.pt",
        ttl_seconds: float = 8.0,
        max_time_lost_seconds: float = 8.0,
        minimum_detection_confidence: float = 0.25,
        minimum_reassociation_iou: float = 0.30,
        maximum_center_distance_ratio: float = 0.35,
        tracker_yaml: Optional[str] = None,
    ):
        self.camera_id = camera_id
        self.model_path = model_path
        self.prefer_bytetrack = prefer_bytetrack
        self.minimum_detection_confidence = minimum_detection_confidence
        self._bt: Optional[ByteTrackAdapter] = None
        self._bbox = BboxPersonTrackerAdapter(camera_id=camera_id, ttl_seconds=ttl_seconds)
        self._yolo_model = None
        self._continuity = StablePersonTrackManager(
            camera_id,
            max_time_lost_seconds=max_time_lost_seconds,
            minimum_reassociation_iou=minimum_reassociation_iou,
            maximum_center_distance_ratio=maximum_center_distance_ratio,
        )
        self.last_debug: Dict[str, Any] = {}
        self.last_events: List[dict] = []
        if prefer_bytetrack:
            self._bt = ByteTrackAdapter(
                camera_id=camera_id,
                model_path=model_path,
                conf=minimum_detection_confidence,
                tracker_yaml=tracker_yaml,
            )

    def update(self, detections, frame, timestamp) -> List[PersonTrack]:
        raw: List[PersonTrack] = []
        backend = "bbox_iou"
        if self._bt is not None and not self._bt.failed:
            raw = self._bt.update([], frame, timestamp)
            backend_debug = dict(self._bt.last_debug)
            if not self._bt.failed:
                backend = "bytetrack"
            else:
                logger.info("person_tracker_fallback_to_bbox", camera_id=self.camera_id)
                backend_debug = {}
        else:
            backend_debug = {}

        if backend != "bytetrack":
            dets = detections
            det_debug: Dict[str, Any] = {}
            if not dets and frame is not None:
                try:
                    if self._yolo_model is None:
                        from ultralytics import YOLO

                        self._yolo_model = YOLO(self.model_path)
                except Exception as e:
                    self.last_debug = {
                        "tracker_backend": "bbox_iou",
                        "detections_count": 0,
                        "person_tracks_count": 0,
                        "detects_internally": False,
                        "status": "unavailable",
                        "reason": str(e),
                    }
                    return []
                dets, det_debug = detect_persons(
                    frame,
                    model_path=self.model_path,
                    model=self._yolo_model,
                    conf=self.minimum_detection_confidence,
                )
            raw = self._bbox.update(dets or [], frame, timestamp)
            backend_debug = {
                **self._bbox.last_debug,
                "person_detector": det_debug,
                "status": det_debug.get("status", "available") if det_debug else "available",
            }
            backend = "bbox_iou"

        import time as _time

        now = float(timestamp) if timestamp is not None else _time.time()
        if now > 1e12:  # ms safety
            now = now / 1000.0
        stable = self._continuity.update(raw, now=now)
        self.last_events = self._continuity.drain_events()
        self.last_debug = {
            **backend_debug,
            "tracker_backend": backend,
            "stable_continuity": self._continuity.last_debug,
            "person_tracks_count": len(stable),
            "raw_tracks_count": len(raw),
            "max_time_lost_seconds": self._continuity.max_time_lost_seconds,
            "events": list(self.last_events),
        }
        return stable


def create_person_tracker(
    camera_id: str,
    prefer_bytetrack: bool = True,
    model_path: str = "yolov8n.pt",
    ttl_seconds: float = 8.0,
    max_time_lost_seconds: float = 8.0,
    minimum_detection_confidence: float = 0.25,
    minimum_reassociation_iou: float = 0.30,
    maximum_center_distance_ratio: float = 0.35,
    tracker_yaml: Optional[str] = None,
) -> PersonTrackerFacade:
    return PersonTrackerFacade(
        camera_id,
        prefer_bytetrack=prefer_bytetrack,
        model_path=model_path,
        ttl_seconds=ttl_seconds,
        max_time_lost_seconds=max_time_lost_seconds,
        minimum_detection_confidence=minimum_detection_confidence,
        minimum_reassociation_iou=minimum_reassociation_iou,
        maximum_center_distance_ratio=maximum_center_distance_ratio,
        tracker_yaml=tracker_yaml,
    )
