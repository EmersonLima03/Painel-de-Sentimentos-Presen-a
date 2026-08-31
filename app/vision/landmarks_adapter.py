"""Adapter FacialFeatures a partir de Face Landmarker / facial_signals."""

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
    """Usa analyze_face_roi (MediaPipe Tasks). Campos None = inconclusivos."""
    ts = timestamp or datetime.now(timezone.utc)
    try:
        from app.vision.facial_signals import analyze_face_roi

        sample = analyze_face_roi(face_roi)
    except Exception:
        sample = None

    if sample is None:
        return FacialFeatures(timestamp=ts, track_id=track_id, landmarks_quality=0.0)

    ear = getattr(sample, "ear", None)
    ear_l = getattr(sample, "ear_left", ear)
    ear_r = getattr(sample, "ear_right", ear)
    mouth = getattr(sample, "mouth_aspect", None)
    yawn = None
    if mouth is not None:
        yawn = float(mouth) if float(mouth) >= 0.55 else 0.0
    return FacialFeatures(
        timestamp=ts,
        track_id=track_id,
        left_eye_openness=ear_l,
        right_eye_openness=ear_r,
        average_eye_openness=ear,
        blink_score=None,
        mouth_open_score=mouth,
        smile_score=None if getattr(sample, "smile_score", None) is None else float(sample.smile_score),
        frown_score=None if getattr(sample, "frown_score", None) is None else float(sample.frown_score),
        brow_tension_score=None,
        gaze_horizontal=getattr(sample, "yaw", None),
        gaze_vertical=getattr(sample, "pitch", None),
        yaw=getattr(sample, "yaw", None),
        pitch=getattr(sample, "pitch", None),
        roll=getattr(sample, "roll", None),
        landmarks_quality=float(getattr(sample, "landmarks_quality", 0.0) or 0.0),
    )
