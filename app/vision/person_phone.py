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
    if _phone_on_chest(phone, person):
        return False
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
    if phone_area / person_area > 0.058:
        return False
    if pcy > py + ph * 0.48:
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


def _phone_lateral_to_face(phone: BBox, face: Optional[BBox], person: Optional[BBox] = None) -> bool:
    """Objeto ao lado do rosto (exibir / fone). Encostar na cara = uso (E3), não lateral."""
    if face is None:
        return False
    fcx, fcy = _center(face)
    pcx, pcy = _center(phone)
    fw = max(float(face[2]), 1.0)
    fh = max(float(face[3]), 1.0)
    phw = max(float(phone[2]), 1.0)
    if abs(pcy - fcy) > fh * 0.85:
        return False
    gap = abs(pcx - fcx) - fw / 2.0 - phw / 2.0
    # Sobreposto ou quase colado no rosto → E3, não "ao lado sem uso".
    if gap <= max(4.0, fw * 0.20):
        return False
    if abs(pcx - fcx) < fw * 0.55:
        return False
    return True


def _phone_raised_to_face(
    phone: BBox,
    face: Optional[BBox],
    person: BBox,
) -> bool:
    """Celular à frente / altura do rosto (uso real). Fone lateral não conta aqui."""
    if face is None:
        return False
    if _phone_in_ear_zone(phone, face, person):
        return False
    if _phone_lateral_to_face(phone, face, person):
        return False
    phone_area = max(1.0, phone[2] * phone[3])
    person_area = max(1.0, person[2] * person[3])
    pcx, pcy = _center(phone)
    fx, fy, fw, fh = face
    at_face_height = (fy - fh * 0.20) <= pcy <= (fy + fh * 1.20)
    # Recorte YOLO (bloco das câmeras) na cara ainda é E3; 0.038 matava esse take.
    min_area = 0.034 if at_face_height else 0.038
    if phone_area / person_area < min_area:
        return False
    _, py, _, ph = person
    # Close-up YuNet: face ~meio corpo; expand 1.55× descia até o peito (E4→E3).
    down = 1.12 if fh >= ph * 0.28 else 1.55
    expanded = (fx - fw * 0.45, fy - fh * 0.25, fw * 1.9, fh * down)
    if _bbox_intersection_area(phone, expanded) / phone_area >= 0.12:
        return True
    if not _phone_near_face_region(phone, face, person):
        return False
    pcx, pcy = _center(phone)
    face_bottom = fy + fh
    extra = fh * 0.20 if fh >= ph * 0.28 else fh * 0.55
    if pcy > face_bottom + extra:
        return False
    return True


def _phone_large_handheld_upper(
    phone: BBox,
    person: BBox,
    face: Optional[BBox],
) -> bool:
    """
    E3 LIVE sem punho: smartphone grande à frente na faixa mão/ombro/rosto.
    Ao lado do rosto (olhar câmera) NÃO é uso — senão E3 come o contrato lateral.
    Fone over-ear ~113×171 NÃO passa (w/h).
    """
    if _phone_in_ear_zone(phone, face, person):
        return False
    if _phone_lateral_to_face(phone, face, person):
        return False
    px, py, pw, ph = person
    pcx, pcy = _center(phone)
    phone_area = max(1.0, phone[2] * phone[3])
    person_area = max(1.0, pw * ph)
    area_ratio = phone_area / person_area
    w, h = float(phone[2]), float(phone[3])
    # Corte acima do over-ear C típico (113×171); handset LIVE ~190×261 passa.
    if area_ratio < 0.035 or w < 140 or h < 180:
        return False
    hw = h / max(w, 1.0)
    if not (1.10 <= hw <= 2.55):
        return False
    # Peito E4: centro no torso médio, sem tamanho de "mão erguida" perto do rosto
    if face is not None:
        face_bottom = face[1] + face[3]
        if pcy > face_bottom + max(face[3] * 0.95, 60.0) and py + ph * 0.40 <= pcy <= py + ph * 0.85:
            # Claramente abaixo do rosto no peito
            if abs(pcx - _center(face)[0]) < face[2] * 0.9:
                return False
    elif _phone_on_chest(phone, person, None):
        return False
    if pcy > py + ph * 0.85:
        return False
    if pcy < py - ph * 0.08:
        return False
    if not (px - pw * 0.28 <= pcx <= px + pw * 1.28):
        return False
    if face is None:
        return pcy <= py + ph * 0.72
    if _phone_near_face_region(phone, face, person):
        return True
    face_bottom = face[1] + face[3]
    if pcy <= face_bottom + max(face[3] * 1.0, 55.0):
        return True
    return False


