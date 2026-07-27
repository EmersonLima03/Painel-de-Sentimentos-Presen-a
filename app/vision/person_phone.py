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
    phone_in_hand: bool = False
    ambiguous: bool = False
    # not_detected | phone_visible | phone_near_person | phone_in_hand |
    # possible_phone_interaction | probable_phone_interaction
    # Nunca: confirmed_phone_interaction
    interaction_level: str = "not_detected"
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


def _near_wrist(phone: BBox, wrist: Optional[Tuple[float, float]], person: BBox) -> bool:
    if wrist is None:
        return False
    pcx, pcy = _center(phone)
    diag = max(1.0, (person[2] ** 2 + person[3] ** 2) ** 0.5)
    return ((pcx - wrist[0]) ** 2 + (pcy - wrist[1]) ** 2) ** 0.5 / diag <= 0.28


class PersonPhoneAssociator:
    def __init__(
        self,
        *,
        minimum_interaction_seconds: float = 5.0,
        probable_seconds: float = 12.0,
        near_dist_norm: float = 0.55,
        ambiguous_gap: float = 0.12,
    ):
        self.minimum_interaction_seconds = minimum_interaction_seconds
        self.probable_seconds = probable_seconds
        self.near_dist_norm = near_dist_norm
        self.ambiguous_gap = ambiguous_gap
        self._near_since: Dict[str, float] = {}

    def update(
        self,
        *,
        now: float,
        person_tracks: Dict[str, BBox],
        phone_boxes: List[Tuple[float, float, float, float, float]],
        wrists: Optional[Dict[str, List[Tuple[float, float]]]] = None,
        head_looking_down: Optional[Dict[str, bool]] = None,
    ) -> List[PhoneAssociationState]:
        """
        Fluxo: detectado → assoc person → near tronco/mão → phone_in_hand → duração.
        Celular entre duas pessoas permanece ambíguo (não escala a interaction).
        Nunca retorna confirmed_*.
        """
        out: List[PhoneAssociationState] = []
        active_near = set()
        phones = [p[:4] for p in phone_boxes]
        phone_visible = len(phones) > 0
        wrists = wrists or {}
        head_looking_down = head_looking_down or {}

        # por telefone: scores por pessoa (ambiguidade)
        phone_owners: List[Optional[str]] = []
        for ph in phones:
            scores = []
            for pid, pb in person_tracks.items():
                d = _dist_norm(ph, pb)
                score = 1.0 / (1.0 + d)
                if _phone_in_or_near_person(ph, pb):
                    score += 0.3
                scores.append((score, pid, d))
            scores.sort(reverse=True)
            if not scores:
                phone_owners.append(None)
            elif len(scores) >= 2 and (scores[0][0] - scores[1][0]) < self.ambiguous_gap:
                phone_owners.append(None)  # ambíguo
            elif scores[0][0] >= 0.45 or scores[0][2] <= self.near_dist_norm:
                phone_owners.append(scores[0][1])
            else:
                phone_owners.append(None)

        for pid, pb in person_tracks.items():
            reasons: List[str] = []
            near = False
            in_hand = False
            ambiguous = False
            best = 999.0
            owned = [ph for ph, owner in zip(phones, phone_owners) if owner == pid]
            ambiguous_phones = [
                ph for ph, owner in zip(phones, phone_owners) if owner is None and phone_visible
            ]

            for ph in phones:
                d = _dist_norm(ph, pb)
                best = min(best, d)
                if ph in owned or (_phone_in_or_near_person(ph, pb) and ph not in ambiguous_phones):
                    near = True
                # telefone ambíguo perto de ambos
                if owner_is_ambiguous(ph, phones, phone_owners) and d <= self.near_dist_norm:
                    ambiguous = True
                    reasons.append("phone_ambiguous_between_persons")

            for ph in owned:
                for w in wrists.get(pid) or []:
                    if _near_wrist(ph, w, pb):
                        in_hand = True
                        reasons.append("phone_near_wrist")

            if ambiguous and not owned:
                self._near_since.pop(pid, None)
                out.append(
                    PhoneAssociationState(
                        person_track_id=pid,
                        phone_visible=phone_visible,
                        phone_near_person=False,
                        phone_in_hand=False,
                        ambiguous=True,
                        interaction_level="phone_visible" if phone_visible else "not_detected",
                        duration_seconds=0.0,
                        confidence=0.2,
                        reasons=reasons or ["ambiguous_association"],
                    )
                )
                continue

            if near or in_hand:
                active_near.add(pid)
                if pid not in self._near_since:
                    self._near_since[pid] = now
                dur = now - self._near_since[pid]
                reasons.append(f"near_dist_norm={best:.2f}")
                if in_hand:
                    level = "phone_in_hand"
                    conf = 0.45
                else:
                    level = "phone_near_person"
                    conf = 0.35
                looking = bool(head_looking_down.get(pid))
                if in_hand and looking and dur >= self.probable_seconds:
                    level = "probable_phone_interaction"
                    conf = 0.75
                    reasons.append("persistent_in_hand_head_down")
                elif (in_hand or near) and dur >= self.probable_seconds:
                    level = "probable_phone_interaction"
                    conf = 0.7
                    reasons.append("persistent_near_phone")
                elif (in_hand or near) and dur >= self.minimum_interaction_seconds:
                    level = "possible_phone_interaction"
                    conf = 0.55
                    reasons.append("min_interaction_duration")
                elif in_hand:
                    level = "phone_in_hand"
                out.append(
                    PhoneAssociationState(
                        person_track_id=pid,
                        phone_visible=phone_visible,
                        phone_near_person=True,
                        phone_in_hand=in_hand,
                        ambiguous=False,
                        interaction_level=level,
                        duration_seconds=dur,
                        confidence=conf,
                        reasons=reasons,
                    )
                )
            else:
                self._near_since.pop(pid, None)
                level = "phone_visible" if phone_visible else "not_detected"
                out.append(
                    PhoneAssociationState(
                        person_track_id=pid,
                        phone_visible=phone_visible,
                        phone_near_person=False,
                        phone_in_hand=False,
                        ambiguous=False,
                        interaction_level=level,
                        duration_seconds=0.0,
                        confidence=0.25 if phone_visible else 0.0,
                        reasons=["phone_visible_only"] if phone_visible else [],
                    )
                )

        for pid in list(self._near_since.keys()):
            if pid not in active_near:
                self._near_since.pop(pid, None)
        return out


def owner_is_ambiguous(ph, phones, phone_owners) -> bool:
    for p, o in zip(phones, phone_owners):
        if p is ph:
            return o is None
    return False
