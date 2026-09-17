"""Acumulador de sessão ao vivo (RTSP/webcam) para dashboard educacional."""

from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.runtime_mode import DISCLAIMER
from app.pipeline.analytics_track import filter_displayable_tracks
from app.services.session_aggregator import SessionAggregator

SAMPLE_INTERVAL_SECONDS = 15.0
MAX_CLIMATE_SAMPLES = 480
MAX_TIMELINE = 200


def _track_key(track: dict) -> str:
    ident = track.get("identity") or {}
    sid = track.get("student_id") or ident.get("student_id")
    if sid:
        return f"student:{sid}"
    return f"track:{track.get('person_track_id') or track.get('track_id') or 'unknown'}"


def dashboard_track_view(track: dict) -> dict:
    """Normaliza track analytics → formato compacto do dashboard."""
    ident = track.get("identity") or {}
    va = track.get("visual_attention") or {}
    ex = track.get("expression") or {}
    q = track.get("observation_quality") or {}
    ph = track.get("phone") or {}
    dr = track.get("drowsiness") or {}
    sid = track.get("student_id") or ident.get("student_id")
    name = track.get("full_name") or ident.get("full_name") or sid or "Pessoa não identificada"
    id_state = ident.get("identity_state") or "unknown"
    attn = va.get("state") or "inconclusive"
    expr = ex.get("smoothed_state") or ex.get("normalized_state") or "inconclusive"
    q_status = q.get("status") or "unknown"
    active = track.get("active_events") or []
    alert = None
    for ev in active:
        et = str(ev.get("event_type") or "")
        if any(x in et for x in ("drowsiness", "phone", "occlud", "attention", "head_down")):
            alert = et
            break
    return {
        "track_id": track.get("person_track_id") or track.get("track_id"),
        "person_track_id": track.get("person_track_id") or track.get("track_id"),
        "student_id": sid,
        "full_name": name,
        "identity_state": id_state,
        "attention_state": attn,
        "expression_window": expr,
        "expression_display_pt": ex.get("smoothed_display_pt"),
        "expression_confidence": ex.get("confidence"),
        "expression_sample_count": ex.get("sample_count"),
        "expression_status": ex.get("status"),
        "expression_reason": ex.get("reason"),
        "observation_quality": q_status,
        "observation_score": q.get("overall_score") or q.get("overall_observability"),
        "visual_attention_score": va.get("confidence"),
        "attention_sample_count": va.get("sample_count"),
        "phone": {
            "state": ph.get("state") or "not_detected",
            "label": ph.get("state") or "not_detected",
            "level": ph.get("state") or "none",
        },
        "drowsiness_state": dr.get("state") or "inconclusive",
        "active_events": active,
        "alert_type": alert,
        "bbox": track.get("bbox") or track.get("person_bbox"),
        "present": bool(sid) or id_state in ("face_confirmed", "body_continuity", "uncertain"),
    }