def _phone_on_chest(phone: BBox, person: BBox, face: Optional[BBox] = None) -> bool:
    """Celular no peito/torso — uso passivo. Nunca se estiver à frente do rosto."""
    if face is not None and _phone_raised_to_face(phone, face, person):
        return False
    px, py, pw, ph = person
    pcx, pcy = _center(phone)
    chest_top = py + ph * 0.36
    chest_bottom = py + ph * 0.80
    if face is not None and float(face[3]) < ph * 0.32:
        chest_top = max(chest_top, face[1] + face[3] + max(8.0, face[3] * 0.35))
    if not (chest_top <= pcy <= chest_bottom):
        return False
    if pcx < px + pw * 0.12 or pcx > px + pw * 0.88:
        return False
    return True


def _phone_below_face_on_torso(
    phone: BBox,
    person: BBox,
    face: Optional[BBox],
) -> bool:
    """Celular claramente abaixo do queixo no tronco (peito), não uso à frente do rosto."""
    if face is not None and _phone_raised_to_face(phone, face, person):
        return False
    if face is None:
        return _phone_on_chest(phone, person, face)
    px, py, pw, ph = person
    pcx, pcy = _center(phone)
    if pcx < px - pw * 0.08 or pcx > px + pw * 1.08:
        return False
    face_bottom = face[1] + face[3]
    min_gap = max(10.0, ph * 0.06) if face[3] >= ph * 0.32 else max(10.0, face[3] * 0.45)
    if pcy < face_bottom + min_gap:
        return False
    if pcy > py + ph * 0.92:
        return False
    return True


def _phone_in_hand_heuristic(
    phone: BBox,
    person: BBox,
    face_bbox: Optional[BBox],
) -> bool:
    """
    Heurística sem punho: tronco inferior / colo OU handset grande na faixa superior (E3).
    Peito com olhar à frente NÃO é in_hand (celular encostado no peito).
    """
    if face_bbox and _phone_in_ear_zone(phone, face_bbox, person):
        return False
    if _phone_in_ear_zone(phone, face_bbox, person):
        return False
    if face_bbox is not None and _phone_lateral_to_face(phone, face_bbox, person):
        return False
    if _phone_on_chest(phone, person):
        return False
    if _phone_large_handheld_upper(phone, person, face_bbox):
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
        clear_hold_seconds: float = 2.0,
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
            looking = bool(head_looking_down.get(pid))
            resting_torso = False
            raised_to_face = False
            for ph in owned:
                if _phone_raised_to_face(ph, face_bb, pb):
                    raised_to_face = True
                    for w in wrists.get(pid) or []:
                        if _near_wrist(ph, w, pb):
                            in_hand = True
                            reasons.append("phone_near_wrist")
                    if not in_hand:
                        in_hand = True
                        reasons.append("phone_raised_to_face")
                    continue
                if (
                    face_bb is not None
                    and _phone_lateral_to_face(ph, face_bb, pb)
                    and not looking
                    and not _phone_in_ear_zone(ph, face_bb, pb)
                ):
                    reasons.append("phone_lateral_visible_not_use")
                    continue
                if _phone_large_handheld_upper(ph, pb, face_bb):
                    raised_to_face = True
                    in_hand = True
                    reasons.append("phone_large_handheld_upper")
                    continue
                if _phone_below_face_on_torso(ph, pb, face_bb) and not looking:
                    resting_torso = True
                    reasons.append("phone_resting_on_torso_looking_forward")
                    continue
                chest = _phone_on_chest(ph, pb, face_bb)
                if chest and not looking:
                    reasons.append("phone_resting_on_chest")
                    continue
                for w in wrists.get(pid) or []:
                    if _near_wrist(ph, w, pb):
                        in_hand = True
                        reasons.append("phone_near_wrist")
                if not in_hand and _phone_in_hand_heuristic(ph, pb, face_bb):
                    in_hand = True
                    reasons.append("phone_in_hand_heuristic")
            if resting_torso and not looking and not raised_to_face:
                in_hand = False

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
                if (
                    not raised_to_face
                    and (resting_torso or any(_phone_on_chest(ph, pb, face_bb) for ph in owned))
                    and not looking
                ):
                    in_hand = False
                    in_hand_dur = 0.0
                    self._in_hand_since.pop(pid, None)
                    reasons.append("phone_resting_blocks_interaction")
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
