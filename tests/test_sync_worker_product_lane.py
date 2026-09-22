"""Testes do SyncWorker — bug FIFO+whitelist e lane product MVP."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from app.db.models import Event
from app.db.repo import EventRepository
from app.sync.outbox_contract import CLOUD_MVP_SYNCABLE_TYPES
from app.sync.worker import SyncWorker


class FakeClient:
    def __init__(self, *, fail_ids: set[str] | None = None, fail_once: set[str] | None = None):
        self.sent: List[Dict[str, Any]] = []
        self.fail_ids = fail_ids or set()
        self.fail_once = fail_once or set()
        self._failed_once: set[str] = set()

    async def send_event(self, event_payload: Dict) -> bool:
        eid = str(event_payload.get("event_id") or "")
        if eid in self.fail_ids:
            return False
        if eid in self.fail_once and eid not in self._failed_once:
            self._failed_once.add(eid)
            return False
        self.sent.append(event_payload)
        return True


def _insert(
    session,
    *,
    event_id: str,
    event_type: str,
    created_at: datetime,
    payload: Dict[str, Any] | None = None,
) -> None:
    body = payload or {"event_id": event_id, "event_type": event_type}
    row = Event(
        event_id=event_id,
        event_type=event_type,
        payload_json=json.dumps(body),
        status="pending",
        created_at=created_at,
        retries=0,
    )
    session.add(row)
    session.commit()


def test_fifo_whitelist_bug_fixed_product_not_blocked(db_session):
    """Reproduz o bug: 10 test antigos + 1 session novo → deve sincronizar session."""
    base = datetime(2026, 7, 1, 12, 0, 0)
    for i in range(10):
        _insert(
            db_session,
            event_id=f"old-test-{i}",
            event_type="test",
            created_at=base + timedelta(seconds=i),
        )
    _insert(
        db_session,
        event_id="session:new:active",
        event_type="class_session_upsert",
        created_at=base + timedelta(days=60),
        payload={
            "event_id": "session:new:active",
            "event_type": "class_session_upsert",
            "session": {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
        },
    )

    # Comportamento antigo (bug): limit 10 sem filtro → só test
    repo = EventRepository(db_session)
    old_way = repo.get_pending_events(limit=10)
    assert len(old_way) == 10
    assert all(e.event_type == "test" for e in old_way)
    # simula whitelist pós-LIMIT → lote vazio
    whitelist = list(CLOUD_MVP_SYNCABLE_TYPES)
    after_filter = [e for e in old_way if e.event_type in whitelist]
    assert after_filter == []

    # Comportamento novo: filter antes do LIMIT
    product = repo.get_pending_events(
        limit=10,
        event_types=CLOUD_MVP_SYNCABLE_TYPES,
        prioritize_types=CLOUD_MVP_SYNCABLE_TYPES,
    )
    assert len(product) == 1
    assert product[0].event_type == "class_session_upsert"

    client = FakeClient()
    worker = SyncWorker(client=client)
    worker.batch_size = 10
    worker.retry_attempts = 3
    worker.retry_backoff = 0
    asyncio.run(worker.sync_batch())

    assert len(client.sent) == 1
    assert client.sent[0]["event_type"] == "class_session_upsert"
    # test permanece pending (não apagado)
    db_session.expire_all()
    still_test = (
        db_session.query(Event)
        .filter(Event.event_type == "test", Event.status == "pending")
        .count()
    )
    assert still_test == 10
    sent_row = db_session.query(Event).filter(Event.event_id == "session:new:active").one()
    assert sent_row.status == "sent"


@pytest.mark.parametrize(
    "blocker_type",
    ["test", "climate_window", "engagement_window", "behavioral_event", "attendance_checkin"],
)
def test_telemetry_types_do_not_block_product(db_session, blocker_type):
    base = datetime(2026, 8, 1, 10, 0, 0)
    for i in range(15):
        _insert(
            db_session,
            event_id=f"block-{blocker_type}-{i}",
            event_type=blocker_type,
            created_at=base + timedelta(seconds=i),
        )
    for et, eid in [
        ("class_session_upsert", "p-session"),
        ("session_event_upsert", "p-event"),
        ("session_report_snapshot", "p-snap"),
        ("device_heartbeat", "p-hb"),
    ]:
        _insert(
            db_session,
            event_id=eid,
            event_type=et,
            created_at=base + timedelta(hours=5),
            payload={"event_id": eid, "event_type": et},
        )

    client = FakeClient()
    worker = SyncWorker(client=client)
    worker.batch_size = 10
    worker.retry_backoff = 0
    asyncio.run(worker.sync_batch())

    sent_types = {p["event_type"] for p in client.sent}
    assert sent_types == {
        "class_session_upsert",
        "session_event_upsert",
        "session_report_snapshot",
        "device_heartbeat",
    }
    blocked_pending = (
        db_session.query(Event)
        .filter(Event.event_type == blocker_type, Event.status == "pending")
        .count()
    )
    assert blocked_pending == 15


def test_product_priority_order_in_batch(db_session):
    base = datetime(2026, 9, 1, 8, 0, 0)
    # heartbeat criado antes, session depois — prioridade deve colocar session primeiro
    _insert(
        db_session,
        event_id="hb-1",
        event_type="device_heartbeat",
        created_at=base,
        payload={"event_id": "hb-1", "event_type": "device_heartbeat"},
    )
    _insert(
        db_session,
        event_id="sess-1",
        event_type="class_session_upsert",
        created_at=base + timedelta(minutes=5),
        payload={"event_id": "sess-1", "event_type": "class_session_upsert"},
    )
    _insert(
        db_session,
        event_id="evt-1",
        event_type="session_event_upsert",
        created_at=base + timedelta(minutes=6),
        payload={"event_id": "evt-1", "event_type": "session_event_upsert"},
    )
    _insert(
        db_session,
        event_id="snap-1",
        event_type="session_report_snapshot",
        created_at=base + timedelta(minutes=7),
        payload={"event_id": "snap-1", "event_type": "session_report_snapshot"},
    )

    repo = EventRepository(db_session)
    batch = repo.get_pending_events(
        limit=10,
        event_types=CLOUD_MVP_SYNCABLE_TYPES,
        prioritize_types=CLOUD_MVP_SYNCABLE_TYPES,
    )
    assert [e.event_type for e in batch] == [
        "class_session_upsert",
        "session_event_upsert",
        "session_report_snapshot",
        "device_heartbeat",
    ]


def test_lxp_lane_not_blocked_by_product_failures(db_session):
    """Fila product 401/fail não pode impedir envio LXP."""
    from app.integrations.attendance_lxp import LXP_ATTENDANCE_EVENT_TYPE

    class FakeLxp:
        def __init__(self):
            self.sent = []

        async def send_attendance_event(self, payload):
            self.sent.append(payload)
            return True

    base = datetime(2026, 9, 4, 8, 0, 0)
    for i in range(15):
        _insert(
            db_session,
            event_id=f"snap-block-{i}",
            event_type="session_report_snapshot",
            created_at=base + timedelta(seconds=i),
            payload={"event_id": f"snap-block-{i}", "event_type": "session_report_snapshot"},
        )
    lxp_id = "lxp-att:not-blocked"
    _insert(
        db_session,
        event_id=lxp_id,
        event_type=LXP_ATTENDANCE_EVENT_TYPE,
        created_at=base + timedelta(hours=1),
        payload={
            "event_id": lxp_id,
            "event_type": LXP_ATTENDANCE_EVENT_TYPE,
            "lesson_id": "lesson-8b-math-50",
            "student_id": "ext-stu-001",
            "attendance": "present",
        },
    )

    product = FakeClient(fail_ids={f"snap-block-{i}" for i in range(15)})
    lxp = FakeLxp()
    worker = SyncWorker(client=product, lxp_client=lxp)  # type: ignore[arg-type]
    worker.batch_size = 10
    worker.retry_attempts = 2
    worker.retry_backoff = 0
    asyncio.run(worker.sync_batch())

    assert len(lxp.sent) == 1
    db_session.expire_all()
    assert db_session.query(Event).filter(Event.event_id == lxp_id).one().status == "sent"


def test_batch_limit_only_product(db_session):
    base = datetime(2026, 9, 2, 9, 0, 0)
    for i in range(20):
        _insert(
            db_session,
            event_id=f"clim-{i}",
            event_type="climate_window",
            created_at=base + timedelta(seconds=i),
        )
    for i in range(12):
        _insert(
            db_session,
            event_id=f"sess-{i}",
            event_type="class_session_upsert",
            created_at=base + timedelta(hours=1, seconds=i),
            payload={"event_id": f"sess-{i}", "event_type": "class_session_upsert"},
        )

    client = FakeClient()
    worker = SyncWorker(client=client)
    worker.batch_size = 10
    worker.retry_backoff = 0
    asyncio.run(worker.sync_batch())
    assert len(client.sent) == 10
    assert all(p["event_type"] == "class_session_upsert" for p in client.sent)


def test_retry_then_success(db_session):
    base = datetime(2026, 9, 3, 10, 0, 0)
    _insert(
        db_session,
        event_id="retry-me",
        event_type="device_heartbeat",
        created_at=base,
        payload={"event_id": "retry-me", "event_type": "device_heartbeat"},
    )
    client = FakeClient(fail_once={"retry-me"})
    worker = SyncWorker(client=client)
    worker.retry_attempts = 3
    worker.retry_backoff = 0
    asyncio.run(worker.sync_batch())
    db_session.expire_all()
    row = db_session.query(Event).filter(Event.event_id == "retry-me").one()
    assert row.status == "pending"
    assert row.retries >= 1

    asyncio.run(worker.sync_batch())
    db_session.expire_all()
    row = db_session.query(Event).filter(Event.event_id == "retry-me").one()
    assert row.status == "sent"
    assert len(client.sent) == 1


def test_network_failure_marks_failed_after_max_retries(db_session):
    base = datetime(2026, 9, 3, 11, 0, 0)
    _insert(
        db_session,
        event_id="always-fail",
        event_type="class_session_upsert",
        created_at=base,
        payload={"event_id": "always-fail", "event_type": "class_session_upsert"},
    )
    client = FakeClient(fail_ids={"always-fail"})
    worker = SyncWorker(client=client)
    worker.retry_attempts = 2
    worker.retry_backoff = 0
    asyncio.run(worker.sync_batch())
    asyncio.run(worker.sync_batch())
    db_session.expire_all()
    row = db_session.query(Event).filter(Event.event_id == "always-fail").one()
    assert row.status == "failed"


def test_idempotent_second_sync_noop(db_session):
    base = datetime(2026, 9, 4, 12, 0, 0)
    _insert(
        db_session,
        event_id="once",
        event_type="session_report_snapshot",
        created_at=base,
        payload={"event_id": "once", "event_type": "session_report_snapshot"},
    )
    client = FakeClient()
    worker = SyncWorker(client=client)
    worker.retry_backoff = 0
    asyncio.run(worker.sync_batch())
    asyncio.run(worker.sync_batch())
    assert len(client.sent) == 1


def test_outbox_lane_stats(db_session):
    base = datetime(2026, 9, 5, 13, 0, 0)
    _insert(db_session, event_id="s1", event_type="class_session_upsert", created_at=base)
    _insert(db_session, event_id="c1", event_type="climate_window", created_at=base)
    _insert(db_session, event_id="e1", event_type="engagement_window", created_at=base)
    _insert(db_session, event_id="x1", event_type="weird_custom", created_at=base)
    stats = EventRepository(db_session).get_outbox_lane_stats()
    assert stats["product_pending"] == 1
    assert stats["telemetry_pending"] == 2
    assert stats["ignored_pending"] == 1
