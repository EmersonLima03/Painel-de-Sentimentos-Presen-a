"""Testes de fila de eventos (DB isolado via conftest)."""

import json
from app.db.repo import EventRepository
from app.utils.ids import generate_event_id


def test_create_event(db_session):
    """Testa criação de evento."""
    repo = EventRepository(db_session)

    event_id = generate_event_id()
    payload = {
        "event_id": event_id,
        "event_type": "attendance_checkin",
        "student_id": "12345",
    }

    event = repo.create_event(
        event_id=event_id,
        event_type="attendance_checkin",
        payload_json=json.dumps(payload),
    )

    assert event is not None
    assert event.event_id == event_id
    assert event.status == "pending"


def test_get_pending_events(db_session):
    """Testa obtenção de eventos pendentes."""
    repo = EventRepository(db_session)

    for i in range(3):
        event_id = generate_event_id()
        payload = {"event_id": event_id, "event_type": "attendance_checkin"}
        repo.create_event(
            event_id=event_id,
            event_type="attendance_checkin",
            payload_json=json.dumps(payload),
        )

    pending = repo.get_pending_events(limit=10)
    assert len(pending) >= 3
    assert all(e.status == "pending" for e in pending)


def test_mark_sent(db_session):
    """Testa marcação de evento como enviado."""
    repo = EventRepository(db_session)

    event_id = generate_event_id()
    repo.create_event(
        event_id=event_id,
        event_type="attendance_checkin",
        payload_json=json.dumps({"event_id": event_id}),
    )

    repo.mark_sent(event_id)
    pending = repo.get_pending_events(limit=100)
    assert not any(e.event_id == event_id for e in pending)


def test_event_stats(db_session):
    """Testa estatísticas de eventos."""
    repo = EventRepository(db_session)

    event_id = generate_event_id()
    repo.create_event(
        event_id=event_id,
        event_type="attendance_checkin",
        payload_json=json.dumps({"event_id": event_id}),
    )
    stats_before = repo.get_stats()
    assert stats_before.get("pending", 0) >= 1

    repo.mark_sent(event_id)
    stats_after = repo.get_stats()
    assert stats_after.get("sent", 0) >= 1
