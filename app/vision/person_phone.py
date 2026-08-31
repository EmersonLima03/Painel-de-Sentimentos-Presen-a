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


def _bbox_intersection_area(a: BBox, b: BBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1)


def _phone_in_lower_body(phone: BBox, person: BBox) -> bool:
    """Celular na região inferior do corpo (punhos indisponíveis no pose lite)."""
    px, py, pw, ph = person
    pcx, pcy = _center(phone)
    # Abaixo do corpo ≈ mesa — não tratar como in_hand sem punho
    if pcy > py + ph * 0.90:
        return False
    lower_y = py + ph * 0.38
    if pcy < lower_y:
        return False
    margin = 0.12 * max(pw, ph)
    return (px - margin) <= pcx <= (px + pw + margin)


def _phone_overlaps_lower_torso(phone: BBox, person: BBox) -> bool:
    px, py, pw, ph = person
    lower = (px, py + ph * 0.35, pw, ph * 0.65)
    phone_area = max(1.0, phone[2] * phone[3])
    return _bbox_intersection_area(phone, lower) / phone_area >= 0.12


def _phone_near_face_region(phone: BBox, face: BBox, person: BBox) -> bool:
    """Celular próximo ao rosto (altura da face) — usado só como near, não in_hand sozinho."""
    fcx, fcy = _center(face)
    pcx, pcy = _center(phone)
    fdiag = max(1.0, (face[2] ** 2 + face[3] ** 2) ** 0.5)
    dist = ((pcx - fcx) ** 2 + (pcy - fcy) ** 2) ** 0.5 / fdiag
    return dist <= 1.35


def _phone_in_ear_zone(phone: BBox, face: Optional[BBox], person: BBox) -> bool:
    """Fone/orelha: bbox pequena no terço superior lateral da pessoa (ou lateral ao rosto)."""
    px, py, pw, ph = person
    pcx, pcy = _center(phone)
    phone_area = max(1.0, phone[2] * phone[3])
    person_area = max(1.0, pw * ph)
    if phone_area / person_area > 0.045:
        return False
    if pcy > py + ph * 0.32:
        return False
    lateral = pcx < px + pw * 0.28 or pcx > px + pw * 0.72
    if not lateral:
        return False
    if face is not None:
        fcx, fcy = _center(face)
        # lateral ao rosto, não na frente
        if abs(pcx - fcx) < face[2] * 0.35 and abs(pcy - fcy) < face[3] * 0.55:
            return False
    return True


def _phone_on_chest(phone: BBox, person: BBox) -> bool:
    """Celular deitado no peito/torso superior (comum em uso passivo)."""
    pw_phone, ph_phone = phone[2], phone[3]
    if pw_phone / max(ph_phone, 1.0) < 1.15:
        return False
    px, py, pw, ph = person
    pcx, pcy = _center(phone)
    chest_top = py + ph * 0.28
    chest_bottom = py + ph * 0.58
    if not (chest_top <= pcy <= chest_bottom):
        return False
    margin = 0.12 * pw
    return (px - margin) <= pcx <= (px + pw + margin)


def _phone_in_hand_heuristic(
    phone: BBox,
    person: BBox,
    face_bbox: Optional[BBox],
) -> bool:
    """
    Heurística sem punho: peito / tronco inferior.
    NÃO promover in_hand só por proximidade ao rosto (fone/orelha geram FP).
    """
    if face_bbox and _phone_in_ear_zone(phone, face_bbox, person):
        return False
    if _phone_in_ear_zone(phone, face_bbox, person):
        return False
    if _phone_on_chest(phone, person):
        return True
    if _phone_in_lower_body(phone, person) and _phone_overlaps_lower_torso(phone, person):
        return True
    return False


