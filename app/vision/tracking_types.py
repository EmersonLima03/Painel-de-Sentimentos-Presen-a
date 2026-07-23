"""PersonTrack, FaceTrack e IdentityBinding — camadas separadas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Protocol, Tuple


BBox = Tuple[float, float, float, float]  # x, y, w, h


@dataclass
class PersonTrack:
    track_id: str
    camera_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    bounding_box: BBox
    tracking_confidence: float = 0.0
    visible: bool = True
    occlusion_level: float = 0.0
    observation_quality: float = 0.0


@dataclass
class FaceTrack:
    track_id: str
    camera_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    face_bbox: BBox
    tracking_confidence: float = 0.0
    visible: bool = True
    occlusion_level: float = 0.0
    observation_quality: float = 0.0
    landmarks_quality: float = 0.0


@dataclass
class IdentityBindingResult:
    person_track_id: Optional[str]
    face_track_id: Optional[str]
    student_id: Optional[str]
    identity_confidence: float
    binding_confidence: float
    reasons: List[str] = field(default_factory=list)
    # Binding NUNCA escreve attendance_checkin


class TrackerAdapter(Protocol):
    def update(self, detections, frame, timestamp) -> list:
        ...


class IdentityBinder(Protocol):
    def bind(
        self,
        person_tracks: List[PersonTrack],
        face_tracks: List[FaceTrack],
        *,
        embeddings: Optional[dict] = None,
    ) -> List[IdentityBindingResult]:
        ...
