"""Motor de fusão temporal — eventos possible/probable; nunca confirmed_phone; não altera presença."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.vision.domain import Provenance


@dataclass
class InterpretedEvent:
    event_type: str
    severity: str  # possible | probable | inconclusive
    track_id: Optional[str]
    student_id: Optional[str]
    confidence: float
    observation_quality: float
    reasons: List[str] = field(default_factory=list)
    provenance: Optional[Provenance] = None
    # confirmed NÃO é emitido aqui — só via review_status


class FusionEngine:
    def __init__(self, provenance: Optional[Provenance] = None):
        self.provenance = provenance or Provenance(
            provider="fusion",
            model_name="rule_engine",
            model_version="rules-v0-baseline",
        )

    def interpret_phone(self, level: str, confidence: float, quality: float, track_id: str) -> Optional[InterpretedEvent]:
        # Aceita aliases curtos e nomes canônicos
        norm = {
            "possible": "possible_phone_interaction",
            "probable": "probable_phone_interaction",
            "possible_phone_interaction": "possible_phone_interaction",
            "probable_phone_interaction": "probable_phone_interaction",
        }.get(level)
        if not norm:
            return None
        if quality < 0.45:
            return InterpretedEvent(
                event_type="possible_phone_interaction",
                severity="inconclusive",
                track_id=track_id,
                student_id=None,
                confidence=confidence,
                observation_quality=quality,
                reasons=["insufficient_observation_quality"],
                provenance=self.provenance,
            )
        sev = "probable" if "probable" in norm else "possible"
        return InterpretedEvent(
            event_type=norm,
            severity=sev,
            track_id=track_id,
            student_id=None,
            confidence=confidence,
            observation_quality=quality,
            reasons=[f"level={level}"],
            provenance=self.provenance,
        )

    def interpret_drowsiness(
        self,
        *,
        eyes_closed_ratio: float,
        head_down: bool,
        duration_s: float,
        quality: float,
        track_id: str,
        min_duration: float = 8.0,
    ) -> Optional[InterpretedEvent]:
        if quality < 0.6:
            return InterpretedEvent(
                event_type="apparent_drowsiness",
                severity="inconclusive",
                track_id=track_id,
                student_id=None,
                confidence=0.0,
                observation_quality=quality,
                reasons=["insufficient_observation_quality"],
                provenance=self.provenance,
            )
        if duration_s < min_duration:
            return None
        if eyes_closed_ratio >= 0.7 and head_down:
            return InterpretedEvent(
                event_type="apparent_drowsiness",
                severity="probable",
                track_id=track_id,
                student_id=None,
                confidence=0.7,
                observation_quality=quality,
                reasons=["eyes_closed", "head_down", f"duration={duration_s:.1f}"],
                provenance=self.provenance,
            )
        if eyes_closed_ratio >= 0.7:
            return InterpretedEvent(
                event_type="apparent_drowsiness",
                severity="possible",
                track_id=track_id,
                student_id=None,
                confidence=0.55,
                observation_quality=quality,
                reasons=["eyes_closed_persistent"],
                provenance=self.provenance,
            )
        return None

    def to_shadow_dict(self, ev: InterpretedEvent) -> Dict[str, Any]:
        d = {
            "event_type": ev.event_type,
            "severity": ev.severity,
            "track_id": ev.track_id,
            "student_id": ev.student_id,
            "confidence": ev.confidence,
            "observation_quality": ev.observation_quality,
            "reasons": ev.reasons,
            "review_status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            # Nunca confirmed aqui
            "auto_confirmed": False,
        }
        if ev.provenance:
            d.update(ev.provenance.to_dict())
        return d
