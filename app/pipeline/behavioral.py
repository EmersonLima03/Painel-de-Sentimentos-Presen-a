"""
Pipeline de sinais comportamentais observáveis + persistência de eventos.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

from app.db.repo import BehavioralEventRepository, EventRepository
from app.logging import get_logger
from app.pipeline.temporal_aggregator import BehavioralEventDraft, TemporalSignalAggregator
from app.utils.ids import generate_event_id
from app.vision.behavioral_taxonomy import DISCLAIMER_PT
from app.vision.facial_signals import analyze_face_roi

logger = get_logger(__name__)


class BehavioralSignalsPipeline:
    def __init__(
        self,
        event_repo: EventRepository,
        behavioral_repo: BehavioralEventRepository,
        *,
        camera_id: str,
        room_id: str,
        device_id: str,
        school_id: str,
        session_id: Optional[str] = None,
    ):
        self.event_repo = event_repo
        self.behavioral_repo = behavioral_repo
        self.camera_id = camera_id
        self.room_id = room_id
        self.device_id = device_id
        self.school_id = school_id
        self.session_id = session_id
        self.aggregator = TemporalSignalAggregator()
        self.model_version = "signals-v1-mediapipe"

    def set_session_id(self, session_id: Optional[str]) -> None:
        self.session_id = session_id

    def process_frame(
        self,
        frame: np.ndarray,
        face_bboxes: List[Tuple],
        track_ids: Optional[List[str]] = None,
    ) -> List[dict]:
        ih, iw = frame.shape[:2]
        active: List[str] = []
        overlay: List[dict] = []

        for i, bbox in enumerate(face_bboxes):
            x, y, w, h = bbox[:4]
            tid = str(track_ids[i]) if track_ids and i < len(track_ids) else f"t{i}"
            active.append(tid)
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(iw, x1 + int(w)), min(ih, y1 + int(h))
            if x2 <= x1 or y2 <= y1:
                self.aggregator.update_track(tid, None)
                continue
            roi = frame[y1:y2, x1:x2]
            sample = analyze_face_roi(roi)
            self.aggregator.update_track(tid, sample)
            if sample:
                overlay.append(
                    {
                        "bbox": [x1, y1, w, h],
                        "track_id": tid,
                        "signal": sample.orientation,
                        "label_pt": sample.label_pt,
                        "confidence": sample.confidence,
                        "observation_quality": sample.observation_quality,
                        "eyes_closed": sample.eyes_closed,
                        "possible_yawn": sample.possible_yawn,
                    }
                )

        self.aggregator.mark_missing_tracks(active)
        drafts = self.aggregator.poll_events()
        for draft in drafts:
            self._persist(draft)
        return overlay

    def _persist(self, draft: BehavioralEventDraft) -> None:
        event_id = generate_event_id()
        requires_review = bool((draft.metadata or {}).get("requires_human_review")) or draft.event_type in (
            "possible_drowsiness",
            "possible_phone_interaction",
        )
        status = "pending_review" if requires_review else "observed"
        payload = {
            "event_id": event_id,
            "event_type": "behavioral_event",
            "behavioral_type": draft.event_type,
            "school_id": self.school_id,
            "room_id": self.room_id,
            "device_id": self.device_id,
            "camera_id": self.camera_id,
            "session_id": self.session_id,
            "anonymous_track_id": draft.anonymous_track_id,
            "started_at": int(draft.started_at),
            "ended_at": int(draft.ended_at),
            "duration_seconds": round(draft.duration_seconds, 1),
            "confidence": round(draft.confidence, 3),
            "observation_quality": draft.observation_quality,
            "label_pt": draft.label_pt,
            "model_version": self.model_version,
            "status": status,
            "disclaimer": DISCLAIMER_PT,
            "metadata": draft.metadata,
        }
        self.event_repo.create_event(
            event_id=event_id,
            event_type="behavioral_event",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        self.behavioral_repo.create(
            event_id=event_id,
            event_type=draft.event_type,
            school_id=self.school_id,
            room_id=self.room_id,
            device_id=self.device_id,
            camera_id=self.camera_id,
            session_id=self.session_id,
            anonymous_track_id=draft.anonymous_track_id,
            started_at=datetime.utcfromtimestamp(draft.started_at),
            ended_at=datetime.utcfromtimestamp(draft.ended_at),
            duration_seconds=draft.duration_seconds,
            confidence=draft.confidence,
            observation_quality=draft.observation_quality,
            source_model="facial_signals",
            model_version=self.model_version,
            status=status,
            metadata_json=json.dumps(draft.metadata or {}, ensure_ascii=False),
        )
        logger.info(
            "behavioral_event",
            event_type=draft.event_type,
            track=draft.anonymous_track_id,
            duration=round(draft.duration_seconds, 1),
        )
