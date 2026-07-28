"""
IdentityBinding — continuidade por person_track_id.

Semântica P0:
- face_missing_ttl_seconds = idade da confirmação facial (stale UI / decay de face_confirmation_confidence).
- NÃO expira student_id nem força uncertain só pelo tempo sem rosto.
- body_continuity_confidence só cai por evidência corporal/ambiguidade (sem TTL oculto).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.logging import get_logger
from app.vision.face_person_association import FacePersonAssociator, FacePersonAssociation
from app.vision.tracking_types import FaceTrack, IdentityBindingResult, PersonTrack

logger = get_logger(__name__)

BODY_CONTINUITY_UNCERTAIN_THRESHOLD = 0.45
BODY_CONTINUITY_TEMP_LOST_PENALTY = 0.15
BODY_CONTINUITY_PROXIMITY_PENALTY = 0.20
BODY_CONTINUITY_LOW_TRACK_PENALTY = 0.10
BODY_CONTINUITY_TEMP_LOST_UNCERTAIN_SECONDS = 4.0
BODY_CONTINUITY_SPATIAL_REASSOC_CAP = 0.55
BODY_CONTINUITY_AMBIGUOUS_CAP = 0.35
BODY_CONTINUITY_PENDING_SWITCH_CAP = 0.40
PERSON_PERSON_IOU_AMBIGUITY = 0.15


def _iou_boxes(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


@dataclass
class IdentityState:
    student_id: Optional[str] = None
    confidence: float = 0.0  # face_confirmation_confidence (pode decay temporal)
    source: str = "unknown"  # face_recognition | body_continuity | spatial_reassociation | unknown
    identity_state: str = "unknown"  # face_confirmed | body_continuity | uncertain | unknown
    full_name: Optional[str] = None
    face_visible: bool = False
    last_face_seen_at: Optional[float] = None
    last_face_confirmation_at: Optional[float] = None
    seconds_since_face_seen: float = 0.0
    seconds_since_face_confirmation: float = 0.0
    margin: Optional[float] = None
    pending_switch: Optional[str] = None
    confirmation_count: int = 0
    cooldown_until: Optional[float] = None
    face_track_id: Optional[str] = None
    association: Optional[dict] = None
    body_continuity_confidence: float = 0.0
    face_confirmation_confidence: float = 0.0
    revalidation_required: bool = False
    identity_source: str = "unknown"
    ambiguity_reasons: List[str] = field(default_factory=list)
    temporarily_lost_since: Optional[float] = None
    spatial_reassociation: bool = False
    face_confirmation_stale: bool = False
    reconfirmation_recommended: bool = False

    def as_dict(self) -> dict:
        return {
            "student_id": self.student_id,
            "full_name": self.full_name,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "identity_confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "face_confirmation_confidence": round(float(self.face_confirmation_confidence or 0.0), 3),
            "source": self.source,
            "identity_source": self.identity_source or self.source,
            "identity_state": self.identity_state,
            "face_visible": self.face_visible,
            "last_face_seen_at": self.last_face_seen_at,
            "last_face_confirmation_at": self.last_face_confirmation_at,
            "seconds_since_face_seen": round(self.seconds_since_face_seen, 2),
            "seconds_since_face_confirmation": round(self.seconds_since_face_confirmation, 2),
            "margin": None if self.margin is None else round(self.margin, 3),
            "pending_switch": self.pending_switch,
            "confirmation_count": self.confirmation_count,
            "cooldown_until": self.cooldown_until,
            "body_continuity_confidence": round(float(self.body_continuity_confidence or 0.0), 3),
            "revalidation_required": bool(self.revalidation_required),
            "ambiguity_reasons": list(self.ambiguity_reasons or []),
            "spatial_reassociation": bool(self.spatial_reassociation),
            "face_confirmation_stale": bool(self.face_confirmation_stale),
            "reconfirmation_recommended": bool(self.reconfirmation_recommended),
        }


class IdentityBindingEngine:
    """
    Liga person_track ↔ face_track ↔ student_id com continuidade corporal.
    """

    def __init__(
        self,
        history_bonus: float = 0.15,
        *,
        face_missing_ttl_seconds: float = 12.0,
        minimum_new_identity_confidence: float = 0.75,
        minimum_identity_margin: float = 0.10,
        confirmations_before_switch: int = 3,
        identity_switch_cooldown_seconds: float = 10.0,
        confidence_decay_per_second: float = 0.04,
        body_continuity_uncertain_threshold: float = BODY_CONTINUITY_UNCERTAIN_THRESHOLD,
        temporarily_lost_uncertain_seconds: float = BODY_CONTINUITY_TEMP_LOST_UNCERTAIN_SECONDS,
    ):
        self.history_bonus = history_bonus
        self.face_missing_ttl_seconds = face_missing_ttl_seconds
        self.minimum_new_identity_confidence = minimum_new_identity_confidence
        self.minimum_identity_margin = minimum_identity_margin
        self.confirmations_before_switch = confirmations_before_switch
        self.identity_switch_cooldown_seconds = identity_switch_cooldown_seconds
        self.confidence_decay_per_second = confidence_decay_per_second
        self.body_continuity_uncertain_threshold = body_continuity_uncertain_threshold
        self.temporarily_lost_uncertain_seconds = temporarily_lost_uncertain_seconds
        self._associator = FacePersonAssociator(history_bonus=history_bonus)
        self._states: Dict[str, IdentityState] = {}
        self._student_to_track: Dict[str, str] = {}
        self._events: List[dict] = []
        self._prev_boxes: Dict[str, Tuple[float, float, float, float]] = {}

    def drain_events(self) -> List[dict]:
        out = list(self._events)
        self._events.clear()
        return out

    def _emit(self, event_type: str, **payload) -> None:
        ev = {"event_type": event_type, **payload}
        self._events.append(ev)
        logger.info(event_type, **{k: v for k, v in payload.items() if k != "reasons"})

    def get_state(self, person_track_id: str) -> IdentityState:
        if person_track_id not in self._states:
            self._states[person_track_id] = IdentityState()
        return self._states[person_track_id]

    def expire_track(self, person_track_id: str) -> None:
        st = self._states.pop(person_track_id, None)
        self._prev_boxes.pop(person_track_id, None)
        if st and st.student_id:
            if self._student_to_track.get(st.student_id) == person_track_id:
                self._student_to_track.pop(st.student_id, None)
            self._emit(
                "identity_binding_expired",
                person_track_id=person_track_id,
                student_id=st.student_id,
                reason="person_track_ended",
            )

    def update_continuity(
        self,
        *,
        now: float,
        person_tracks: List[PersonTrack],
        face_tracks: List[FaceTrack],
        face_identities: Optional[Dict[str, dict]] = None,
        person_meta: Optional[Dict[str, dict]] = None,
    ) -> Dict[str, IdentityState]:
        """
        face_identities[face_track_id] = {student_id, confidence, margin?, top2_score?}
        person_meta[person_track_id] = opcional:
          tracking_state, tracking_confidence, spatial_reassociation, seconds_since_person_detection
        """
        face_identities = face_identities or {}
        person_meta = person_meta or {}
        associations = self._associator.associate(person_tracks, face_tracks)
        assoc_by_person = {a.person_track_id: a for a in associations if a.person_track_id}
        active_pids = {p.track_id for p in person_tracks}

        for pid in list(self._states.keys()):
            if pid not in active_pids:
                self.expire_track(pid)

        # proximidade pessoa-pessoa
        boxes = {p.track_id: p.bounding_box for p in person_tracks}
        proximity_ambiguous: Dict[str, List[str]] = {pid: [] for pid in boxes}
        pids = list(boxes.keys())
        for i, a in enumerate(pids):
            for b in pids[i + 1 :]:
                if _iou_boxes(boxes[a], boxes[b]) > PERSON_PERSON_IOU_AMBIGUITY:
                    proximity_ambiguous[a].append("person_overlap")
                    proximity_ambiguous[b].append("person_overlap")

        out: Dict[str, IdentityState] = {}
        for person in person_tracks:
            st = self.get_state(person.track_id)
            assoc = assoc_by_person.get(person.track_id)
            st.association = assoc.as_dict() if assoc else None
            meta = person_meta.get(person.track_id) or {}
            tracking_state = str(
                meta.get("tracking_state")
                or getattr(person, "tracking_state", None)
                or "active"
            )
            track_conf = float(
                meta.get("tracking_confidence")
                if meta.get("tracking_confidence") is not None
                else getattr(person, "tracking_confidence", 0.9) or 0.9
            )
            spatial_reassoc = bool(meta.get("spatial_reassociation", False))
            if tracking_state == "reassociated":
                spatial_reassoc = True
            seconds_lost = float(
                meta.get("seconds_since_person_detection")
                if meta.get("seconds_since_person_detection") is not None
                else getattr(person, "seconds_since_person_detection", 0.0) or 0.0
            )

            # mudança brusca de posição
            abrupt = False
            prev = self._prev_boxes.get(person.track_id)
            if prev is not None and tracking_state == "active":
                if _iou_boxes(prev, person.bounding_box) < 0.05:
                    cx0, cy0 = prev[0] + prev[2] / 2, prev[1] + prev[3] / 2
                    bb = person.bounding_box
                    cx1, cy1 = bb[0] + bb[2] / 2, bb[1] + bb[3] / 2
                    diag = max(1.0, (prev[2] ** 2 + prev[3] ** 2) ** 0.5)
                    if ((cx0 - cx1) ** 2 + (cy0 - cy1) ** 2) ** 0.5 / diag > 1.2:
                        abrupt = True
            if tracking_state == "active":
                self._prev_boxes[person.track_id] = person.bounding_box

            face_id = assoc.face_track_id if assoc and not assoc.ambiguous else None
            if assoc and assoc.ambiguous:
                st.face_visible = bool(assoc.face_track_id)
                if st.student_id and st.last_face_seen_at is not None:
                    st.seconds_since_face_seen = max(0.0, now - st.last_face_seen_at)
                self._apply_no_face_continuity(
                    st,
                    person.track_id,
                    now,
                    tracking_state=tracking_state,
                    track_conf=track_conf,
                    spatial_reassoc=spatial_reassoc,
                    seconds_lost=seconds_lost,
                    ambiguous_assoc=True,
                    proximity_reasons=proximity_ambiguous.get(person.track_id) or [],
                    abrupt=abrupt,
                )
                out[person.track_id] = st
                continue

            if face_id and face_id in face_identities:
                cand = face_identities[face_id]
                self._apply_face_observation(person.track_id, st, cand, assoc, now)
                # face path already set identity_state; still apply body penalties if any
                self._finalize_with_body_signals(
                    st,
                    now,
                    tracking_state=tracking_state,
                    track_conf=track_conf,
                    spatial_reassoc=spatial_reassoc,
                    seconds_lost=seconds_lost,
                    ambiguous_assoc=False,
                    proximity_reasons=proximity_ambiguous.get(person.track_id) or [],
                    abrupt=abrupt,
                    face_just_confirmed=st.identity_state == "face_confirmed",
                )
            elif face_id:
                st.face_visible = True
                st.face_track_id = face_id
                st.last_face_seen_at = now
                st.seconds_since_face_seen = 0.0
                if st.student_id:
                    self._apply_no_face_continuity(
                        st,
                        person.track_id,
                        now,
                        tracking_state=tracking_state,
                        track_conf=track_conf,
                        spatial_reassoc=spatial_reassoc,
                        seconds_lost=seconds_lost,
                        ambiguous_assoc=False,
                        proximity_reasons=proximity_ambiguous.get(person.track_id) or [],
                        abrupt=abrupt,
                        face_seen_unidentified=True,
                    )
                else:
                    st.source = "unknown"
                    st.identity_source = "unknown"
                    st.identity_state = "unknown"
                    st.revalidation_required = True
            else:
                st.face_visible = False
                st.face_track_id = None
                if st.last_face_seen_at is not None:
                    st.seconds_since_face_seen = max(0.0, now - st.last_face_seen_at)
                else:
                    st.seconds_since_face_seen = 999.0
                self._apply_no_face_continuity(
                    st,
                    person.track_id,
                    now,
                    tracking_state=tracking_state,
                    track_conf=track_conf,
                    spatial_reassoc=spatial_reassoc,
                    seconds_lost=seconds_lost,
                    ambiguous_assoc=False,
                    proximity_reasons=proximity_ambiguous.get(person.track_id) or [],
                    abrupt=abrupt,
                )

            out[person.track_id] = st
        return out

    def _apply_face_confirmation_decay(self, st: IdentityState, now: float) -> None:
        """Decay só em face_confirmation_confidence — nunca derruba body_continuity sozinho."""
        if st.last_face_confirmation_at is None:
            st.seconds_since_face_confirmation = 999.0
            st.face_confirmation_stale = True
            st.reconfirmation_recommended = bool(st.student_id)
            return
        gap = max(0.0, now - st.last_face_confirmation_at)
        st.seconds_since_face_confirmation = gap
        st.face_confirmation_stale = gap > self.face_missing_ttl_seconds
        st.reconfirmation_recommended = st.face_confirmation_stale and bool(st.student_id)
        if gap > self.face_missing_ttl_seconds:
            excess = gap - self.face_missing_ttl_seconds
            decay = self.confidence_decay_per_second * excess
            st.face_confirmation_confidence = max(0.0, float(st.face_confirmation_confidence) - decay)
            # confidence espelha face confirmation para compatibilidade de API
            st.confidence = st.face_confirmation_confidence

    def _apply_no_face_continuity(
        self,
        st: IdentityState,
        person_track_id: str,
        now: float,
        *,
        tracking_state: str,
        track_conf: float,
        spatial_reassoc: bool,
        seconds_lost: float,
        ambiguous_assoc: bool,
        proximity_reasons: List[str],
        abrupt: bool,
        face_seen_unidentified: bool = False,
    ) -> None:
        if not st.student_id:
            st.source = "unknown"
            st.identity_source = "unknown"
            st.identity_state = "unknown"
            st.confidence = 0.0
            st.revalidation_required = True
            return

        self._apply_face_confirmation_decay(st, now)

        if st.identity_state == "face_confirmed" or st.source == "face_recognition":
            # entrar em body_continuity com snapshot da última face
            if st.body_continuity_confidence <= 0:
                st.body_continuity_confidence = min(1.0, float(st.face_confirmation_confidence or st.confidence or 0.0))
            st.identity_state = "body_continuity"
            st.source = "body_continuity"
            st.identity_source = "body_continuity"

        if st.body_continuity_confidence <= 0 and st.student_id:
            st.body_continuity_confidence = min(1.0, float(st.face_confirmation_confidence or st.confidence or 0.5))

        self._finalize_with_body_signals(
            st,
            now,
            tracking_state=tracking_state,
            track_conf=track_conf,
            spatial_reassoc=spatial_reassoc,
            seconds_lost=seconds_lost,
            ambiguous_assoc=ambiguous_assoc,
            proximity_reasons=proximity_reasons,
            abrupt=abrupt,
            face_just_confirmed=False,
        )
        if face_seen_unidentified and st.identity_state == "body_continuity":
            # rosto visível sem id: mantém continuidade, recomenda reconfirmação
            st.reconfirmation_recommended = True

    def _finalize_with_body_signals(
        self,
        st: IdentityState,
        now: float,
        *,
        tracking_state: str,
        track_conf: float,
        spatial_reassoc: bool,
        seconds_lost: float,
        ambiguous_assoc: bool,
        proximity_reasons: List[str],
        abrupt: bool,
        face_just_confirmed: bool,
    ) -> None:
        if face_just_confirmed or st.identity_state == "face_confirmed":
            # face confirmada prevalece; limpa ambiguidade temporária
            st.ambiguity_reasons = []
            st.revalidation_required = False
            st.spatial_reassociation = False
            st.temporarily_lost_since = None
            return
        if not st.student_id:
            st.identity_state = "unknown"
            st.revalidation_required = True
            return

        reasons: List[str] = []
        bcc = float(st.body_continuity_confidence or 0.0)

        if tracking_state == "temporarily_lost":
            if st.temporarily_lost_since is None:
                st.temporarily_lost_since = now - max(0.0, seconds_lost)
                bcc = max(0.0, bcc - BODY_CONTINUITY_TEMP_LOST_PENALTY)
                reasons.append("temporarily_lost")
            lost_for = now - st.temporarily_lost_since
            if lost_for >= self.temporarily_lost_uncertain_seconds:
                reasons.append("temporarily_lost_prolonged")
                st.identity_state = "uncertain"
                st.revalidation_required = True
                st.source = "body_continuity"
                st.identity_source = "body_continuity"
                st.body_continuity_confidence = min(bcc, self.body_continuity_uncertain_threshold - 0.01)
                st.ambiguity_reasons = reasons
                return
        else:
            st.temporarily_lost_since = None

        if track_conf < 0.35:
            bcc = max(0.0, bcc - BODY_CONTINUITY_LOW_TRACK_PENALTY)
            reasons.append("low_tracking_confidence")

        if proximity_reasons:
            bcc = max(0.0, bcc - BODY_CONTINUITY_PROXIMITY_PENALTY)
            reasons.extend(proximity_reasons)

        # Associação facial ambígua (ex.: mão no rosto) NÃO derruba continuidade
        # se o corpo está estável e não há cruzamento / reclaim / troca pendente.
        solo_stable_body = (
            tracking_state == "active"
            and track_conf >= 0.35
            and not proximity_reasons
            and not spatial_reassoc
            and not st.pending_switch
            and not abrupt
        )
        if ambiguous_assoc:
            reasons.append("ambiguous_face_person_association")
            if solo_stable_body and bcc >= self.body_continuity_uncertain_threshold:
                # oclusão / face ruidosa: manter body_continuity
                pass
            else:
                bcc = min(bcc, BODY_CONTINUITY_AMBIGUOUS_CAP)
                st.identity_state = "uncertain"
                st.revalidation_required = True

        if st.pending_switch:
            bcc = min(bcc, BODY_CONTINUITY_PENDING_SWITCH_CAP)
            reasons.append("pending_identity_switch")
            st.identity_state = "uncertain"
            st.revalidation_required = True

        if abrupt:
            bcc = max(0.0, bcc - 0.20)
            reasons.append("abrupt_position_change")

        if spatial_reassoc:
            bcc = min(bcc, BODY_CONTINUITY_SPATIAL_REASSOC_CAP)
            reasons.append("spatial_reassociation")
            st.spatial_reassociation = True
            st.identity_state = "uncertain"
            st.revalidation_required = True
            st.identity_source = "spatial_reassociation"
            st.source = "spatial_reassociation"

        st.body_continuity_confidence = bcc
        st.ambiguity_reasons = reasons

        hard_ambiguous = ambiguous_assoc and not (
            solo_stable_body and bcc >= self.body_continuity_uncertain_threshold
        )
        force_uncertain = (
            st.identity_state == "uncertain"
            or hard_ambiguous
            or bool(st.pending_switch)
            or spatial_reassoc
            or ("person_overlap" in reasons and bcc < self.body_continuity_uncertain_threshold)
        )
        if bcc < self.body_continuity_uncertain_threshold and reasons and not solo_stable_body:
            force_uncertain = True
        # ambígua sozinha com corpo estável: nunca força uncertain
        if solo_stable_body and ambiguous_assoc and not proximity_reasons and not spatial_reassoc:
            force_uncertain = False
            st.identity_state = "body_continuity"
            st.revalidation_required = False

        if force_uncertain:
            st.identity_state = "uncertain"
            st.revalidation_required = True
            if st.source not in ("spatial_reassociation",):
                st.source = "body_continuity"
                st.identity_source = st.identity_source or "body_continuity"
        else:
            # corpo estável: permanece body_continuity mesmo com face stale / oclusão
            st.identity_state = "body_continuity"
            st.source = "body_continuity"
            st.identity_source = "body_continuity"
            st.revalidation_required = False

    def _apply_face_observation(
        self,
        person_track_id: str,
        st: IdentityState,
        cand: dict,
        assoc: Optional[FacePersonAssociation],
        now: float,
    ) -> None:
        sid = cand.get("student_id")
        conf = float(cand.get("confidence") or 0.0)
        margin = cand.get("margin", None)
        if margin is not None:
            try:
                margin = float(margin)
            except (TypeError, ValueError):
                margin = None
        top2 = cand.get("top2_score")
        if margin is None and top2 is not None and conf is not None:
            try:
                margin = float(conf) - float(top2)
            except (TypeError, ValueError):
                margin = None

        st.face_visible = True
        st.last_face_seen_at = now
        st.seconds_since_face_seen = 0.0
        st.face_track_id = assoc.face_track_id if assoc else None
        st.margin = margin

        if not sid:
            if st.student_id:
                st.source = "body_continuity"
                st.identity_source = "body_continuity"
                st.identity_state = "body_continuity"
            return

        if st.student_id == sid:
            st.confidence = max(st.confidence, conf)
            st.face_confirmation_confidence = max(float(st.face_confirmation_confidence or 0.0), conf)
            st.last_face_confirmation_at = now
            st.seconds_since_face_confirmation = 0.0
            st.source = "face_recognition"
            st.identity_source = "face_recognition"
            st.identity_state = "face_confirmed"
            if cand.get("full_name"):
                st.full_name = str(cand.get("full_name"))
            st.body_continuity_confidence = min(1.0, max(st.body_continuity_confidence, conf))
            st.pending_switch = None
            st.confirmation_count = 0
            st.revalidation_required = False
            st.face_confirmation_stale = False
            st.reconfirmation_recommended = False
            st.spatial_reassociation = False
            st.ambiguity_reasons = []
            self._student_to_track[sid] = person_track_id
            self._emit("identity_reconfirmed", person_track_id=person_track_id, student_id=sid, confidence=conf)
            return

        if not st.student_id:
            if self._can_assign_new(sid, conf, margin, assoc, now, person_track_id):
                self._commit_identity(
                    person_track_id,
                    st,
                    sid,
                    conf,
                    margin,
                    now,
                    reason="initial_bind",
                    full_name=cand.get("full_name"),
                )
            else:
                st.source = "unknown"
                st.identity_source = "unknown"
                st.identity_state = "unknown"
                st.revalidation_required = True
            return

        self._emit(
            "identity_swap_requested",
            person_track_id=person_track_id,
            from_student=st.student_id,
            to_student=sid,
            confidence=conf,
            margin=margin,
        )
        blocked = self._swap_block_reason(person_track_id, st, sid, conf, margin, assoc, now)
        if blocked:
            self._emit(
                "identity_swap_blocked",
                person_track_id=person_track_id,
                from_student=st.student_id,
                to_student=sid,
                reason=blocked,
            )
            st.pending_switch = None
            st.confirmation_count = 0
            # Face ruidosa / oclusão: manter continuidade — NÃO uncertain.
            # Uncertain só se o candidato for forte o bastante para disputa real
            # (bloqueio por cooldown/outro track ainda mantém id atual em continuity).
            weak_noise = blocked in (
                "low_confidence",
                "insufficient_margin",
                "margin_unavailable_needs_higher_confidence",
                "weak_sample_during_body_continuity",
                "ambiguous_face_person_association",
            )
            st.source = "body_continuity"
            st.identity_source = "body_continuity"
            st.identity_state = "body_continuity"
            st.revalidation_required = False
            if not weak_noise:
                st.ambiguity_reasons = list(st.ambiguity_reasons or []) + ["swap_blocked:" + blocked]
            else:
                st.ambiguity_reasons = list(st.ambiguity_reasons or []) + ["ignored_weak_face:" + blocked]
            return

        if st.pending_switch != sid:
            st.pending_switch = sid
            st.confirmation_count = 1
            st.identity_state = "uncertain"
            st.revalidation_required = True
            return
        st.confirmation_count += 1
        if st.confirmation_count < self.confirmations_before_switch:
            st.identity_state = "uncertain"
            st.revalidation_required = True
            return

        old = st.student_id
        self._commit_identity(
            person_track_id,
            st,
            sid,
            conf,
            margin,
            now,
            reason="swap",
            full_name=cand.get("full_name"),
        )
        self._emit(
            "identity_swap_committed",
            person_track_id=person_track_id,
            from_student=old,
            to_student=sid,
            confidence=conf,
        )

    def _can_assign_new(
        self,
        sid: str,
        conf: float,
        margin: Optional[float],
        assoc: Optional[FacePersonAssociation],
        now: float,
        person_track_id: str,
    ) -> bool:
        if assoc and assoc.ambiguous:
            return False
        if conf < self.minimum_new_identity_confidence:
            return False
        if margin is not None and margin < self.minimum_identity_margin:
            return False
        if margin is None and conf < self.minimum_new_identity_confidence + 0.05:
            return False
        other = self._student_to_track.get(sid)
        if other and other != person_track_id and other in self._states:
            other_st = self._states[other]
            if other_st.student_id == sid and other_st.identity_state != "unknown":
                return False
        return True

    def _swap_block_reason(
        self,
        person_track_id: str,
        st: IdentityState,
        sid: str,
        conf: float,
        margin: Optional[float],
        assoc: Optional[FacePersonAssociation],
        now: float,
    ) -> Optional[str]:
        if assoc and assoc.ambiguous:
            return "ambiguous_face_person_association"
        if conf < self.minimum_new_identity_confidence:
            return "low_confidence"
        if margin is not None and margin < self.minimum_identity_margin:
            return "insufficient_margin"
        if margin is None and conf < self.minimum_new_identity_confidence + 0.05:
            return "margin_unavailable_needs_higher_confidence"
        if st.cooldown_until and now < st.cooldown_until:
            return "cooldown_active"
        other = self._student_to_track.get(sid)
        if other and other != person_track_id and other in self._states:
            if self._states[other].student_id == sid:
                return "identity_bound_to_other_active_track"
        # amostra fraca só bloqueia swap durante body_continuity (sem face do titular)
        if (
            st.identity_state == "body_continuity"
            and st.body_continuity_confidence >= 0.45
            and conf < st.confidence + 0.08
        ):
            return "weak_sample_during_body_continuity"
        return None

    def _commit_identity(
        self,
        person_track_id: str,
        st: IdentityState,
        sid: str,
        conf: float,
        margin: Optional[float],
        now: float,
        reason: str,
        full_name: Optional[str] = None,
    ) -> None:
        prev = self._student_to_track.get(sid)
        if prev and prev != person_track_id and prev in self._states:
            pst = self._states[prev]
            if pst.student_id == sid:
                pst.student_id = None
                pst.source = "unknown"
                pst.identity_source = "unknown"
                pst.identity_state = "unknown"
                pst.confidence = 0.0
                pst.revalidation_required = True
                pst.full_name = None
        if st.student_id and st.student_id in self._student_to_track:
            if self._student_to_track[st.student_id] == person_track_id:
                self._student_to_track.pop(st.student_id, None)
        st.student_id = sid
        st.confidence = conf
        st.face_confirmation_confidence = conf
        st.body_continuity_confidence = min(1.0, conf)
        st.source = "face_recognition"
        st.identity_source = "face_recognition"
        st.identity_state = "face_confirmed"
        st.margin = margin
        if full_name:
            st.full_name = str(full_name)
        st.pending_switch = None
        st.confirmation_count = 0
        st.cooldown_until = now + self.identity_switch_cooldown_seconds
        st.last_face_confirmation_at = now
        st.seconds_since_face_confirmation = 0.0
        st.revalidation_required = False
        st.face_confirmation_stale = False
        st.reconfirmation_recommended = False
        st.spatial_reassociation = False
        st.ambiguity_reasons = []
        self._student_to_track[sid] = person_track_id
        self._emit(
            "identity_bound",
            person_track_id=person_track_id,
            student_id=sid,
            confidence=conf,
            reason=reason,
        )

    # --- API legada (testes multimodais) ---
    def bind(
        self,
        person_tracks: List[PersonTrack],
        face_tracks: List[FaceTrack],
        *,
        face_identities: Optional[Dict[str, Tuple[Optional[str], float]]] = None,
    ) -> List[IdentityBindingResult]:
        face_identities = face_identities or {}
        now = datetime.now(timezone.utc).timestamp()
        fi_dict = {
            fid: {"student_id": sid, "confidence": conf, "margin": None}
            for fid, (sid, conf) in face_identities.items()
        }
        states = self.update_continuity(
            now=now,
            person_tracks=person_tracks,
            face_tracks=face_tracks,
            face_identities=fi_dict,
        )
        results: List[IdentityBindingResult] = []
        for person in person_tracks:
            st = states.get(person.track_id) or IdentityState()
            assoc = st.association or {}
            hist_reasons = []
            for r in assoc.get("reasons") or []:
                if str(r).startswith("history="):
                    hist_reasons.append(f"temporal_pair_count={str(r).split('=', 1)[1]}")
            results.append(
                IdentityBindingResult(
                    person_track_id=person.track_id,
                    face_track_id=assoc.get("face_track_id") or st.face_track_id,
                    student_id=st.student_id,
                    identity_confidence=float(st.confidence or 0.0),
                    binding_confidence=float(assoc.get("score") or 0.0),
                    reasons=list(assoc.get("reasons") or [])
                    + ([f"source={st.source}"] if st.source else [])
                    + ([f"identity_state={st.identity_state}"] if st.identity_state else [])
                    + hist_reasons,
                )
            )
        return results
