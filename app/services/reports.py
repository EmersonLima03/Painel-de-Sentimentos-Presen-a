"""Relatórios de presença e engajamento (padrão AI-Based-Student-Monitoring)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Event
from app.utils.time import get_date_key


def _parse_payload(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def attendance_summary_today(session: Session, school_id: Optional[str] = None) -> Dict[str, Any]:
    """Resumo de check-ins do dia (por aluno e sala)."""
    date_key = get_date_key()
    q = session.query(Event).filter(Event.event_type == "attendance_checkin")
    rows = q.order_by(Event.created_at.desc()).limit(5000).all()

    by_student: Dict[str, dict] = {}
    by_room: Dict[str, int] = {}

    for ev in rows:
        p = _parse_payload(ev.payload_json)
        if p.get("date_key") and p.get("date_key") != date_key:
            continue
        sid = p.get("student_id") or "unknown"
        room = p.get("room_id") or "unknown"
        by_room[room] = by_room.get(room, 0) + 1
        if sid not in by_student:
            by_student[sid] = {
                "student_id": sid,
                "room_id": room,
                "first_seen_ts": p.get("ts"),
                "checkins": 0,
            }
        by_student[sid]["checkins"] += 1

    return {
        "date": date_key,
        "school_id": school_id,
        "total_checkins": sum(by_room.values()),
        "unique_students": len(by_student),
        "by_room": by_room,
        "students": list(by_student.values()),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def engagement_summary(
    session: Session,
    *,
    room_id: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Médias de janelas de engajamento recentes."""
    q = session.query(Event).filter(Event.event_type == "engagement_window")
    rows = q.order_by(Event.created_at.desc()).limit(limit).all()

    windows: List[dict] = []
    indices: List[float] = []
    faces_avgs: List[float] = []

    for ev in rows:
        p = _parse_payload(ev.payload_json)
        if room_id and p.get("room_id") != room_id:
            continue
        idx = float(p.get("engagement_index_avg") or 0)
        faces = float(p.get("faces_detected_avg") or 0)
        indices.append(idx)
        faces_avgs.append(faces)
        windows.append(
            {
                "event_id": ev.event_id,
                "room_id": p.get("room_id"),
                "ts_start": p.get("ts_start"),
                "ts_end": p.get("ts_end"),
                "engagement_index_avg": idx,
                "faces_detected_avg": faces,
                "activity_level": p.get("activity_level"),
                "model_version": p.get("model_version"),
                "states_distribution": p.get("states_distribution"),
            }
        )

    n = len(indices)
    return {
        "room_id": room_id,
        "window_count": n,
        "engagement_index_mean": round(sum(indices) / n, 3) if n else 0.0,
        "faces_detected_mean": round(sum(faces_avgs) / n, 2) if n else 0.0,
        "windows": windows[:limit],
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
