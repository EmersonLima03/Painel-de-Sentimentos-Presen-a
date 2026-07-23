"""Associação pessoa–celular. Motor nunca emite confirmed — só possible/probable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

BBox = Tuple[float, float, float, float]


@dataclass
class PhoneAssociationState:
    person_track_id: str
    phone_visible: bool = False
    phone_near_person: bool = False
    # Automáticos: phone_visible | phone_near_person | possible_phone_interaction | probable_phone_interaction | none
    # Nunca: confirmed_phone_interaction
    interaction_level: str = "none"
    duration_seconds: float = 0.0
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)


def _center(b: BBox) -> Tuple[float, float]:
    return b[0] + b[2] / 2.0, b[1] + b[3] / 2.0


def _dist_norm(phone: BBox, person: BBox) -> float:
    pcx, pcy = _center(phone)
    rcx, rcy = _center(person)
    diag = max(1.0, (person[2] ** 2 + person[3] ** 2) ** 0.5)
    return ((pcx - rcx) ** 2 + (pcy - rcy) ** 2) ** 0.5 / diag


def _phone_in_or_near_person(phone: BBox, person: BBox, margin: float = 0.15) -> bool:
    px, py, pw, ph = person
    m = margin * max(pw, ph)
    exp = (px - m, py - m, pw + 2 * m, ph + 2 * m)
    cx, cy = _center(phone)
    return exp[0] <= cx <= exp[0] + exp[2] and exp[1] <= cy <= exp[1] + exp[3]


class PersonPhoneAssociator:
    def __init__(
        self,
        *,
        minimum_interaction_seconds: float = 5.0,
        probable_seconds: float = 12.0,
        near_dist_norm: float = 0.55,
    ):
        self.minimum_interaction_seconds = minimum_interaction_seconds
        self.probable_seconds = probable_seconds
        self.near_dist_norm = near_dist_norm
        self._near_since: Dict[str, float] = {}

    def update(
        self,
        *,
        now: float,
        person_tracks: Dict[str, BBox],
        phone_boxes: List[Tuple[float, float, float, float, float]],
    ) -> List[PhoneAssociationState]:
        """
        interaction_level:
          none | phone_visible | phone_near_person | possible_phone_interaction | probable_phone_interaction
        Nunca retorna confirmed_phone_interaction — confirmação é review_status.
        """
        out: List[PhoneAssociationState] = []
        active_near = set()
        phones = [p[:4] for p in phone_boxes]
        phone_visible = len(phones) > 0

        for pid, pb in person_tracks.items():
            reasons: List[str] = []
            near = False
            best = 999.0
            for ph in phones:
                d = _dist_norm(ph, pb)
                best = min(best, d)
                if _phone_in_or_near_person(ph, pb) or d <= self.near_dist_norm:
                    near = True
            if near:
                active_near.add(pid)
                if pid not in self._near_since:
                    self._near_since[pid] = now
                dur = now - self._near_since[pid]
                reasons.append(f"near_dist_norm={best:.2f}")
                level = "phone_near_person"
                conf = 0.35
                if dur >= self.probable_seconds:
                    level = "probable_phone_interaction"
                    conf = 0.75
                    reasons.append("persistent_near_phone")
                elif dur >= self.minimum_interaction_seconds:
                    level = "possible_phone_interaction"
                    conf = 0.55
                    reasons.append("min_interaction_duration")
                out.append(
                    PhoneAssociationState(
                        person_track_id=pid,
                        phone_visible=phone_visible,
                        phone_near_person=True,
                        interaction_level=level,
                        duration_seconds=dur,
                        confidence=conf,
                        reasons=reasons,
                    )
                )
            else:
                self._near_since.pop(pid, None)
                level = "phone_visible" if phone_visible else "none"
                out.append(
                    PhoneAssociationState(
                        person_track_id=pid,
                        phone_visible=phone_visible,
                        phone_near_person=False,
                        interaction_level=level,
                        duration_seconds=0.0,
                        confidence=0.25 if phone_visible else 0.0,
                        reasons=["phone_visible_only"] if phone_visible else [],
                    )
                )

        # limpar tracks ausentes
        for pid in list(self._near_since.keys()):
            if pid not in active_near:
                self._near_since.pop(pid, None)
        return out
