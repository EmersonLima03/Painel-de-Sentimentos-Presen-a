"""Testes da integração LXP Attendance Simulator (homolog) — sem TRI."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest

from app.integrations.attendance_lxp import (
    CONTRACT_VERSION,
    LXP_ATTENDANCE_EVENT_TYPE,
    LxpAttendanceClient,
    maybe_enqueue_lxp_attendance_from_checkin,
    resolve_external_student_id,
)
from app.sync.outbox_contract import classify_outbox_lane
from app.sync.worker import SyncWorker


class FakeLxpClient:
    def __init__(self, *, fail_once: bool = False, fail_always: bool = False):
        self.sent: List[Dict[str, Any]] = []
        self.fail_once = fail_once
        self.fail_always = fail_always
        self._failed = False

    def configured(self) -> bool:
        return True

    async def send_attendance_event(self, payload: Dict[str, Any]) -> bool:
        if self.fail_always:
            return False
        if self.fail_once and not self._failed:
            self._failed = True
            return False
        self.sent.append(payload)
        return True


def test_outbox_lane_lxp():
    assert classify_outbox_lane("lxp_attendance_event") == "lxp"
    assert classify_outbox_lane("attendance_checkin") == "telemetry"
    assert classify_outbox_lane("class_session_upsert") == "product"


def test_resolve_external_student_defaults():
    assert resolve_external_student_id("p01") == "ext-stu-001"
    assert resolve_external_student_id("anon-xyz") is None


def test_enqueue_lxp_attendance_idempotent(db_session, monkeypatch):
    from app.config import get_settings, reload_settings

    reload_settings()
    settings = get_settings()
    monkeypatch.setattr(settings, "module_lxp_mode", "simulator")
    monkeypatch.setattr(settings, "lxp_external_lesson_id", "lesson-8b-math-50")

    event = {
        "event_id": "chk-001",
        "student_id": "p01",
        "session_id": "sess-1",
        "timestamp": 1700000000,
        "device_id": "edge-test",
    }
    assert maybe_enqueue_lxp_attendance_from_checkin(event) is True
    assert maybe_enqueue_lxp_attendance_from_checkin(event) is False  # same outbox event_id

    from app.db.models import Event

    rows = db_session.query(Event).filter(Event.event_type == LXP_ATTENDANCE_EVENT_TYPE).all()
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    assert payload["lesson_id"] == "lesson-8b-math-50"
    assert payload["student_id"] == "ext-stu-001"
    assert payload["attendance"] == "present"
    assert payload["contract_version"] == CONTRACT_VERSION


def test_skip_anonymous_and_unmapped(monkeypatch):
    from app.config import get_settings, reload_settings

    reload_settings()
    settings = get_settings()
    monkeypatch.setattr(settings, "module_lxp_mode", "simulator")
    monkeypatch.setattr(settings, "lxp_external_lesson_id", "lesson-8b-math-50")
    assert maybe_enqueue_lxp_attendance_from_checkin({"student_id": "", "event_id": "e1"}) is False
    assert (
        maybe_enqueue_lxp_attendance_from_checkin(
            {"student_id": "anon-1", "event_id": "e2", "session_id": "s"}
        )
        is False
    )

def test_sync_worker_routes_lxp(db_session):
    from app.db.models import Event

    eid = "lxp-att:chk-xyz"
    payload = {
        "event_type": LXP_ATTENDANCE_EVENT_TYPE,
        "event_id": eid,
        "lesson_id": "lesson-8b-math-50",
        "student_id": "ext-stu-001",
        "attendance": "present",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "sentimentos",
        "contract_version": CONTRACT_VERSION,
    }
    db_session.add(
        Event(
            event_id=eid,
            event_type=LXP_ATTENDANCE_EVENT_TYPE,
            payload_json=json.dumps(payload),
            status="pending",
            retries=0,
        )
    )
    db_session.commit()

    fake = FakeLxpClient()
    worker = SyncWorker(lxp_client=fake)  # type: ignore[arg-type]
    asyncio.run(worker.sync_batch())

    assert len(fake.sent) == 1
    row = db_session.query(Event).filter(Event.event_id == eid).one()
    assert row.status == "sent"


def test_sync_worker_retry_then_ok(db_session):
    from app.db.models import Event

    eid = "lxp-att:retry-1"
    payload = {
        "event_type": LXP_ATTENDANCE_EVENT_TYPE,
        "event_id": eid,
        "lesson_id": "lesson-8b-math-50",
        "student_id": "ext-stu-001",
        "attendance": "present",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "sentimentos",
    }
    db_session.add(
        Event(
            event_id=eid,
            event_type=LXP_ATTENDANCE_EVENT_TYPE,
            payload_json=json.dumps(payload),
            status="pending",
            retries=0,
        )
    )
    db_session.commit()
    fake = FakeLxpClient(fail_once=True)
    worker = SyncWorker(lxp_client=fake)  # type: ignore[arg-type]
    worker.retry_attempts = 3
    worker.retry_backoff = 0
    asyncio.run(worker.sync_batch())
    row = db_session.query(Event).filter(Event.event_id == eid).one()
    assert row.status in ("pending", "sent")
    asyncio.run(worker.sync_batch())
    db_session.refresh(row)
    assert row.status == "sent"
    assert len(fake.sent) == 1


@pytest.mark.asyncio
async def test_lxp_client_rejects_without_config():
    client = LxpAttendanceClient(base_url="", token="")
    assert client.configured() is False
    assert await client.send_attendance_event({"event_id": "x"}) is False
