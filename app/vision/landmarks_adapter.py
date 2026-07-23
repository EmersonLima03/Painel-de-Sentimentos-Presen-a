"""Adapter FacialFeatures a partir de Face Mesh / facial_signals existentes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np

from app.vision.domain import FacialFeatures


def facial_features_from_roi(
    face_roi: np.ndarray,
    track_id: str,
    *,
    timestamp: Optional[datetime] = None,
) -> FacialFeatures:
    """Usa analyze_face_roi se disponível; campos podem ser None (inconclusivos)."""
    ts = timestamp or datetime.now(timezone.utc)
    try:
        from app.vision.facial_signals import analyze_face_roi

        sample = analyze_face_roi(face_roi)
    except Exception:
        sample = None

    if sample is None:
        return FacialFeatures(timestamp=ts, track_id=track_id, landmarks_quality=0.0)

    ear = getattr(sample, "ear", None)
    return FacialFeatures(
        timestamp=ts,
        track_id=track_id,
        left_eye_openness=ear,
        right_eye_openness=ear,
        average_eye_openness=ear,
        blink_score=None,
        mouth_open_score=getattr(sample, "mouth_aspect", None),
        smile_score=None,
        brow_tension_score=None,
        gaze_horizontal=None,
        gaze_vertical=None,
        yaw=getattr(sample, "yaw", None),
        pitch=getattr(sample, "pitch", None),
        roll=None,
        landmarks_quality=0.7 if getattr(sample, "observation_quality", "") == "good" else 0.45,
    )
