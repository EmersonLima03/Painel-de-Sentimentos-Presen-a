"""Persistência pedagógica → outbox local (SQLite events) para sync Sentimentos.

Não toca TRI/visão. Apenas empilha payloads idempotentes no outbox existente.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import get_settings
from app.db.init_db import close_session, get_session
from app.db.repo import EventRepository
from app.logging import get_logger

logger = get_logger(__name__)

SNAPSHOT_SCHEMA_VERSION = 1


def _ts_iso(ts: float | None) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def enqueue_outbox(event_type: str, event_id: str, payload: Dict[str, Any]) -> bool:
    """Insere no outbox SQLite se ainda não existir (idempotente por event_id)."""
    session = get_session()
    try:
        from app.db.models import Event

        row = session.query(Event).filter(Event.event_id == event_id).first()
        if row:
            return False
        EventRepository(session).create_event(
            event_id=event_id,
            event_type=event_type,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        )
        return True
    except Exception as e:
        logger.warning("outbox_enqueue_failed", event_type=event_type, error=str(e))
        return False
    finally:
        close_session(session)


def enqueue_class_session_upsert(
    *,
    session_id: str,
    status: str,
    started_at: float,
    ended_at: float | None = None,
    title: str | None = None,
    external_lesson_id: str | None = None,
) -> None:
    settings = get_settings()
    org = getattr(settings, "cloud_organization_id", "") or ""
    school = getattr(settings, "cloud_school_id", "") or ""
    lesson = external_lesson_id or (getattr(settings, "lxp_external_lesson_id", "") or None)
    payload = {
        "event_type": "class_session_upsert",
        "event_id": f"session:{session_id}:{status}",
        "session": {
            "id": session_id,
            "organization_id": org or None,
            "school_id": school or None,
            "title": title or "Sessão",
            "status": status,
            "started_at": _ts_iso(started_at),
            "ended_at": _ts_iso(ended_at),
            "source_device_id": settings.device_id,
            "scheduled_start_at": None,
            "scheduled_duration_minutes": None,
            "external_lesson_id": lesson or None,
        },
        "device_id": settings.device_id,
        "school_id": school or settings.school_id,
    }
    enqueue_outbox("class_session_upsert", payload["event_id"], payload)


def enqueue_session_event_upsert(event: Dict[str, Any], *, lifecycle: str) -> None:
    settings = get_settings()
    org = getattr(settings, "cloud_organization_id", "") or ""
    school = getattr(settings, "cloud_school_id", "") or ""
    event_id = str(event.get("event_id") or "")
    if not event_id:
        return
    session_id = event.get("session_id")
    if not session_id:
        return
    opened = float(event.get("started_at") or event.get("opened_at") or time.time())
    closed = event.get("ended_at") or event.get("closed_at")
    status = "closed" if lifecycle == "closed" or closed else "open"
    payload = {
        "event_type": "session_event_upsert",
        "event_id": f"evt:{event_id}:{lifecycle}",
        "session_event": {
            "id": event_id,
            "session_id": session_id,
            "organization_id": org or None,
            "school_id": school or None,
            "device_id": settings.device_id,
            "edge_camera_id": event.get("camera_id"),
            "student_id": None,  # cloud UUID mapping is future; edge key in payload
            "anonymous_track_id": event.get("track_id") or event.get("person_track_id"),
            "event_type": event.get("event_type"),
            "opened_at": _ts_iso(opened),
            "closed_at": _ts_iso(float(closed)) if closed else None,
            "duration_seconds": event.get("duration_seconds"),
            "confidence": event.get("confidence"),
            "observation_quality": event.get("observation_quality"),
            "status": status,
            "review_status": "pending_review"
            if event.get("requires_human_review")
            else "none",
            "payload": {
                "edge_student_key": event.get("student_id"),
                "reasons": event.get("reasons"),
                "lifecycle": lifecycle,
                # never include embeddings / frames
            },
        },
        "device_id": settings.device_id,
    }
    enqueue_outbox("session_event_upsert", payload["event_id"], payload)


def enqueue_report_snapshot(
    *,
    session_id: str,
    report: Dict[str, Any],
    captured_at: float | None = None,
    is_final: bool = False,
    snapshot_id: str | None = None,
) -> None:
    settings = get_settings()
    org = getattr(settings, "cloud_organization_id", "") or ""
    school = getattr(settings, "cloud_school_id", "") or ""
    captured = captured_at or time.time()
    sid = snapshot_id or hashlib.sha256(
        f"{session_id}:{captured}:{int(is_final)}".encode()
    ).hexdigest()[:32]
    # stable uuid-like
    snap_uuid = f"{sid[:8]}-{sid[8:12]}-{sid[12:16]}-{sid[16:20]}-{sid[20:32]}"
    payload = {
        "event_type": "session_report_snapshot",
        "event_id": f"snap:{session_id}:{int(captured)}:{int(is_final)}",
        "snapshot": {
            "id": snap_uuid,
            "session_id": session_id,
            "organization_id": org or None,
            "school_id": school or None,
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "captured_at": _ts_iso(captured),
            "report": report,
            "source_device_id": settings.device_id,
            "is_final": is_final,
        },
        "device_id": settings.device_id,
    }
    enqueue_outbox("session_report_snapshot", payload["event_id"], payload)


def enqueue_device_heartbeat(*, app_version: str | None = None) -> None:
    settings = get_settings()
    eid = f"hb:{settings.device_id}:{int(time.time() // 60)}"
    payload = {
        "event_type": "device_heartbeat",
        "event_id": eid,
        "device_id": settings.device_id,
        "app_version": app_version or "0.1.0",
        "last_seen_at": _ts_iso(time.time()),
    }
    enqueue_outbox("device_heartbeat", eid, payload)
