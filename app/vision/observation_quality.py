"""ObservationQuality — baixa qualidade → inconclusivo, nunca low engagement."""

from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.vision.domain import ObservationQuality


def compute_observation_quality(
    face_roi: Optional[np.ndarray],
    *,
    face_bbox: Optional[Tuple[float, float, float, float]] = None,
    frame_shape: Optional[Tuple[int, ...]] = None,
    occlusion_level: float = 0.0,
    track_stability: float = 1.0,
    pose_extremity: float = 0.0,
) -> ObservationQuality:
    reasons: List[str] = []
    if face_roi is None or getattr(face_roi, "size", 0) == 0:
        return ObservationQuality(
            overall_score=0.0,
            visibility_score=0.0,
            reasons=["face_not_visible"],
        )

    h, w = face_roi.shape[:2]
    size_score = min(1.0, min(h, w) / 80.0)
    if size_score < 0.35:
        reasons.append("face_too_small")

    gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY) if len(face_roi.shape) == 3 else face_roi
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharpness = min(1.0, blur / 100.0)
    if sharpness < 0.25:
        reasons.append("blurred")

    mean_b = float(np.mean(gray))
    illum = max(0.0, 1.0 - abs(mean_b - 140.0) / 140.0)
    if mean_b < 40:
        reasons.append("low_light")

    pose_score = max(0.0, 1.0 - pose_extremity)
    if pose_extremity > 0.7:
        reasons.append("extreme_pose")

    occ_score = max(0.0, 1.0 - occlusion_level)
    if occlusion_level > 0.5:
        reasons.append("occluded")

    vis = 1.0 if size_score > 0 else 0.0
    stab = max(0.0, min(1.0, track_stability))
    if stab < 0.4:
        reasons.append("unstable_track")

    overall = (
        size_score * 0.2
        + sharpness * 0.2
        + illum * 0.15
        + pose_score * 0.15
        + occ_score * 0.15
        + vis * 0.05
        + stab * 0.1
    )
    return ObservationQuality(
        face_size_score=size_score,
        sharpness_score=sharpness,
        illumination_score=illum,
        pose_score=pose_score,
        occlusion_score=occ_score,
        visibility_score=vis,
        track_stability_score=stab,
        overall_score=float(overall),
        reasons=reasons,
    )


def engagement_state_from_scores(
    *,
    visual_attention: Optional[float],
    observation_quality: float,
    min_quality: float = 0.55,
) -> Tuple[str, List[str]]:
    """Regra: baixa observabilidade NÃO vira low engagement."""
    if observation_quality < min_quality or visual_attention is None:
        return "inconclusive", ["insufficient_observation_quality"]
    if visual_attention >= 0.7:
        return "high", []
    if visual_attention >= 0.4:
        return "moderate", []
    return "low", []
