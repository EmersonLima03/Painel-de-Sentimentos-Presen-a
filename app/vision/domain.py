"""Dataclasses de domínio para observação multimodal."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Provenance:
    provider: str
    model_name: str
    model_version: str
    rule_engine_version: str = "rules-v0-baseline"
    threshold_profile: str = "presence-yaml-2026-07-23"
    camera_calibration_version: str = "cam-vip-5440-01-uncalibrated"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ObservationQuality:
    face_size_score: float = 0.0
    sharpness_score: float = 0.0
    illumination_score: float = 0.0
    pose_score: float = 0.0
    occlusion_score: float = 0.0
    visibility_score: float = 0.0
    track_stability_score: float = 0.0
    overall_score: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FacialFeatures:
    timestamp: datetime
    track_id: str
    left_eye_openness: Optional[float] = None
    right_eye_openness: Optional[float] = None
    average_eye_openness: Optional[float] = None
    blink_score: Optional[float] = None
    mouth_open_score: Optional[float] = None
    smile_score: Optional[float] = None
    frown_score: Optional[float] = None
    brow_tension_score: Optional[float] = None
    gaze_horizontal: Optional[float] = None
    gaze_vertical: Optional[float] = None
    yaw: Optional[float] = None
    pitch: Optional[float] = None
    roll: Optional[float] = None
    landmarks_quality: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass
class FacialExpressionPrediction:
    label: str
    probabilities: Dict[str, float]
    confidence: float
    provider: str
    inference_ms: float
    face_quality: float
    is_conclusive: bool
    raw_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalSignal:
    signal_type: str
    started_at: datetime
    updated_at: datetime
    duration_seconds: float
    sample_count: int
    positive_samples: int
    ratio: float
    confidence: float
    observation_quality: float
    active: bool
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        return d


@dataclass
class EngagementWindow:
    session_id: str
    camera_id: str
    track_id: Optional[str]
    student_id: Optional[str]
    started_at: datetime
    ended_at: datetime
    visual_attention_score: Optional[float]
    observation_coverage: float
    observation_quality: float
    state: str  # high | moderate | low | inconclusive
    confidence: float
    contributing_signals: Dict[str, float] = field(default_factory=dict)
    exclusion_reasons: List[str] = field(default_factory=list)
    provenance: Optional[Provenance] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        d["ended_at"] = self.ended_at.isoformat()
        return d
