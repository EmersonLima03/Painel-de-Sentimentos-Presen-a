"""Pose corporal mínima (experimental expandida fica fora do caminho crítico)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MinimalPoseSignals:
    head_supported: Optional[bool] = None
    prolonged_tilt: Optional[bool] = None
    reclined: Optional[bool] = None
    pose_quality: float = 0.0
    experimental_hand_raised: Optional[bool] = None  # experimental — não gera eventos pedagógicos
    experimental_writing: Optional[bool] = None
    experimental_reading: Optional[bool] = None


def estimate_minimal_pose_from_head(*, pitch: Optional[float], quality: float) -> MinimalPoseSignals:
    """Heurística mínima a partir de pitch facial; MediaPipe Pose completo é opcional."""
    if pitch is None or quality < 0.4:
        return MinimalPoseSignals(pose_quality=quality)
    prolonged_tilt = pitch > 25.0
    reclined = pitch > 40.0
    return MinimalPoseSignals(
        head_supported=prolonged_tilt,
        prolonged_tilt=prolonged_tilt,
        reclined=reclined,
        pose_quality=quality,
    )
