"""
Canal de clima / humor aparente agregado por turma.

Nunca gera nota individual. FER opcional apenas para distribuição agregada.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.config import get_settings
from app.db.repo import EventRepository
from app.logging import get_logger
from app.utils.ids import generate_event_id
from app.vision.behavioral_taxonomy import DISCLAIMER_PT, ClimateBucket, ObservableSignal
from app.vision.facial_signals import FacialSignalSample, analyze_face_roi

logger = get_logger(__name__)


def _bucket_from_sample(sample: FacialSignalSample, fer_label: Optional[str] = None) -> str:
    """Mapeia sinais observáveis (+ FER opcional) para clima aparente."""
    if sample.observation_quality == "poor":
        return ClimateBucket.INCONCLUSIVE.value
    if sample.orientation in (
        ObservableSignal.ATTENTION_INCONCLUSIVE.value,
        ObservableSignal.LOW_OBSERVATION_QUALITY.value,
    ):
        return ClimateBucket.INCONCLUSIVE.value

    if fer_label:
        pos = {"happy", "surprise"}
        neg = {"angry", "disgust", "fear", "sad"}
        if fer_label in pos:
            return ClimateBucket.POSITIVE_APPARENT.value
        if fer_label in neg:
            return ClimateBucket.NEGATIVE_APPARENT.value
        if fer_label == "neutral":
            return ClimateBucket.NEUTRAL_APPARENT.value

    # Base: pose + energia facial (sem FER)
    if sample.orientation == ObservableSignal.ORIENTATION_FORWARD.value and not sample.eyes_closed:
        return ClimateBucket.POSITIVE_APPARENT.value
    if sample.eyes_closed or sample.orientation == ObservableSignal.ORIENTATION_AWAY.value:
        return ClimateBucket.NEGATIVE_APPARENT.value
    return ClimateBucket.NEUTRAL_APPARENT.value


class ClimateAnalytics:
    """Agrega clima aparente da turma em janelas temporais."""

    def __init__(
        self,
        event_repo: EventRepository,
        *,
        camera_id: str,
        room_id: str,
        device_id: str,
        school_id: str,
        session_id: Optional[str] = None,
        window_seconds: int = 15,
    ):
        self.event_repo = event_repo
        self.camera_id = camera_id
        self.room_id = room_id
        self.device_id = device_id
        self.school_id = school_id
        self.session_id = session_id
        self.window_seconds = window_seconds
        self._buckets: List[str] = []
        self._energy: List[float] = []
        self._window_start: Optional[float] = None
        self._prev_gray: Optional[np.ndarray] = None
        settings = get_settings()
        self.use_fer = bool(getattr(settings, "climate_use_fer", False))
        self.model_version = "climate-v1-pose" + ("+fer" if self.use_fer else "")

    def _motion(self, frame: np.ndarray) -> float:
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray.copy()
            return 0.0
        diff = np.abs(gray.astype(np.float32) - self._prev_gray.astype(np.float32))
        self._prev_gray = gray.copy()
        return float(np.mean(diff))

    def process_frame(
        self,
        frame: np.ndarray,
        face_bboxes: Optional[List[Tuple[int, int, int, int]]] = None,
    ) -> Optional[dict]:
        now = time.time()
        if self._window_start is None:
            self._window_start = now

        self._energy.append(self._motion(frame))
        fer_predict = None
        if self.use_fer:
            try:
                from app.vision.emotion_engagement import predict_emotion

                fer_predict = predict_emotion
            except Exception:
                fer_predict = None

        if face_bboxes:
            ih, iw = frame.shape[:2]
            for (x, y, w, h) in face_bboxes:
                x1, y1 = max(0, int(x)), max(0, int(y))
                x2, y2 = min(iw, x1 + int(w)), min(ih, y1 + int(h))
                if x2 <= x1 or y2 <= y1:
                    continue
                roi = frame[y1:y2, x1:x2]
                sample = analyze_face_roi(roi)
                if sample is None:
                    self._buckets.append(ClimateBucket.INCONCLUSIVE.value)
                    continue
                fer_label = None
                if fer_predict is not None:
                    try:
                        fer_label, _ = fer_predict(roi)
                    except Exception:
                        fer_label = None
                self._buckets.append(_bucket_from_sample(sample, fer_label))

        if now - self._window_start < self.window_seconds:
            return None

        event = self._flush(int(self._window_start), int(now))
        self._buckets = []
        self._energy = []
        self._window_start = now
        return event

    def _flush(self, ts_start: int, ts_end: int) -> dict:
        total = max(1, len(self._buckets))
        dist = {
            ClimateBucket.POSITIVE_APPARENT.value: 0.0,
            ClimateBucket.NEUTRAL_APPARENT.value: 0.0,
            ClimateBucket.NEGATIVE_APPARENT.value: 0.0,
            ClimateBucket.INCONCLUSIVE.value: 0.0,
        }
        for b in self._buckets:
            dist[b] = dist.get(b, 0.0) + 1.0
        for k in dist:
            dist[k] = round(dist[k] / total, 3)

        energy = float(np.mean(self._energy)) if self._energy else 0.0
        # dominante ignorando inconclusive se houver sinal útil
        usable = {k: v for k, v in dist.items() if k != ClimateBucket.INCONCLUSIVE.value}
        dominant = max(usable, key=usable.get) if usable and sum(usable.values()) > 0 else ClimateBucket.INCONCLUSIVE.value

        event = {
            "event_id": generate_event_id(),
            "event_type": "climate_window",
            "school_id": self.school_id,
            "room_id": self.room_id,
            "device_id": self.device_id,
            "camera_id": self.camera_id,
            "session_id": self.session_id,
            "ts_start": ts_start,
            "ts_end": ts_end,
            "climate_distribution": dist,
            "dominant_climate": dominant,
            "activity_energy": round(energy, 2),
            "samples": len(self._buckets),
            "model_version": self.model_version,
            "disclaimer": DISCLAIMER_PT,
            "status": "observed",
        }
        self.event_repo.create_event(
            event_id=event["event_id"],
            event_type="climate_window",
            payload_json=json.dumps(event, ensure_ascii=False),
        )
        logger.info(
            "climate_window",
            room_id=self.room_id,
            dominant=dominant,
            samples=len(self._buckets),
        )
        return event
