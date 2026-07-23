"""
TrackerAdapter — ByteTrack via Ultralytics quando disponível; fallback BboxTracker.
PersonTrack separado de FaceTrack.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.vision.tracking_types import PersonTrack
from app.vision.tracker import BboxTracker


class BboxPersonTrackerAdapter:
    """Fallback sem Ultralytics — IoU bbox como PersonTrack aproximado."""

    def __init__(self, camera_id: str = "cam"):
        self.camera_id = camera_id
        self._tracker = BboxTracker(iou_threshold=0.3, ttl_seconds=3.0, max_tracks=32)

    def update(self, detections, frame, timestamp) -> List[PersonTrack]:
        boxes = [tuple(int(x) for x in d[:4]) for d in detections]
        pairs = self._tracker.update(boxes)
        now = datetime.now(timezone.utc)
        out: List[PersonTrack] = []
        for bbox, track_id, track in pairs:
            out.append(
                PersonTrack(
                    track_id=str(track_id),
                    camera_id=self.camera_id,
                    first_seen_at=now,
                    last_seen_at=now,
                    bounding_box=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                    tracking_confidence=float(getattr(track, "last_confidence", 0.5) or 0.5) if track else 0.5,
                    visible=True,
                )
            )
        return out


class ByteTrackAdapter:
    """ByteTrack via YOLO track — requer ultralytics; falha → None."""

    def __init__(self, camera_id: str = "cam", model_path: str = "yolov8n.pt"):
        self.camera_id = camera_id
        self.model_path = model_path
        self._model = None
        self._failed = False

    def update(self, detections, frame, timestamp) -> List[PersonTrack]:
        if self._failed or frame is None:
            return []
        try:
            if self._model is None:
                from ultralytics import YOLO

                self._model = YOLO(self.model_path)
            results = self._model.track(frame, persist=True, classes=[0], tracker="bytetrack.yaml", verbose=False)
            now = datetime.now(timezone.utc)
            out: List[PersonTrack] = []
            for r in results:
                if r.boxes is None or r.boxes.id is None:
                    continue
                for box, tid in zip(r.boxes.xywh, r.boxes.id):
                    x, y, w, h = [float(v) for v in box.tolist()]
                    out.append(
                        PersonTrack(
                            track_id=f"bt-{int(tid)}",
                            camera_id=self.camera_id,
                            first_seen_at=now,
                            last_seen_at=now,
                            bounding_box=(x - w / 2, y - h / 2, w, h),
                            tracking_confidence=0.6,
                            visible=True,
                        )
                    )
            return out
        except Exception:
            self._failed = True
            return []


def create_person_tracker(camera_id: str, prefer_bytetrack: bool = False):
    if prefer_bytetrack:
        bt = ByteTrackAdapter(camera_id=camera_id)
        # smoke: se falhar no primeiro update, caller usa fallback
        return bt
    return BboxPersonTrackerAdapter(camera_id=camera_id)
