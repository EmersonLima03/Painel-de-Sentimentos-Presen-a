"""
Agregador temporal — impede que um único frame gere alertas definitivos.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from app.vision.behavioral_taxonomy import ObservableSignal, label_pt
from app.vision.facial_signals import FacialSignalSample


@dataclass
class TrackSignalState:
    track_id: str
    samples: Deque[Tuple[float, FacialSignalSample]] = field(default_factory=lambda: deque(maxlen=120))
    last_seen: float = 0.0
    out_of_field_since: Optional[float] = None


@dataclass
class BehavioralEventDraft:
    event_type: str
    anonymous_track_id: str
    started_at: float
    ended_at: float
    duration_seconds: float
    confidence: float
    observation_quality: str
    label_pt: str
    metadata: dict


class TemporalSignalAggregator:
    """
    Agrega amostras por track anônimo.

    Regras (defaults do plano):
    - eyes closed persistente >= drowsiness_eyes_seconds
    - possível sonolência: olhos fechados + (pitch alto ou yawn) por >= drowsiness_combo_seconds
    - fora de campo >= out_of_field_seconds
    - cabeça baixa curta NÃO vira sonolência
    """

    def __init__(
        self,
        *,
        out_of_field_seconds: float = 45.0,
        eyes_closed_seconds: float = 45.0,
        drowsiness_combo_seconds: float = 60.0,
        min_confidence: float = 0.55,
        track_ttl_seconds: float = 8.0,
    ):
        self.out_of_field_seconds = out_of_field_seconds
        self.eyes_closed_seconds = eyes_closed_seconds
        self.drowsiness_combo_seconds = drowsiness_combo_seconds
        self.min_confidence = min_confidence
        self.track_ttl_seconds = track_ttl_seconds
        self._tracks: Dict[str, TrackSignalState] = {}
        self._emitted: Dict[str, float] = {}  # key -> last emit ts (cooldown)

    def update_track(self, track_id: str, sample: Optional[FacialSignalSample], now: Optional[float] = None) -> None:
        now = now or time.time()
        st = self._tracks.get(track_id)
        if st is None:
            st = TrackSignalState(track_id=track_id)
            self._tracks[track_id] = st
        st.last_seen = now
        if sample is None:
            if st.out_of_field_since is None:
                st.out_of_field_since = now
            return
        st.out_of_field_since = None
        st.samples.append((now, sample))

    def mark_missing_tracks(self, active_ids: List[str], now: Optional[float] = None) -> None:
        now = now or time.time()
        active = set(active_ids)
        for tid, st in list(self._tracks.items()):
            if tid not in active:
                if st.out_of_field_since is None:
                    st.out_of_field_since = now
            if now - st.last_seen > self.track_ttl_seconds * 4:
                # limpa tracks antigos
                del self._tracks[tid]

    def poll_events(self, now: Optional[float] = None) -> List[BehavioralEventDraft]:
        now = now or time.time()
        events: List[BehavioralEventDraft] = []
        for tid, st in self._tracks.items():
            events.extend(self._eval_track(tid, st, now))
        return events

    def _cooldown_ok(self, key: str, now: float, cooldown: float = 90.0) -> bool:
        last = self._emitted.get(key, 0.0)
        if now - last < cooldown:
            return False
        self._emitted[key] = now
        return True

    def _eval_track(self, tid: str, st: TrackSignalState, now: float) -> List[BehavioralEventDraft]:
        out: List[BehavioralEventDraft] = []

        # Fora do campo
        if st.out_of_field_since is not None:
            dur = now - st.out_of_field_since
            if dur >= self.out_of_field_seconds:
                key = f"{tid}:out_of_field"
                if self._cooldown_ok(key, now):
                    out.append(
                        BehavioralEventDraft(
                            event_type=ObservableSignal.OUT_OF_FIELD.value,
                            anonymous_track_id=tid,
                            started_at=st.out_of_field_since,
                            ended_at=now,
                            duration_seconds=dur,
                            confidence=0.7,
                            observation_quality="fair",
                            label_pt=label_pt(ObservableSignal.OUT_OF_FIELD.value),
                            metadata={"reason": "track_missing"},
                        )
                    )

        if len(st.samples) < 3:
            return out

        # Janela recente
        window = [(t, s) for t, s in st.samples if now - t <= max(self.drowsiness_combo_seconds, 90)]
        if not window:
            return out

        closed = [(t, s) for t, s in window if s.eyes_closed and s.confidence >= self.min_confidence]
        if closed:
            t0, t1 = closed[0][0], closed[-1][0]
            dur = t1 - t0
            if dur >= self.eyes_closed_seconds:
                yawns = sum(1 for _, s in window if s.possible_yawn)
                pitch_high = sum(1 for _, s in window if s.pitch > 0.4) / max(1, len(window))
                combo = yawns >= 1 or pitch_high >= 0.4
                if combo and dur >= self.drowsiness_combo_seconds:
                    et = ObservableSignal.POSSIBLE_DROWSINESS.value
                else:
                    et = ObservableSignal.EYES_CLOSED_PERSISTENT.value
                key = f"{tid}:{et}"
                if self._cooldown_ok(key, now):
                    conf = float(np_mean([s.confidence for _, s in closed]))
                    out.append(
                        BehavioralEventDraft(
                            event_type=et,
                            anonymous_track_id=tid,
                            started_at=t0,
                            ended_at=t1,
                            duration_seconds=dur,
                            confidence=conf,
                            observation_quality=closed[-1][1].observation_quality,
                            label_pt=label_pt(et),
                            metadata={
                                "yawns_in_window": yawns,
                                "pitch_high_ratio": round(pitch_high, 2),
                                "requires_human_review": et == ObservableSignal.POSSIBLE_DROWSINESS.value,
                            },
                        )
                    )

        # Baixa qualidade persistente
        poor = [(t, s) for t, s in window if s.observation_quality == "poor"]
        if len(poor) >= 5 and (poor[-1][0] - poor[0][0]) >= 20:
            key = f"{tid}:low_quality"
            if self._cooldown_ok(key, now, cooldown=120.0):
                out.append(
                    BehavioralEventDraft(
                        event_type=ObservableSignal.LOW_OBSERVATION_QUALITY.value,
                        anonymous_track_id=tid,
                        started_at=poor[0][0],
                        ended_at=poor[-1][0],
                        duration_seconds=poor[-1][0] - poor[0][0],
                        confidence=0.5,
                        observation_quality="poor",
                        label_pt=label_pt(ObservableSignal.LOW_OBSERVATION_QUALITY.value),
                        metadata={},
                    )
                )
        return out


def np_mean(vals: List[float]) -> float:
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))
