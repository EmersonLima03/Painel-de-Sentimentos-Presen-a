"""Relatórios do módulo emoções/dashboard."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import BehavioralEvent, ClassSession, Event
from app.db.repo import AttendanceRepository, BehavioralEventRepository, ClassSessionRepository, EventRepository
from app.vision.behavioral_taxonomy import DISCLAIMER_PT


def session_timeline(session: Session, session_id: Optional[str] = None, room_id: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    q = session.query(Event).filter(
        Event.event_type.in_(["engagement_window", "climate_window", "behavioral_event", "attendance_checkin"])
    )
    rows = q.order_by(Event.created_at.desc()).limit(limit * 3).all()
    items = []
    for r in rows:
        try:
            payload = json.loads(r.payload_json)
        except Exception:
            continue
        if session_id and payload.get("session_id") and payload.get("session_id") != session_id:
            continue
        if room_id and payload.get("room_id") and payload.get("room_id") != room_id:
            continue
        items.append(
            {
                "event_id": r.event_id,
                "event_type": r.event_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "status": r.status,
                "payload": payload,
            }
        )
        if len(items) >= limit:
            break
    items.reverse()
    return {"disclaimer": DISCLAIMER_PT, "items": items, "count": len(items)}


def engagement_report(session: Session, room_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    q = session.query(Event).filter(Event.event_type == "engagement_window")
    rows = q.order_by(Event.created_at.desc()).limit(limit).all()
    series = []
    for r in rows:
        try:
            p = json.loads(r.payload_json)
        except Exception:
            continue
        if room_id and p.get("room_id") != room_id:
            continue
        series.append(
            {
                "ts_start": p.get("ts_start"),
                "ts_end": p.get("ts_end"),
                "engagement_index_avg": p.get("engagement_index_avg"),
                "activity_level": p.get("activity_level"),
                "states_distribution": p.get("states_distribution"),
                "faces_detected_avg": p.get("faces_detected_avg"),
                "room_id": p.get("room_id"),
            }
        )
    series.reverse()
    avg = 0.0
    if series:
        avg = sum(float(s.get("engagement_index_avg") or 0) for s in series) / len(series)
    return {
        "disclaimer": DISCLAIMER_PT,
        "label": "Engajamento aparente (estimativa)",
        "avg_engagement_index": round(avg, 3),
        "points": series,
    }


def climate_report(session: Session, room_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    q = session.query(Event).filter(Event.event_type == "climate_window")
    rows = q.order_by(Event.created_at.desc()).limit(limit).all()
    series = []
    for r in rows:
        try:
            p = json.loads(r.payload_json)
        except Exception:
            continue
        if room_id and p.get("room_id") != room_id:
            continue
        series.append(
            {
                "ts_start": p.get("ts_start"),
                "ts_end": p.get("ts_end"),
                "dominant_climate": p.get("dominant_climate"),
                "climate_distribution": p.get("climate_distribution"),
                "activity_energy": p.get("activity_energy"),
                "room_id": p.get("room_id"),
            }
        )
    series.reverse()
    return {
        "disclaimer": DISCLAIMER_PT,
        "label": "Clima / humor aparente da turma (estimativa agregada)",
        "points": series,
    }


def observability_summary(session: Session, room_id: Optional[str] = None) -> Dict[str, Any]:
    beh = BehavioralEventRepository(session)
    events = beh.list_events(room_id=room_id, limit=100)
    low_q = sum(1 for e in events if e.event_type == "low_observation_quality")
    out_field = sum(1 for e in events if e.event_type == "out_of_field")
    drowsiness = sum(1 for e in events if e.event_type == "possible_drowsiness")
    pending = sum(1 for e in events if e.status == "pending_review")
    return {
        "disclaimer": DISCLAIMER_PT,
        "low_observation_quality_events": low_q,
        "out_of_field_events": out_field,
        "possible_drowsiness_events": drowsiness,
        "pending_review": pending,
        "total_behavioral_recent": len(events),
    }


def live_kpis(orchestrator, session: Session) -> Dict[str, Any]:
    status = orchestrator.get_status() if orchestrator else {"cameras": {}, "running": False}
    climate = {}
    vision = {"detector_backend": "none", "embedder_backend": "none", "faiss_enabled": False}
    if orchestrator:
        climate = getattr(orchestrator, "_latest_climate", {}) or {}
        try:
            vision = orchestrator.get_vision_backends()
        except Exception:
            pass
    sess_repo = ClassSessionRepository(session)
    active = sess_repo.get_active()
    present = 0
    if active:
        present = len(AttendanceRepository(session).list_for_session(active.session_id))
    return {
        "disclaimer": DISCLAIMER_PT,
        "session_id": active.session_id if active else None,
        "session_status": active.status if active else None,
        "present_count": present,
        "cameras": status.get("cameras") or {},
        "latest_climate_by_camera": climate,
        "running": status.get("running", False),
        "vision": vision,
    }


def unified_overview(
    orchestrator,
    session: Session,
    *,
    version: str = "",
    uptime_seconds: int = 0,
    simulation_mode: bool = False,
    supabase_enabled: bool = False,
    device_id: str = "",
    school_id: str = "",
) -> Dict[str, Any]:
    """Um payload único para o painel consolidado."""
    live = live_kpis(orchestrator, session)
    cams = live.get("cameras") or {}
    online = sum(1 for c in cams.values() if c.get("is_connected"))
    faces = sum(int(c.get("faces_detected_last") or 0) for c in cams.values())

    event_repo = EventRepository(session)
    queue = event_repo.get_stats()
    obs = observability_summary(session)
    eng = engagement_report(session, limit=20)
    clim = climate_report(session, limit=20)

    camera_rows = []
    for cam_id, st in cams.items():
        camera_rows.append(
            {
                "camera_id": cam_id,
                "connected": bool(st.get("is_connected")),
                "faces": int(st.get("faces_detected_last") or 0),
                "last_match": st.get("last_presence_match"),
                "source": st.get("source") or st.get("rtsp_url") or "—",
                "fps": st.get("fps"),
                "error": st.get("last_error") or st.get("error"),
            }
        )

    return {
        "disclaimer": DISCLAIMER_PT,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "system": {
            "status": "ok" if live.get("running") or online > 0 else "idle",
            "version": version,
            "uptime_seconds": uptime_seconds,
            "device_id": device_id,
            "school_id": school_id,
            "simulation_mode": simulation_mode,
            "supabase_enabled": supabase_enabled,
            "pipeline_running": bool(live.get("running")),
            "vision": live.get("vision") or {},
        },
        "session": {
            "session_id": live.get("session_id"),
            "status": live.get("session_status"),
            "present_count": live.get("present_count", 0),
        },
        "cameras": {
            "online": online,
            "total": len(cams),
            "faces_last": faces,
            "items": camera_rows,
        },
        "queue": queue,
        "observability": obs,
        "engagement": eng,
        "climate": clim,
        "latest_climate_by_camera": live.get("latest_climate_by_camera") or {},
        "links": {
            "dashboard": "/dashboard",
            "health": "/health",
            "stats": "/stats",
            "debug_viewer": "/debug/viewer",
            "debug_enroll": "/debug/enroll",
            "docs": "/docs",
            "module_dod": "/module/dod",
        },
    }