class PersonPhoneAssociator:
    def __init__(
        self,
        *,
        minimum_interaction_seconds: float = 5.0,
        probable_seconds: float = 12.0,
        near_dist_norm: float = 0.55,
        ambiguous_gap: float = 0.12,
        interaction_requires_in_hand: bool = True,
        clear_hold_seconds: float = 3.0,
    ):
        self.minimum_interaction_seconds = minimum_interaction_seconds
        self.probable_seconds = probable_seconds
        self.near_dist_norm = near_dist_norm
        self.ambiguous_gap = ambiguous_gap
        self.interaction_requires_in_hand = interaction_requires_in_hand
        self.clear_hold_seconds = float(clear_hold_seconds)
        self._near_since: Dict[str, float] = {}
        self._in_hand_since: Dict[str, float] = {}
        self._near_last_seen: Dict[str, float] = {}
        self._in_hand_last_seen: Dict[str, float] = {}
        self._last_level: Dict[str, str] = {}
        self._last_reasons: Dict[str, List[str]] = {}
        self._last_conf: Dict[str, float] = {}

    def update(
        self,
        *,
        now: float,
        person_tracks: Dict[str, BBox],
        phone_boxes: List[Tuple[float, float, float, float, float]],
        wrists: Optional[Dict[str, List[Tuple[float, float]]]] = None,
        head_looking_down: Optional[Dict[str, bool]] = None,
        face_bboxes: Optional[Dict[str, BBox]] = None,
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
        face_bboxes = face_bboxes or {}

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

            face_bb = face_bboxes.get(pid)
            for ph in owned:
                for w in wrists.get(pid) or []:
                    if _near_wrist(ph, w, pb):
                        in_hand = True
                        reasons.append("phone_near_wrist")
                if not in_hand and _phone_in_hand_heuristic(ph, pb, face_bb):
                    in_hand = True
                    if _phone_on_chest(ph, pb):
                        reasons.append("phone_on_chest")
                    else:
                        reasons.append("phone_in_hand_heuristic")

            if ambiguous and not owned:
                self._near_since.pop(pid, None)
                self._in_hand_since.pop(pid, None)
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
                self._near_last_seen[pid] = now
                dur = now - self._near_since[pid]
                if in_hand:
                    if pid not in self._in_hand_since:
                        self._in_hand_since[pid] = now
                    self._in_hand_last_seen[pid] = now
                    in_hand_dur = now - self._in_hand_since[pid]
                else:
                    # hold breve de in_hand se punho/detecção piscou
                    if (
                        pid in self._in_hand_last_seen
                        and (now - float(self._in_hand_last_seen[pid])) < self.clear_hold_seconds
                        and pid in self._in_hand_since
                    ):
                        in_hand = True
                        in_hand_dur = now - self._in_hand_since[pid]
                        reasons.append("in_hand_temporal_hold")
                    else:
                        self._in_hand_since.pop(pid, None)
                        in_hand_dur = 0.0
                reasons.append(f"near_dist_norm={best:.2f}")
                if in_hand:
                    level = "phone_in_hand"
                    conf = 0.45
                else:
                    level = "phone_near_person"
                    conf = 0.35
                looking = bool(head_looking_down.get(pid))
                can_interact = in_hand or not self.interaction_requires_in_hand
                interact_dur = in_hand_dur if self.interaction_requires_in_hand else dur
                if can_interact and in_hand and looking and interact_dur >= self.probable_seconds:
                    level = "probable_phone_interaction"
                    conf = 0.75
                    reasons.append("persistent_in_hand_head_down")
                elif can_interact and in_hand and interact_dur >= self.probable_seconds:
                    level = "probable_phone_interaction"
                    conf = 0.7
                    reasons.append("persistent_in_hand")
                elif can_interact and in_hand and interact_dur >= self.minimum_interaction_seconds:
                    level = "possible_phone_interaction"
                    conf = 0.55
                    reasons.append("min_interaction_in_hand")
                elif can_interact and not self.interaction_requires_in_hand and dur >= self.probable_seconds:
                    level = "probable_phone_interaction"
                    conf = 0.65
                    reasons.append("persistent_near_phone")
                elif can_interact and not self.interaction_requires_in_hand and dur >= self.minimum_interaction_seconds:
                    level = "possible_phone_interaction"
                    conf = 0.5
                    reasons.append("min_interaction_duration")
                elif in_hand:
                    level = "phone_in_hand"
                elif near and self.interaction_requires_in_hand:
                    reasons.append("near_without_wrist_not_interaction")
                self._last_level[pid] = level
                self._last_reasons[pid] = list(reasons)
                self._last_conf[pid] = conf
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
            elif (
                pid in self._near_last_seen
                and (now - float(self._near_last_seen[pid])) < self.clear_hold_seconds
                and pid in self._near_since
            ):
                # Detecção piscou: manter near/in_hand por hold curto
                active_near.add(pid)
                dur = now - self._near_since[pid]
                held_in_hand = (
                    pid in self._in_hand_since
                    and pid in self._in_hand_last_seen
                    and (now - float(self._in_hand_last_seen[pid])) < self.clear_hold_seconds
                )
                level = self._last_level.get(pid) or (
                    "phone_in_hand" if held_in_hand else "phone_near_person"
                )
                reasons = list(self._last_reasons.get(pid) or []) + ["phone_assoc_temporal_hold"]
                conf = float(self._last_conf.get(pid) or (0.4 if held_in_hand else 0.32))
                out.append(
                    PhoneAssociationState(
                        person_track_id=pid,
                        phone_visible=True,
                        phone_near_person=True,
                        phone_in_hand=held_in_hand,
                        ambiguous=False,
                        interaction_level=level,
                        duration_seconds=dur,
                        confidence=conf,
                        reasons=reasons,
                    )
                )
            else:
                self._near_since.pop(pid, None)
                self._in_hand_since.pop(pid, None)
                self._near_last_seen.pop(pid, None)
                self._in_hand_last_seen.pop(pid, None)
                self._last_level.pop(pid, None)
                self._last_reasons.pop(pid, None)
                self._last_conf.pop(pid, None)
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
                # só limpa se hold já expirou
                last = self._near_last_seen.get(pid)
                if last is None or (now - float(last)) >= self.clear_hold_seconds:
                    self._near_since.pop(pid, None)
                    self._in_hand_since.pop(pid, None)
                    self._near_last_seen.pop(pid, None)
                    self._in_hand_last_seen.pop(pid, None)
                    self._last_level.pop(pid, None)
                    self._last_reasons.pop(pid, None)
                    self._last_conf.pop(pid, None)
        return out


def owner_is_ambiguous(ph, phones, phone_owners) -> bool:
    for p, o in zip(phones, phone_owners):
        if p is ph:
            return o is None
    return False
