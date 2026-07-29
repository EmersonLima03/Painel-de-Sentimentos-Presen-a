"""Agregação pedagógica de sessão — merge identidade, episódios e KPIs unificados."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.labels_pt import (
    CONCLUSIVE_ATTENTION,
    CONCLUSIVE_EXPRESSION,
    EVENT_MERGE_GAP_SECONDS,
    INCONCLUSIVE_THRESHOLD,
    LOW_OBSERVABILITY_NOTE,
    MIN_PRESENCE_EXCLUDE_SECONDS,
    SIGNAL_FAMILIES,
    attention_label_pt,
    attention_level_from_index,
    category_totals_from_signals,
    climate_label_pt,
    empty_category_totals,
    expression_label_pt,
    signal_disclaimer_pt,
    signal_label_pt,
)


@dataclass
class SignalRollup:
    signal_key: str
    total_seconds: float = 0.0
    occurrence_count: int = 0
    last_ended_at: float = 0.0
    # duração já contabilizada por event_id (evita somar updated + closed)
    _episode_seconds: Dict[str, float] = field(default_factory=dict)
    # eid -> (started_at, ended_at) para merge pedagógico de ocorrências
    _episode_spans: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    def apply_episode(
        self,
        event_id: str,
        duration: float,
        *,
        ended_at: float,
        closed: bool,
        started_at: Optional[float] = None,
    ) -> None:
        eid = event_id or f"anon:{self.signal_key}:{ended_at}"
        prev = float(self._episode_seconds.get(eid, 0.0))
        dur = max(0.0, float(duration))
        self.total_seconds = max(0.0, self.total_seconds - prev + dur)
        if prev <= 0 and dur > 0:
            self.occurrence_count += 1
        self._episode_seconds[eid] = dur
        end = float(ended_at)
        start = float(started_at) if started_at is not None else max(0.0, end - dur)
        if start > end:
            start = max(0.0, end - dur)
        self._episode_spans[eid] = (start, end)
        self.last_ended_at = max(self.last_ended_at, end)
        if closed and event_id:
            # mantém valor final; id fica marcado via processed no aggregator
            pass

    def to_dict(self) -> dict:
        return {
            "signal_key": self.signal_key,
            "label_pt": signal_label_pt(self.signal_key),
            "total_seconds": round(self.total_seconds, 1),
            "occurrence_count": self.occurrence_count,
            "disclaimer_pt": signal_disclaimer_pt(self.signal_key),
        }


@dataclass
class PersonRecord:
    person_key: str
    student_id: Optional[str] = None
    full_name: str = "Pessoa não identificada"
    track_ids: set = field(default_factory=set)
    presence_seconds: float = 0.0
    last_seen_at: float = 0.0
    attention_seconds: Counter = field(default_factory=Counter)
    expression_seconds: Counter = field(default_factory=Counter)
    observable_seconds: float = 0.0
    inconclusive_seconds: float = 0.0
    signals: Dict[str, SignalRollup] = field(default_factory=dict)
    last_attention: str = "inconclusive"
    last_expression: str = "inconclusive"
    last_expression_pt: Optional[str] = None

    def observable_pct(self) -> float:
        if self.presence_seconds <= 0:
            return 0.0
        return round(100.0 * self.observable_seconds / self.presence_seconds, 1)

    def _insufficient_data(self) -> bool:
        if self.presence_seconds <= 0:
            return True
        return (self.inconclusive_seconds / self.presence_seconds) > INCONCLUSIVE_THRESHOLD

    def _dominant_from_counter(
        self,
        counter: Counter,
        conclusive: frozenset,
    ) -> Tuple[str, bool]:
        insufficient = self._insufficient_data()
        if insufficient:
            return "inconclusive", True
        conclusive_totals = {k: float(v) for k, v in counter.items() if k in conclusive}
        if not conclusive_totals:
            return "inconclusive", False
        dominant = max(conclusive_totals, key=conclusive_totals.get)
        return dominant, False

    def to_report_dict(self) -> dict:
        dom_attn, attn_insuf = self._dominant_from_counter(self.attention_seconds, CONCLUSIVE_ATTENTION)
        dom_expr, expr_insuf = self._dominant_from_counter(self.expression_seconds, CONCLUSIVE_EXPRESSION)
        obs_pct = self.observable_pct()
        note = LOW_OBSERVABILITY_NOTE if obs_pct == 0 and self.student_id else None
        signals_sorted = sorted(
            self.signals.values(),
            key=lambda s: s.total_seconds,
            reverse=True,
        )
        signal_dicts = [s.to_dict() for s in signals_sorted if s.total_seconds > 0]
        # Sempre lista as 5 categorias cobertas (mesmo com 0s) para o professor ver o escopo
        categories = category_totals_from_signals(signal_dicts, include_zero=True)

        def _sec(counter: Counter, *keys: str) -> float:
            return round(sum(float(counter.get(k, 0) or 0) for k in keys), 1)

        observation_profile = {
            "presence_seconds": round(self.presence_seconds, 1),
            "observable_seconds": round(self.observable_seconds, 1),
            "inconclusive_seconds": round(self.inconclusive_seconds, 1),
            "attention_high_seconds": _sec(self.attention_seconds, "high"),
            "attention_moderate_seconds": _sec(self.attention_seconds, "moderate"),
            "attention_low_seconds": _sec(self.attention_seconds, "low"),
            "expression_positive_seconds": _sec(
                self.expression_seconds, "predominantly_positive", "positive"
            ),
            "expression_neutral_seconds": _sec(
                self.expression_seconds, "predominantly_neutral", "neutral"
            ),
            "expression_negative_seconds": _sec(
                self.expression_seconds, "predominantly_negative", "negative"
            ),
            "expression_mixed_seconds": _sec(self.expression_seconds, "mixed", "surprise"),
        }
        return {
            "person_key": self.person_key,
            "student_id": self.student_id,
            "full_name": self.full_name,
            "track_ids": sorted(self.track_ids),
            "presence_seconds": round(self.presence_seconds, 1),
            "observable_pct": obs_pct,
            "observability_note_pt": note,
            "attention_level": dom_attn,
            "attention_label_pt": attention_label_pt(dom_attn, insufficient=attn_insuf),
            "expression_level": dom_expr,
            "expression_label_pt": expression_label_pt(dom_expr, insufficient=expr_insuf),
            "insufficient_data": attn_insuf or expr_insuf,
            "last_expression_pt": self.last_expression_pt,
            "time_by_category": categories,
            "observation_profile": observation_profile,
            "signals": signal_dicts,
            "present": True,
        }


@dataclass
class SessionAggregator:
    started_at: float = field(default_factory=time.time)
    persons: Dict[str, PersonRecord] = field(default_factory=dict)
    track_to_person: Dict[str, str] = field(default_factory=dict)
    processed_event_ids: set = field(default_factory=set)
    peak_visible: int = 0
    last_ingest_at: float = 0.0

    def reset(self, started_at: Optional[float] = None) -> None:
        self.started_at = started_at or time.time()
        self.persons.clear()
        self.track_to_person.clear()
        self.processed_event_ids.clear()
        self.peak_visible = 0
        self.last_ingest_at = 0.0

    def _resolve_person_key(
        self,
        *,
        student_id: Optional[str],
        track_id: Optional[str],
    ) -> str:
        if student_id:
            return f"student:{student_id}"
        tid = str(track_id or "unknown")
        if tid in self.track_to_person:
            return self.track_to_person[tid]
        return f"track:{tid}"

    def _get_or_create(
        self,
        person_key: str,
        *,
        student_id: Optional[str] = None,
        full_name: Optional[str] = None,
        track_id: Optional[str] = None,
    ) -> PersonRecord:
        if person_key not in self.persons:
            self.persons[person_key] = PersonRecord(
                person_key=person_key,
                student_id=student_id,
                full_name=full_name or "Pessoa não identificada",
            )
        rec = self.persons[person_key]
        if student_id:
            rec.student_id = student_id
        if full_name:
            rec.full_name = full_name
        if track_id:
            rec.track_ids.add(str(track_id))
            self.track_to_person[str(track_id)] = person_key
        return rec

    def _merge_person_into(self, source_key: str, target_key: str) -> None:
        if source_key == target_key or source_key not in self.persons:
            return
        src = self.persons.pop(source_key)
        tgt = self._get_or_create(
            target_key,
            student_id=src.student_id,
            full_name=src.full_name,
        )
        tgt.presence_seconds += src.presence_seconds
        tgt.observable_seconds += src.observable_seconds
        tgt.inconclusive_seconds += src.inconclusive_seconds
        tgt.attention_seconds.update(src.attention_seconds)
        tgt.expression_seconds.update(src.expression_seconds)
        tgt.track_ids.update(src.track_ids)
        tgt.last_seen_at = max(tgt.last_seen_at, src.last_seen_at)
        if src.last_expression_pt:
            tgt.last_expression_pt = src.last_expression_pt
        for tid in src.track_ids:
            self.track_to_person[str(tid)] = target_key
        for sig_key, sig in src.signals.items():
            existing = tgt.signals.get(sig_key)
            if existing is None:
                tgt.signals[sig_key] = sig
            else:
                existing.total_seconds += sig.total_seconds
                existing.occurrence_count += sig.occurrence_count
                existing.last_ended_at = max(existing.last_ended_at, sig.last_ended_at)
                existing._episode_seconds.update(sig._episode_seconds)
                existing._episode_spans.update(sig._episode_spans)

    def _maybe_merge_track_to_student(self, track_id: str, student_id: str) -> str:
        student_key = f"student:{student_id}"
        track_key = f"track:{track_id}"
        if track_key in self.persons and track_key != student_key:
            self._merge_person_into(track_key, student_key)
        return student_key

    def ingest_track_sample(
        self,
        *,
        track_id: Optional[str],
        student_id: Optional[str],
        full_name: Optional[str],
        attention_state: str,
        expression_state: str,
        expression_display_pt: Optional[str],
        observation_quality: str,
        delta_seconds: float,
        now: float,
    ) -> None:
        if track_id and student_id:
            person_key = self._maybe_merge_track_to_student(str(track_id), str(student_id))
        else:
            person_key = self._resolve_person_key(student_id=student_id, track_id=track_id)

        rec = self._get_or_create(
            person_key,
            student_id=student_id,
            full_name=full_name,
            track_id=track_id,
        )
        rec.presence_seconds += delta_seconds
        rec.last_seen_at = now
        attn = attention_state or "inconclusive"
        expr = expression_state or "inconclusive"
        rec.attention_seconds[attn] += delta_seconds
        rec.expression_seconds[expr] += delta_seconds
        rec.last_attention = attn
        rec.last_expression = expr
        if expression_display_pt:
            rec.last_expression_pt = expression_display_pt
        if observation_quality == "observable":
            rec.observable_seconds += delta_seconds
        elif attn == "inconclusive" or expr == "inconclusive" or observation_quality in (
            "inconclusive",
            "low_quality",
            "unknown",
        ):
            rec.inconclusive_seconds += delta_seconds

    def ingest_event(self, ev: dict, now: float) -> None:
        lifecycle = ev.get("lifecycle")
        if lifecycle not in ("closed", "updated", "opened"):
            return

        eid = str(ev.get("event_id") or "")
        if lifecycle == "closed" and eid and eid in self.processed_event_ids:
            return

        student_id = ev.get("student_id") or ev.get("confirmed_student_id") or ev.get("candidate_student_id")
        track_id = ev.get("person_track_id") or ev.get("track_id")
        if track_id and student_id:
            person_key = self._maybe_merge_track_to_student(str(track_id), str(student_id))
        else:
            person_key = self._resolve_person_key(student_id=student_id, track_id=track_id)

        event_type = str(ev.get("event_type") or "")
        if not event_type:
            return

        dur = float(ev.get("duration_seconds") or 0.0)
        if dur <= 0:
            return

        rec = self._get_or_create(
            person_key,
            student_id=str(student_id) if student_id else None,
            track_id=str(track_id) if track_id else None,
        )
        rollup = rec.signals.get(event_type)
        if rollup is None:
            rollup = SignalRollup(signal_key=event_type)
            rec.signals[event_type] = rollup

        ended_at = float(ev.get("ended_at") or ev.get("closed_at") or ev.get("updated_at") or now)
        started_raw = ev.get("started_at")
        started_at = float(started_raw) if started_raw is not None else None
        rollup.apply_episode(
            eid,
            dur,
            ended_at=ended_at,
            closed=(lifecycle == "closed"),
            started_at=started_at,
        )
        if lifecycle == "closed" and eid:
            self.processed_event_ids.add(eid)

    def rebuild_signals_from_events(self, events_seen: Dict[str, dict]) -> None:
        """Recalcula sinais a partir do histórico completo (fonte da verdade)."""
        for rec in self.persons.values():
            rec.signals.clear()
        self.processed_event_ids.clear()

        best: Dict[str, dict] = {}
        for ev in events_seen.values():
            eid = str(ev.get("event_id") or "")
            if not eid:
                continue
            dur = float(ev.get("duration_seconds") or 0.0)
            if dur <= 0:
                continue
            prev = best.get(eid)
            if prev is None or dur >= float(prev.get("duration_seconds") or 0):
                best[eid] = dict(ev)
                best[eid]["lifecycle"] = "closed"

        for ev in best.values():
            self.ingest_event(ev, time.time())

        # Contagem pedagógica: merge episódios da mesma família com gap curto
        # (possible→probable e flicker não viram 9 "vezes")
        for rec in self.persons.values():
            self._recompute_occurrence_counts(rec)

    def _recompute_occurrence_counts(self, rec: PersonRecord) -> None:
        """Contagem pedagógica: mesma família + gap curto = 1 ocorrência."""
        episodes: List[Tuple[float, float, str]] = []  # (start, end, family)
        for sig_key, rollup in rec.signals.items():
            family = SIGNAL_FAMILIES.get(sig_key, sig_key)
            for eid, dur in (rollup._episode_seconds or {}).items():
                span = (rollup._episode_spans or {}).get(eid)
                if span is not None:
                    start, end = float(span[0]), float(span[1])
                else:
                    end = float(rollup.last_ended_at or 0.0)
                    start = max(0.0, end - float(dur))
                episodes.append((start, end, family))
            rollup.occurrence_count = 0

        if not episodes:
            return

        by_fam: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        for start, end, fam in episodes:
            by_fam[fam].append((start, end))

        fam_counts: Dict[str, int] = {}
        for fam, spans in by_fam.items():
            spans.sort(key=lambda x: x[0])
            merged = 0
            cur_end = -1e18
            for start, end in spans:
                if start - cur_end <= EVENT_MERGE_GAP_SECONDS:
                    cur_end = max(cur_end, end)
                else:
                    merged += 1
                    cur_end = end
            fam_counts[fam] = max(1, merged)

        for sig_key, rollup in rec.signals.items():
            fam = SIGNAL_FAMILIES.get(sig_key, sig_key)
            if rollup.total_seconds <= 0:
                rollup.occurrence_count = 0
                continue
            siblings = [
                (k, r)
                for k, r in rec.signals.items()
                if SIGNAL_FAMILIES.get(k, k) == fam and r.total_seconds > 0
            ]
            top = max(siblings, key=lambda kr: kr[1].total_seconds)
            if top[0] == sig_key:
                rollup.occurrence_count = fam_counts.get(fam, 1)
            else:
                rollup.occurrence_count = 0

    def ingest_live_state(self, state: dict, *, visible_count: int) -> None:
        now = time.time()
        delta = 2.0 if self.last_ingest_at <= 0 else min(30.0, max(0.5, now - self.last_ingest_at))
        self.last_ingest_at = now
        self.peak_visible = max(self.peak_visible, visible_count)

        for track in state.get("tracks") or []:
            ident = track.get("identity") or {}
            sid = track.get("student_id") or ident.get("student_id")
            tid = track.get("person_track_id") or track.get("track_id")
            name = track.get("full_name") or ident.get("full_name") or sid or "Pessoa não identificada"
            va = track.get("visual_attention") or {}
            ex = track.get("expression") or {}
            q = track.get("observation_quality") or {}
            self.ingest_track_sample(
                track_id=str(tid) if tid else None,
                student_id=str(sid) if sid else None,
                full_name=name,
                attention_state=va.get("state") or "inconclusive",
                expression_state=ex.get("smoothed_state") or ex.get("normalized_state") or "inconclusive",
                expression_display_pt=ex.get("smoothed_display_pt"),
                observation_quality=q.get("status") or "unknown",
                delta_seconds=delta,
                now=now,
            )

        for ev in state.get("live_event_buffer") or []:
            self.ingest_event(ev, now)

    def report_students(self) -> List[dict]:
        out: List[dict] = []
        for rec in self.persons.values():
            if not rec.student_id and rec.presence_seconds < MIN_PRESENCE_EXCLUDE_SECONDS:
                continue
            out.append(rec.to_report_dict())
        out.sort(key=lambda x: (x.get("full_name") or "").lower())
        return out

    def class_time_by_category(self, students: List[dict]) -> List[dict]:
        merged: Dict[str, dict] = {c["category_id"]: dict(c) for c in empty_category_totals()}
        for s in students:
            for cat in s.get("time_by_category") or []:
                cid = cat["category_id"]
                if cid not in merged:
                    merged[cid] = dict(cat)
                else:
                    merged[cid]["total_seconds"] = round(
                        float(merged[cid].get("total_seconds") or 0) + float(cat.get("total_seconds") or 0),
                        1,
                    )
                    merged[cid]["occurrence_count"] = int(merged[cid].get("occurrence_count") or 0) + int(
                        cat.get("occurrence_count") or 0
                    )
        return sorted(merged.values(), key=lambda x: x["total_seconds"], reverse=True)

    def class_observation_profile(self, students: List[dict]) -> dict:
        keys = (
            "presence_seconds",
            "observable_seconds",
            "inconclusive_seconds",
            "attention_high_seconds",
            "attention_moderate_seconds",
            "attention_low_seconds",
            "expression_positive_seconds",
            "expression_neutral_seconds",
            "expression_negative_seconds",
            "expression_mixed_seconds",
        )
        out = {k: 0.0 for k in keys}
        for s in students:
            profile = s.get("observation_profile") or {}
            for k in keys:
                out[k] = round(out[k] + float(profile.get(k) or 0), 1)
        return out

    def aggregate_session(
        self,
        *,
        climate_samples: List[dict],
        events_seen: Dict[str, dict],
        duration_seconds: float,
        current_state: Optional[dict] = None,
    ) -> dict:
        # Fonte da verdade para durações: histórico completo de eventos da sessão
        if events_seen:
            self.rebuild_signals_from_events(events_seen)

        students = self.report_students()
        time_by_category = self.class_time_by_category(students)
        observation_profile = self.class_observation_profile(students)
        obs_samples = [s.get("observable_pct") for s in climate_samples if s.get("observable_pct") is not None]
        avg_obs = round(sum(obs_samples) / len(obs_samples), 1) if obs_samples else None
        climate_hist = Counter(
            s.get("apparent_climate") for s in climate_samples if s.get("apparent_climate")
        )
        events = list(events_seen.values())
        reviewed = [e for e in events if e.get("attribution_status") in ("confirmed", "track_only")]
        current = current_state or {}
        cc = current.get("classroom_counts") or {}
        attn_index = current.get("attention_index") or cc.get("attention_index")
        climate = current.get("apparent_climate") or cc.get("climate")
        attn_level = attention_level_from_index(attn_index)

        class_summary = {
            "visible_now": current.get("visible_people") or self.peak_visible,
            "observable_pct_now": climate_samples[-1].get("observable_pct") if climate_samples else None,
            "attention_level": attn_level,
            "attention_label_pt": attention_label_pt(attn_level),
            "attention_index": attn_index,
            "climate_now": climate,
            "climate_label_pt": climate_label_pt(climate),
            "students_in_report": len(students),
            "identified_students": sum(1 for s in students if s.get("student_id")),
            "time_by_category": time_by_category,
            "observation_profile": observation_profile,
        }

        return {
            "duration_seconds": round(duration_seconds, 1),
            "peak_visible": self.peak_visible,
            "observable_pct_avg": avg_obs,
            "observable_pct_latest": climate_samples[-1].get("observable_pct") if climate_samples else None,
            "climate": climate,
            "climate_label_pt": climate_label_pt(climate),
            "climate_history": dict(climate_hist),
            "climate_timeline": list(climate_samples),
            "attention_index": attn_index,
            "attention_level": attn_level,
            "attention_label_pt": attention_label_pt(attn_level),
            "events_total": len(events),
            "events_open": sum(1 for e in events if e.get("lifecycle") in ("opened", "updated")),
            "events_reviewed": len(reviewed),
            "time_by_category": time_by_category,
            "observation_profile": observation_profile,
            "students": students,
            "students_count": len(students),
            "class_summary": class_summary,
        }
