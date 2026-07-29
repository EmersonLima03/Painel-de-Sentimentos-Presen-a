"""
Continuidade estável de person_track_id sobre o tracker bruto (ByteTrack/bbox).

Regra crítica (evidência manual pessoas:2):
enquanto um track estiver temporarily_lost na mesma região espacial,
NÃO criar person-002 — reassociar a detecção ao ID estável.

Não usa rosto nem identidade.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.logging import get_logger
from app.vision.tracking_types import BBox, PersonTrack

logger = get_logger(__name__)


def _iou(a: BBox, b: BBox) -> float:
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


def _center(b: BBox) -> Tuple[float, float]:
    return b[0] + b[2] / 2.0, b[1] + b[3] / 2.0


def _center_dist_ratio(a: BBox, b: BBox) -> float:
    acx, acy = _center(a)
    bcx, bcy = _center(b)
    diag = max(1.0, (a[2] ** 2 + a[3] ** 2) ** 0.5)
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5 / diag


def _size_compatible(a: BBox, b: BBox, tol: float = 0.65) -> bool:
    if a[2] <= 1 or a[3] <= 1 or b[2] <= 1 or b[3] <= 1:
        return False
    wr = min(a[2], b[2]) / max(a[2], b[2])
    hr = min(a[3], b[3]) / max(a[3], b[3])
    return wr >= (1.0 - tol) and hr >= (1.0 - tol)


@dataclass
class _StableState:
    track_id: str
    camera_id: str
    first_seen_at: datetime
    last_bbox: BBox
    last_detection_ts: float
    last_update_ts: float
    tracking_confidence: float = 0.5
    tracking_state: str = "active"
    missed_detections: int = 0
    reassociation_score: Optional[float] = None
    raw_tracker_id: Optional[str] = None
    expire_reason: Optional[str] = None
    lost_since: Optional[float] = None
    # Detecção fraca / nunca confirmada → TTL curto (anti-fantasma YOLO)
    ever_strong: bool = False


class StablePersonTrackManager:
    """Mapeia tracks brutos → person_track_id estável."""

    def __init__(
        self,
        camera_id: str,
        *,
        max_time_lost_seconds: float = 8.0,
        minimum_reassociation_iou: float = 0.30,
        maximum_center_distance_ratio: float = 0.35,
        weak_max_time_lost_seconds: float = 2.0,
        strong_confidence_threshold: float = 0.45,
    ):
        self.camera_id = camera_id
        self.max_time_lost_seconds = float(max_time_lost_seconds)
        self.weak_max_time_lost_seconds = float(weak_max_time_lost_seconds)
        self.strong_confidence_threshold = float(strong_confidence_threshold)
        self.minimum_reassociation_iou = float(minimum_reassociation_iou)
        self.maximum_center_distance_ratio = float(maximum_center_distance_ratio)
        # reclaim mais permissivo (oclusão / bbox oscila)
        self._loose_iou = min(0.12, self.minimum_reassociation_iou)
        self._loose_dist = max(0.70, self.maximum_center_distance_ratio * 2.0)
        self._force_dist = 0.85
        self._next_id = 1
        self._states: Dict[str, _StableState] = {}
        self._events: List[dict] = []
        self.last_debug: Dict[str, Any] = {}

    def drain_events(self) -> List[dict]:
        out = list(self._events)
        self._events.clear()
        return out

    def _emit(self, event_type: str, **payload) -> None:
        ev = {"event_type": event_type, "camera_id": self.camera_id, **payload}
        self._events.append(ev)
        logger.info(event_type, **{k: v for k, v in payload.items() if k != "bbox"})

    def _new_id(self) -> str:
        tid = f"{self.camera_id}-person-{self._next_id:03d}"
        self._next_id += 1
        return tid

    def _score(self, prev: BBox, cur: BBox) -> Tuple[float, Dict[str, float]]:
        iou = _iou(prev, cur)
        dist = _center_dist_ratio(prev, cur)
        size_ok = _size_compatible(prev, cur)
        score = 0.50 * iou + 0.40 * max(0.0, 1.0 - dist / max(1e-6, self._loose_dist))
        if size_ok:
            score += 0.10
        else:
            score -= 0.08
        return score, {"iou": iou, "center_dist_ratio": dist, "size_ok": 1.0 if size_ok else 0.0}

    def _ok_strict(self, metrics: Dict[str, float], score: float) -> bool:
        return (
            metrics["iou"] >= self.minimum_reassociation_iou
            or (
                metrics["center_dist_ratio"] <= self.maximum_center_distance_ratio
                and metrics["size_ok"] >= 1.0
                and score >= 0.35
            )
        )

    def _ok_loose(self, metrics: Dict[str, float], score: float) -> bool:
        """Reclaim de track lost / oclusão — evita person-002 paralelo."""
        return (
            metrics["iou"] >= self._loose_iou
            or metrics["center_dist_ratio"] <= self._loose_dist
            or score >= 0.22
        )

    def update(self, raw_tracks: List[PersonTrack], now: Optional[float] = None) -> List[PersonTrack]:
        now = now if now is not None else time.time()
        dt_now = datetime.now(timezone.utc)
        used_stable: set = set()
        used_raw: set = set()
        assignments: Dict[str, Tuple[int, float, Dict[str, float], str]] = {}

        # --- pass 1: match estrito ---
        strict_pairs: List[Tuple[float, str, int, Dict[str, float]]] = []
        for sid, st in self._states.items():
            for i, raw in enumerate(raw_tracks):
                score, metrics = self._score(st.last_bbox, raw.bounding_box)
                if self._ok_strict(metrics, score):
                    strict_pairs.append((score, sid, i, metrics))
        strict_pairs.sort(key=lambda x: x[0], reverse=True)
        for score, sid, i, metrics in strict_pairs:
            if sid in used_stable or i in used_raw:
                continue
            used_stable.add(sid)
            used_raw.add(i)
            assignments[sid] = (i, score, metrics, "strict")

        # --- pass 2: reclaim frouxo para stables ainda sem match ---
        loose_pairs: List[Tuple[float, str, int, Dict[str, float]]] = []
        for sid, st in self._states.items():
            if sid in used_stable:
                continue
            for i, raw in enumerate(raw_tracks):
                if i in used_raw:
                    continue
                score, metrics = self._score(st.last_bbox, raw.bounding_box)
                if self._ok_loose(metrics, score):
                    # preferir reclaim de lost
                    bonus = 0.05 if st.tracking_state == "temporarily_lost" or st.lost_since else 0.0
                    loose_pairs.append((score + bonus, sid, i, metrics))
        loose_pairs.sort(key=lambda x: x[0], reverse=True)
        for score, sid, i, metrics in loose_pairs:
            if sid in used_stable or i in used_raw:
                continue
            used_stable.add(sid)
            used_raw.add(i)
            assignments[sid] = (i, score, metrics, "loose")

        # --- pass 3: força 1 lost + 1 raw na mesma região (anti ghost 001+002) ---
        unmatched_raw = [i for i in range(len(raw_tracks)) if i not in used_raw]
        unmatched_stable = [sid for sid in self._states if sid not in used_stable]
        if unmatched_raw and unmatched_stable:
            # Se há exatamente um stable pending e um raw, forçar se distância razoável
            if len(unmatched_stable) == 1 and len(unmatched_raw) == 1:
                sid = unmatched_stable[0]
                i = unmatched_raw[0]
                score, metrics = self._score(self._states[sid].last_bbox, raw_tracks[i].bounding_box)
                if metrics["center_dist_ratio"] <= self._force_dist or metrics["iou"] >= 0.05:
                    used_stable.add(sid)
                    used_raw.add(i)
                    assignments[sid] = (i, score, metrics, "forced_single")
                    unmatched_raw = []
                    unmatched_stable = []
            else:
                # vários: cada raw pega o melhor stable unmatched ainda livre (se perto)
                for i in list(unmatched_raw):
                    best = None
                    for sid in unmatched_stable:
                        if sid in used_stable:
                            continue
                        score, metrics = self._score(self._states[sid].last_bbox, raw_tracks[i].bounding_box)
                        if metrics["center_dist_ratio"] <= self._force_dist or metrics["iou"] >= 0.08:
                            if best is None or score > best[0]:
                                best = (score, sid, metrics)
                    if best is not None:
                        score, sid, metrics = best
                        used_stable.add(sid)
                        used_raw.add(i)
                        assignments[sid] = (i, score, metrics, "forced_nearest")
                unmatched_raw = [i for i in range(len(raw_tracks)) if i not in used_raw]
                unmatched_stable = [sid for sid in self._states if sid not in used_stable]

        out: List[PersonTrack] = []

        # aplicar assignments
        for sid, (i, score, metrics, how) in assignments.items():
            raw = raw_tracks[i]
            st = self._states[sid]
            was_lost = st.tracking_state == "temporarily_lost" or st.lost_since is not None
            prev_state = st.tracking_state
            st.last_bbox = raw.bounding_box
            st.last_detection_ts = now
            st.last_update_ts = now
            st.tracking_confidence = float(raw.tracking_confidence or st.tracking_confidence)
            if st.tracking_confidence >= self.strong_confidence_threshold:
                st.ever_strong = True
            st.missed_detections = 0
            st.lost_since = None
            st.expire_reason = None
            st.raw_tracker_id = raw.track_id
            st.reassociation_score = score
            if was_lost or how.startswith("forced") or how == "loose":
                st.tracking_state = "reassociated"
                self._emit(
                    "track_reassociated",
                    person_track_id=sid,
                    raw_tracker_id=raw.track_id,
                    score=round(score, 3),
                    iou=round(metrics["iou"], 3),
                    center_dist_ratio=round(metrics["center_dist_ratio"], 3),
                    previous_state=prev_state,
                    method=how,
                )
            else:
                st.tracking_state = "active"
            out.append(self._to_track(st, now, dt_now, visible=True))

        # só cria ID novo se NÃO houver stable reclaimável próximo
        for i, raw in enumerate(raw_tracks):
            if i in used_raw:
                continue
            # última salvaguarda: se ainda existe qualquer temporarily_lost / unmatched stable perto, não criar
            blocked = False
            for sid, st in self._states.items():
                if sid in used_stable:
                    continue
                score, metrics = self._score(st.last_bbox, raw.bounding_box)
                if metrics["center_dist_ratio"] <= self._force_dist or metrics["iou"] >= 0.05:
                    # reclaim forçado residual
                    used_stable.add(sid)
                    used_raw.add(i)
                    was_lost = True
                    prev_state = st.tracking_state
                    st.last_bbox = raw.bounding_box
                    st.last_detection_ts = now
                    st.last_update_ts = now
                    st.tracking_confidence = float(raw.tracking_confidence or st.tracking_confidence)
                    st.missed_detections = 0
                    st.lost_since = None
                    st.raw_tracker_id = raw.track_id
                    st.reassociation_score = score
                    st.tracking_state = "reassociated"
                    self._emit(
                        "track_reassociated",
                        person_track_id=sid,
                        raw_tracker_id=raw.track_id,
                        score=round(score, 3),
                        method="forced_block_new",
                        previous_state=prev_state,
                    )
                    out.append(self._to_track(st, now, dt_now, visible=True))
                    blocked = True
                    break
            if blocked:
                continue

            sid = self._new_id()
            conf0 = float(raw.tracking_confidence or 0.5)
            st = _StableState(
                track_id=sid,
                camera_id=self.camera_id,
                first_seen_at=dt_now,
                last_bbox=raw.bounding_box,
                last_detection_ts=now,
                last_update_ts=now,
                tracking_confidence=conf0,
                tracking_state="active",
                raw_tracker_id=raw.track_id,
                ever_strong=conf0 >= self.strong_confidence_threshold,
            )
            self._states[sid] = st
            used_stable.add(sid)
            self._emit("track_created", person_track_id=sid, raw_tracker_id=raw.track_id)
            out.append(self._to_track(st, now, dt_now, visible=True))

        # unmatched stables → lost / expire
        for sid, st in list(self._states.items()):
            if sid in used_stable:
                continue
            gap = now - st.last_detection_ts
            st.missed_detections += 1
            st.last_update_ts = now
            # Fantasmas YOLO fracos: TTL curto; tracks fortes: TTL completo
            ttl = (
                self.max_time_lost_seconds
                if st.ever_strong
                else min(self.weak_max_time_lost_seconds, self.max_time_lost_seconds)
            )
            if gap > ttl:
                st.tracking_state = "expired"
                st.expire_reason = (
                    "max_time_lost_exceeded" if st.ever_strong else "weak_track_expired"
                )
                self._emit(
                    "track_expired",
                    person_track_id=sid,
                    seconds_since_person_detection=round(gap, 2),
                    missed_detections=st.missed_detections,
                    reason=st.expire_reason,
                    last_person_bbox=list(st.last_bbox),
                )
                self._states.pop(sid, None)
                continue
            if st.lost_since is None:
                st.lost_since = now
                self._emit(
                    "track_lost",
                    person_track_id=sid,
                    seconds_since_person_detection=round(gap, 2),
                    last_person_bbox=list(st.last_bbox),
                )
            st.tracking_state = "temporarily_lost"
            st.reassociation_score = None
            out.append(self._to_track(st, now, dt_now, visible=False))

        self.last_debug = {
            "stable_tracks": len(self._states),
            "emitted_tracks": len(out),
            "raw_tracks": len(raw_tracks),
            "max_time_lost_seconds": self.max_time_lost_seconds,
            "weak_max_time_lost_seconds": self.weak_max_time_lost_seconds,
            "minimum_reassociation_iou": self.minimum_reassociation_iou,
            "maximum_center_distance_ratio": self.maximum_center_distance_ratio,
            "loose_dist": self._loose_dist,
            "force_dist": self._force_dist,
            "tracks": [
                {
                    "person_track_id": t.track_id,
                    "tracking_state": t.tracking_state,
                    "seconds_since_person_detection": t.seconds_since_person_detection,
                    "missed_detections": t.missed_detections,
                    "reassociation_score": t.reassociation_score,
                    "raw_tracker_id": t.raw_tracker_id,
                    "bbox": list(t.bounding_box),
                }
                for t in out
            ],
        }
        return out

    def _to_track(self, st: _StableState, now: float, dt_now: datetime, *, visible: bool) -> PersonTrack:
        gap = max(0.0, now - st.last_detection_ts)
        return PersonTrack(
            track_id=st.track_id,
            camera_id=st.camera_id,
            first_seen_at=st.first_seen_at,
            last_seen_at=dt_now,
            bounding_box=st.last_bbox,
            tracking_confidence=st.tracking_confidence,
            visible=visible,
            observation_quality=min(1.0, st.tracking_confidence) if visible else 0.4,
            tracking_state=st.tracking_state,
            seconds_since_person_detection=gap,
            last_person_bbox=st.last_bbox,
            reassociation_score=st.reassociation_score,
            raw_tracker_id=st.raw_tracker_id,
            missed_detections=st.missed_detections,
            expire_reason=st.expire_reason,
        )
