"""
IdentityBinding — continuidade por person_track_id com TTL.

Nunca escreve attendance. Nunca inventa margem artificial.
Associação face↔pessoa vem de FacePersonAssociator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.logging import get_logger
from app.vision.face_person_association import FacePersonAssociator, FacePersonAssociation
from app.vision.tracking_types import FaceTrack, IdentityBindingResult, PersonTrack

logger = get_logger(__name__)


@dataclass
class IdentityState:
    student_id: Optional[str] = None
    confidence: float = 0.0
    source: str = "unknown"  # face_recognition | cached_binding | unknown
    face_visible: bool = False
    last_face_seen_at: Optional[float] = None
    seconds_since_face_seen: float = 0.0
    margin: Optional[float] = None  # null = unavailable
    pending_switch: Optional[str] = None
    confirmation_count: int = 0
    cooldown_until: Optional[float] = None
    face_track_id: Optional[str] = None
    association: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "student_id": self.student_id,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "source": self.source,
            "face_visible": self.face_visible,
            "last_face_seen_at": self.last_face_seen_at,
            "seconds_since_face_seen": round(self.seconds_since_face_seen, 2),
            "margin": None if self.margin is None else round(self.margin, 3),
            "pending_switch": self.pending_switch,
            "confirmation_count": self.confirmation_count,
            "cooldown_until": self.cooldown_until,
        }


class IdentityBindingEngine:
    """
    Liga person_track ↔ face_track ↔ student_id com TTL e swap gating.
    Mantém API bind() legada + update_continuity() person-first.
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
    ):
        self.history_bonus = history_bonus
        self.face_missing_ttl_seconds = face_missing_ttl_seconds
        self.minimum_new_identity_confidence = minimum_new_identity_confidence
        self.minimum_identity_margin = minimum_identity_margin
        self.confirmations_before_switch = confirmations_before_switch
        self.identity_switch_cooldown_seconds = identity_switch_cooldown_seconds
        self.confidence_decay_per_second = confidence_decay_per_second
        self._associator = FacePersonAssociator(history_bonus=history_bonus)
        self._states: Dict[str, IdentityState] = {}
        self._student_to_track: Dict[str, str] = {}
        self._events: List[dict] = []

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
    ) -> Dict[str, IdentityState]:
        """
        face_identities[face_track_id] = {
          student_id, confidence, margin (Optional), top2_score (Optional)
        }
        margin só é usada se fornecida explicitamente (nunca inventada).
        """
        face_identities = face_identities or {}
        associations = self._associator.associate(person_tracks, face_tracks)
        assoc_by_person = {
            a.person_track_id: a for a in associations if a.person_track_id
        }
        active_pids = {p.track_id for p in person_tracks}

        # expire dead tracks
        for pid in list(self._states.keys()):
            if pid not in active_pids:
                self.expire_track(pid)

        out: Dict[str, IdentityState] = {}
        for person in person_tracks:
            st = self.get_state(person.track_id)
            assoc = assoc_by_person.get(person.track_id)
            st.association = assoc.as_dict() if assoc else None

            face_id = assoc.face_track_id if assoc and not assoc.ambiguous else None
            if assoc and assoc.ambiguous:
                # associação ambígua: não troca identidade; face pode estar visível espacialmente
                st.face_visible = bool(assoc.face_track_id)
                if st.student_id and st.last_face_seen_at is not None:
                    st.seconds_since_face_seen = max(0.0, now - st.last_face_seen_at)
                    self._apply_ttl_decay(st, now, person.track_id)
                out[person.track_id] = st
                continue

            if face_id and face_id in face_identities:
                cand = face_identities[face_id]
                self._apply_face_observation(person.track_id, st, cand, assoc, now)
            elif face_id:
                # face associada mas sem identidade
                st.face_visible = True
                st.face_track_id = face_id
                st.last_face_seen_at = now
                st.seconds_since_face_seen = 0.0
                if st.student_id:
                    st.source = "cached_binding"
                else:
                    st.source = "unknown"
            else:
                st.face_visible = False
                st.face_track_id = None
                if st.last_face_seen_at is not None:
                    st.seconds_since_face_seen = max(0.0, now - st.last_face_seen_at)
                else:
                    st.seconds_since_face_seen = 999.0
                self._apply_ttl_decay(st, now, person.track_id)

            out[person.track_id] = st
        return out

    def _apply_ttl_decay(self, st: IdentityState, now: float, person_track_id: str) -> None:
        if not st.student_id:
            st.source = "unknown"
            st.confidence = 0.0
            return
        gap = st.seconds_since_face_seen
        if gap > self.face_missing_ttl_seconds:
            old = st.student_id
            if old and self._student_to_track.get(old) == person_track_id:
                self._student_to_track.pop(old, None)
            st.student_id = None
            st.confidence = 0.0
            st.source = "unknown"
            st.margin = None
            st.pending_switch = None
            st.confirmation_count = 0
            self._emit(
                "identity_binding_expired",
                person_track_id=person_track_id,
                student_id=old,
                reason="ttl_exceeded",
                gap=gap,
            )
            return
        st.source = "cached_binding"
        decay = self.confidence_decay_per_second * gap
        st.confidence = max(0.0, float(st.confidence) - decay)

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
        # margem real somente se fornecida
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
        st.margin = margin  # pode ser None = unavailable

        if not sid:
            if st.student_id:
                st.source = "cached_binding"
            return

        # mesma identidade → reconfirma
        if st.student_id == sid:
            st.confidence = max(st.confidence, conf)
            st.source = "face_recognition"
            st.pending_switch = None
            st.confirmation_count = 0
            self._student_to_track[sid] = person_track_id
            self._emit("identity_reconfirmed", person_track_id=person_track_id, student_id=sid, confidence=conf)
            return

        # sem identidade atual → bind se passar gates
        if not st.student_id:
            if self._can_assign_new(sid, conf, margin, assoc, now, person_track_id):
                self._commit_identity(person_track_id, st, sid, conf, margin, now, reason="initial_bind")
            else:
                st.source = "unknown"
            return

        # pedido de swap
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
            st.source = "face_recognition" if st.face_visible else "cached_binding"
            return

        if st.pending_switch != sid:
            st.pending_switch = sid
            st.confirmation_count = 1
            return
        st.confirmation_count += 1
        if st.confirmation_count < self.confirmations_before_switch:
            return

        old = st.student_id
        self._commit_identity(person_track_id, st, sid, conf, margin, now, reason="swap")
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
        # margem unavailable → exige confiança mais alta
        if margin is None and conf < self.minimum_new_identity_confidence + 0.05:
            return False
        other = self._student_to_track.get(sid)
        if other and other != person_track_id and other in self._states:
            other_st = self._states[other]
            if other_st.student_id == sid and other_st.source != "unknown":
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
        # amostra fraca durante TTL: bloquear se cached ainda forte
        if st.source == "cached_binding" and st.confidence >= 0.45 and conf < st.confidence + 0.08:
            return "weak_sample_during_ttl"
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
    ) -> None:
        # liberar vínculo anterior deste student
        prev = self._student_to_track.get(sid)
        if prev and prev != person_track_id and prev in self._states:
            pst = self._states[prev]
            if pst.student_id == sid:
                pst.student_id = None
                pst.source = "unknown"
                pst.confidence = 0.0
        if st.student_id and st.student_id in self._student_to_track:
            if self._student_to_track[st.student_id] == person_track_id:
                self._student_to_track.pop(st.student_id, None)
        st.student_id = sid
        st.confidence = conf
        st.source = "face_recognition"
        st.margin = margin
        st.pending_switch = None
        st.confirmation_count = 0
        st.cooldown_until = now + self.identity_switch_cooldown_seconds
        self._student_to_track[sid] = person_track_id

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
                    + hist_reasons,
                )
            )
        return results
