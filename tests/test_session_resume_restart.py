"""Testes de retomada de ClassSession após restart (sem TRI)."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta

import pytest

from app.db.init_db import close_session, get_session, init_database, reset_db_singleton
from app.db.models import ClassSession
from app.db.repo import ClassSessionRepository
from app.services.live_session import LiveSessionStore, get_live_session
from app.services.session_bootstrap import ensure_active_class_session
from app.services.session_persistence import enqueue_report_snapshot, enqueue_session_event_upsert


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    db = tmp_path / "edge_restart.db"
    monkeypatch.setenv("SQLITE_PATH", str(db))
    reset_db_singleton()
    from app.config import reload_settings

    reload_settings()
    init_database()
    # reset singleton live store
    store = get_live_session()
    store.reset()
    yield db
    store.reset()
    reset_db_singleton()


def _create_active(session_id: str, *, hours_ago: float = 0.1) -> None:
    s = get_session()
    try:
        repo = ClassSessionRepository(s)
        repo.create_session(
            session_id=session_id,
            school_id="school-test",
            room_id="room-1",
            device_id="edge-test",
            title="Teste restart",
        )
        row = s.query(ClassSession).filter(ClassSession.session_id == session_id).first()
        row.started_at = datetime.utcnow() - timedelta(hours=hours_ago)
        s.commit()
    finally:
        close_session(s)


def test_resume_active_session_same_id(isolated_db):
    x = str(uuid.uuid4())
    _create_active(x)
    get_live_session().reset()
    assert get_live_session().session_id == ""

    sid = ensure_active_class_session(create_if_missing=False)
    assert sid == x
    assert get_live_session().session_id == x

    # simula "restart": novo store bind via bootstrap
    get_live_session().reset()
    sid2 = ensure_active_class_session(create_if_missing=True)
    assert sid2 == x
    assert get_live_session().session_id == x


def test_ended_session_not_resumed(isolated_db):
    x = str(uuid.uuid4())
    _create_active(x)
    s = get_session()
    try:
        ClassSessionRepository(s).end_session(x)
    finally:
        close_session(s)

    get_live_session().reset()
    sid = ensure_active_class_session(create_if_missing=False)
    assert sid is None
    assert get_live_session().session_id == ""


def test_no_active_creates_new_when_allowed(isolated_db):
    get_live_session().reset()
    sid = ensure_active_class_session(create_if_missing=True)
    assert sid
    assert get_live_session().session_id == sid
    s = get_session()
    try:
        row = s.query(ClassSession).filter(ClassSession.session_id == sid).first()
        assert row is not None
        assert row.status == "active"
    finally:
        close_session(s)


def test_events_and_snapshot_use_resumed_id(isolated_db, monkeypatch):
    x = str(uuid.uuid4())
    _create_active(x)
    get_live_session().reset()
    assert ensure_active_class_session(create_if_missing=True) == x

    ev = str(uuid.uuid4())
    t0 = time.time()
    enqueue_session_event_upsert(
        {"event_id": ev, "session_id": x, "event_type": "phone_use", "started_at": t0},
        lifecycle="open",
    )
    enqueue_report_snapshot(session_id=x, report={"ok": True}, captured_at=t0)

    s = get_session()
    try:
        from app.db.models import Event
        import json
        from sqlalchemy import or_

        rows = (
            s.query(Event)
            .filter(
                or_(
                    Event.event_id.like(f"%{x}%"),
                    Event.event_id.like(f"%{ev}%"),
                )
            )
            .all()
        )
        assert len(rows) >= 2
        for r in rows:
            blob = r.payload_json or ""
            assert x in blob or x in r.event_id or ev in r.event_id
            if r.event_type == "session_event_upsert":
                payload = json.loads(r.payload_json)
                assert payload.get("session", payload.get("event", {})).get("session_id") == x or x in r.payload_json
    finally:
        close_session(s)


def test_live_store_bind_idempotent():
    store = LiveSessionStore()
    assert store.session_id == ""
    store.bind_session_id("aaa")
    assert store.session_id == "aaa"
    store.bind_session_id("aaa", started_at=100.0)
    assert store.started_at == 100.0
    store.bind_session_id("bbb")
    assert store.session_id == "bbb"