@dataclass
class LiveSessionStore:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: float = field(default_factory=time.time)
    last_sample_at: float = 0.0
    climate_samples: List[dict] = field(default_factory=list)
    timeline: List[dict] = field(default_factory=list)
    display_smoothing: Dict[str, dict] = field(default_factory=dict)
    events_seen: Dict[str, dict] = field(default_factory=dict)
    aggregator: SessionAggregator = field(default_factory=SessionAggregator)

    def bind_session_id(self, session_id: str, *, started_at: float | None = None) -> None:
        """Alinha o store pedagógico ao ClassSession do Edge (UUID estável)."""
        if not session_id:
            return
        if self.session_id == session_id:
            return
        self.session_id = session_id
        if started_at is not None:
            self.started_at = float(started_at)
        self.aggregator.reset(started_at=self.started_at)

    def reset(self) -> None:
        self.session_id = str(uuid.uuid4())
        self.started_at = time.time()
        self.last_sample_at = 0.0
        self.climate_samples.clear()
        self.timeline.clear()
        self.display_smoothing.clear()
        self.events_seen.clear()
        self.aggregator.reset(started_at=self.started_at)

    def ingest_live_state(self, state: dict) -> None:
        now = time.time()
        tracks = state.get("tracks") or []
        display_tracks = filter_displayable_tracks(tracks)
        views = [dashboard_track_view(t) for t in display_tracks]
        visible = len(views)

        cc = state.get("classroom_counts") or {}
        observable = state.get("observable_people")
        if observable is None:
            observable = cc.get("observable")
        inconclusive = state.get("inconclusive_people")
        if inconclusive is None:
            inconclusive = cc.get("inconclusive")
        visible_n = state.get("visible_people") if state.get("visible_people") is not None else visible
        obs_pct = round(100.0 * float(observable or 0) / visible_n, 1) if visible_n else None

        for v in views:
            key = _track_key({"student_id": v.get("student_id"), "person_track_id": v.get("track_id"), "identity": {}})
            prev = self.display_smoothing.get(key) or {}
            attn = v.get("attention_state") or "inconclusive"
            expr = v.get("expression_window") or "inconclusive"
            q = v.get("observation_quality") or "unknown"
            expr_reason = str(v.get("expression_reason") or "")
            if attn != "inconclusive":
                prev["last_stable_attention"] = attn
                prev["last_stable_attention_at"] = now
            elif prev.get("last_stable_attention") and (now - float(prev.get("last_stable_attention_at") or 0)) < 4.0:
                v["attention_state"] = prev["last_stable_attention"]
                v["attention_display_smoothed"] = True
            if expr != "inconclusive" and q == "observable":
                prev["last_stable_expression"] = expr
                prev["last_stable_expression_at"] = now
                prev["last_stable_expression_pt"] = v.get("expression_display_pt")
            elif expr == "inconclusive" and (
                "occlusion" in expr_reason or "face_not_observable" in expr_reason
            ):
                # Oclusão / rosto sumiu: não grudar expressão antiga (contrato TRI)
                prev.pop("last_stable_expression", None)
                prev.pop("last_stable_expression_at", None)
                prev.pop("last_stable_expression_pt", None)
            elif (
                expr == "inconclusive"
                and prev.get("last_stable_expression")
                and (now - float(prev.get("last_stable_expression_at") or 0)) < 2.5
            ):
                # Qualidade/amostra breve: manter última conclusiva no Ao vivo
                v["expression_window"] = prev["last_stable_expression"]
                if prev.get("last_stable_expression_pt"):
                    v["expression_display_pt"] = prev["last_stable_expression_pt"]
                v["expression_display_smoothed"] = True
            if q == "observable":
                prev["last_stable_quality"] = q
                prev["last_stable_quality_at"] = now
            elif prev.get("last_stable_quality") and (now - float(prev.get("last_stable_quality_at") or 0)) < 4.0:
                v["observation_quality"] = prev["last_stable_quality"]
                v["quality_display_smoothed"] = True
            self.display_smoothing[key] = prev

        ingest_state = dict(state)
        ingest_state["tracks"] = display_tracks
        self.aggregator.ingest_live_state(ingest_state, visible_count=visible_n)

        for ev in state.get("live_event_buffer") or []:
            eid = str(ev.get("event_id") or "")
            if not eid:
                continue
            self.events_seen[eid] = ev
            if ev.get("lifecycle") == "opened" and len(self.timeline) < MAX_TIMELINE:
                self.timeline.append(
                    {
                        "t": round(now - self.started_at, 1),
                        "type": "event_opened",
                        "label": ev.get("event_type"),
                        "student_id": ev.get("student_id") or ev.get("candidate_student_id"),
                        "event_id": eid,
                    }
                )

        if now - self.last_sample_at >= SAMPLE_INTERVAL_SECONDS:
            self.last_sample_at = now
            dist = state.get("climate_distribution") or cc.get("climate_distribution") or {}
            sample = {
                "t": round(now - self.started_at, 1),
                "t_minutes": round((now - self.started_at) / 60.0, 2),
                "apparent_climate": state.get("apparent_climate") or cc.get("climate"),
                "climate_distribution": dist,
                "attention_index": state.get("attention_index") or cc.get("attention_index"),
                "visible_people": visible_n,
                "observable_people": observable,
                "observable_pct": obs_pct,
                "inconclusive_people": inconclusive,
            }
            self.climate_samples.append(sample)
            if len(self.climate_samples) > MAX_CLIMATE_SAMPLES:
                self.climate_samples = self.climate_samples[-MAX_CLIMATE_SAMPLES:]
            if len(self.timeline) < MAX_TIMELINE:
                self.timeline.append(
                    {
                        "t": sample["t"],
                        "type": "climate_sample",
                        "label": sample.get("apparent_climate") or "amostra",
                        "observable_pct": obs_pct,
                    }
                )
            # Snapshot periódico para outbox (não altera TRI)
            try:
                from app.services.session_persistence import enqueue_report_snapshot

                report = self.build_report(state)
                report["provenance"] = {
                    "storage": "session_snapshot",
                    "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
                }
                enqueue_report_snapshot(
                    session_id=self.session_id,
                    report=report,
                    captured_at=now,
                    is_final=False,
                )
            except Exception:
                pass

    def session_meta(self) -> dict:
        elapsed = round(time.time() - self.started_at, 1)
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "t_seconds": elapsed,
            "duration_target": None,
            "playing": True,
            "speed": 1.0,
            "source": "live_rtsp",
        }

    def aggregate(self, state: dict) -> dict:
        return self.aggregator.aggregate_session(
            climate_samples=self.climate_samples,
            events_seen=self.events_seen,
            duration_seconds=time.time() - self.started_at,
            current_state=state,
        )

    def students_list(self) -> List[dict]:
        return self.aggregate({}).get("students") or []

    def build_report(self, state: dict) -> dict:
        agg = self.aggregate(state)
        cc = state.get("classroom_counts") or {}
        return {
            "session_id": self.session_id,
            "runtime_mode": state.get("runtime_mode") or "rtsp",
            "is_simulated": False,
            "disclaimer": DISCLAIMER,
            **agg,
            "students_present": state.get("recognized_people") or cc.get("present"),
            "timeline": list(self.timeline)[-80:],
            "limitations": [
                "Indicadores visuais estimados — não constituem diagnóstico ou avaliação de aprendizagem.",
                "Clima aparente agrega expressões observáveis; inconclusivos não entram na distribuição.",
                "Sessão acumulada em memória desde o último restart do servidor edge.",
            ],
            "provenance": {"storage": "live_session_memory", "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS},
        }


_live_session = LiveSessionStore()


def get_live_session() -> LiveSessionStore:
    return _live_session
