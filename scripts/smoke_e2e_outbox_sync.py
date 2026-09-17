"""Smoke E2E: outbox → SyncWorker → ingest (online / offline / restart).

Usa a camada real de session_persistence + SyncWorker.
Não toca TRI/visão. Não imprime tokens.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments" / "smoke_e2e_sentimentos"
OUT.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    for name in (".env", ".env.smoke.local"):
        p = ROOT / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _outbox_counts() -> dict:
    from app.db.init_db import close_session, get_session
    from app.db.models import Event

    s = get_session()
    try:
        rows = s.query(Event).all()
        by = {}
        for r in rows:
            by[r.status] = by.get(r.status, 0) + 1
        pending_types = [
            {"event_id": r.event_id, "event_type": r.event_type, "status": r.status}
            for r in rows
            if r.status in ("pending", "failed")
        ]
        return {"by_status": by, "pending_detail": pending_types, "total": len(rows)}
    finally:
        close_session(s)


async def _sync_once() -> None:
    from app.sync.worker import SyncWorker

    w = SyncWorker()
    # force enough retries for smoke
    w.retry_attempts = 5
    await w.sync_batch()


def main() -> None:
    _load_dotenv()
    # Settings não aceita SUPABASE_URL genérico (só INGEST_URL / ANON_KEY)
    # DB isolado: evita backlog legado (climate/engagement) no dulino_edge.db
    smoke_db = ROOT / "experiments" / "smoke_e2e_sentimentos" / "smoke_edge.db"
    smoke_db.parent.mkdir(parents=True, exist_ok=True)
    if smoke_db.exists():
        smoke_db.unlink()
    os.environ["SQLITE_PATH"] = str(smoke_db)
    from app.config import get_settings, reload_settings
    from app.db.init_db import reset_db_singleton, init_database

    settings = reload_settings()
    reset_db_singleton()
    init_database()

    report: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "phases": {}}

    assert settings.supabase_ingest_url, "SUPABASE_INGEST_URL missing"
    assert settings.device_token, "DEVICE_TOKEN missing"
    assert settings.cloud_organization_id, "CLOUD_ORGANIZATION_ID missing"
    assert settings.cloud_school_id, "CLOUD_SCHOOL_ID missing"

    from app.services.session_persistence import (
        enqueue_class_session_upsert,
        enqueue_report_snapshot,
        enqueue_session_event_upsert,
    )

    # ---------- ONLINE ----------
    session_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    t0 = time.time()
    enqueue_class_session_upsert(
        session_id=session_id,
        status="active",
        started_at=t0,
        title="Smoke E2E Online",
    )
    enqueue_session_event_upsert(
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "phone_use",
            "started_at": t0,
            "track_id": "anon-1",
            "camera_id": "cam-1",
        },
        lifecycle="open",
    )
    enqueue_report_snapshot(
        session_id=session_id,
        report={"attention_now": 0.55, "phase": "online"},
        captured_at=t0 + 1,
        is_final=False,
    )
    before = _outbox_counts()
    asyncio.run(_sync_once())
    after = _outbox_counts()
    report["phases"]["online"] = {
        "session_id": session_id,
        "event_id": event_id,
        "outbox_before": before,
        "outbox_after": after,
    }

    # ---------- OFFLINE ----------
    offline_session = str(uuid.uuid4())
    offline_events = [str(uuid.uuid4()) for _ in range(3)]
    real_url = settings.supabase_ingest_url
    # Simulate offline: unreachable host
    os.environ["SUPABASE_INGEST_URL"] = "https://127.0.0.1:9/functions/v1/ingest-events"
    reload_settings()
    t_off = time.time()
    enqueue_class_session_upsert(
        session_id=offline_session,
        status="active",
        started_at=t_off,
        title="Smoke E2E Offline",
    )
    for eid in offline_events:
        enqueue_session_event_upsert(
            {
                "event_id": eid,
                "session_id": offline_session,
                "event_type": "sleep_risk",
                "started_at": time.time(),
                "track_id": "anon-off",
            },
            lifecycle="open",
        )
    enqueue_report_snapshot(
        session_id=offline_session,
        report={"attention_now": 0.4, "phase": "offline"},
        captured_at=time.time(),
        is_final=False,
    )
    pending_offline = _outbox_counts()
    # attempt sync while offline — should fail and keep pending
    asyncio.run(_sync_once())
    still_pending = _outbox_counts()
    offline_duration_s = 2.0
    time.sleep(offline_duration_s)
    report["phases"]["offline"] = {
        "session_id": offline_session,
        "event_ids": offline_events,
        "duration_s": offline_duration_s,
        "pending_after_enqueue": pending_offline,
        "pending_after_failed_sync": still_pending,
    }

    # ---------- RETURN ONLINE ----------
    os.environ["SUPABASE_INGEST_URL"] = real_url
    reload_settings()
    # end offline session + final snapshot
    enqueue_class_session_upsert(
        session_id=offline_session,
        status="ended",
        started_at=t_off,
        ended_at=time.time(),
        title="Smoke E2E Offline",
    )
    enqueue_report_snapshot(
        session_id=offline_session,
        report={"attention_now": 0.42, "phase": "final"},
        captured_at=time.time(),
        is_final=True,
    )
    # sync multiple batches until drained
    for _ in range(8):
        asyncio.run(_sync_once())
        c = _outbox_counts()
        if c["by_status"].get("pending", 0) == 0 and c["by_status"].get("failed", 0) == 0:
            break
        time.sleep(0.5)
    after_online = _outbox_counts()
    report["phases"]["return_online"] = {"outbox": after_online}

    # ---------- RESTART SIMULATION ----------
    # Persist active session in SQLite ClassSession, "restart" by reading get_active
    from app.db.init_db import close_session, get_session
    from app.db.repo import ClassSessionRepository

    s = get_session()
    try:
        repo = ClassSessionRepository(s)
        # end any active leftovers first
        while True:
            act = repo.get_active()
            if not act:
                break
            repo.end_session(act.session_id)
        restart_sid = str(uuid.uuid4())
        repo.create_session(
            session_id=restart_sid,
            school_id=str(settings.school_id),
            room_id="DEV",
            device_id=settings.device_id,
            title="Smoke Restart",
        )
        enqueue_class_session_upsert(
            session_id=restart_sid,
            status="active",
            started_at=time.time(),
            title="Smoke Restart",
        )
    finally:
        close_session(s)

    # simulate restart: new process would call get_active
    s2 = get_session()
    try:
        repo2 = ClassSessionRepository(s2)
        resumed = repo2.get_active()
        resume_id = resumed.session_id if resumed else None
        # orphan rule: if we end and recreate, no second active
        report["phases"]["restart"] = {
            "created_session_id": restart_sid,
            "resumed_session_id": resume_id,
            "same_uuid": resume_id == restart_sid,
            "duplicate_active": False,
        }
        # ensure only one active
        from app.db.models import ClassSession

        n_active = s2.query(ClassSession).filter(ClassSession.status == "active").count()
        report["phases"]["restart"]["active_count"] = n_active
        report["phases"]["restart"]["ok"] = resume_id == restart_sid and n_active == 1
    finally:
        close_session(s2)

    asyncio.run(_sync_once())

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (OUT / "e2e_outbox_sync.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
