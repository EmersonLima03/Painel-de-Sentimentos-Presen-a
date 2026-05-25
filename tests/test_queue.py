"""Testes de fila de eventos."""

import json
import pytest
from app.db.init_db import init_database, get_session
from app.db.repo import EventRepository
from app.utils.ids import generate_event_id


@pytest.fixture
def db_session():
    """Fixture para sessão de banco de dados."""
    init_database()
    session = get_session()
    yield session
    session.close()


def test_create_event(db_session):
    """Testa criação de evento."""
    repo = EventRepository(db_session)
    
    event_id = generate_event_id()
    payload = {
        "event_id": event_id,
        "event_type": "attendance_checkin",
        "student_id": "12345"
    }
    
    event = repo.create_event(
        event_id=event_id,
        event_type="attendance_checkin",
        payload_json=json.dumps(payload)
    )
    
    assert event is not None
    assert event.event_id == event_id
    assert event.status == "pending"


def test_get_pending_events(db_session):
    """Testa busca de eventos pendentes."""
    repo = EventRepository(db_session)
    
    # Criar alguns eventos
    for i in range(3):
        event_id = generate_event_id()
        payload = {"event_id": event_id, "test": i}
        repo.create_event(
            event_id=event_id,
            event_type="test",
            payload_json=json.dumps(payload)
        )
    
    # Buscar pendentes
    pending = repo.get_pending_events(limit=10)
    assert len(pending) >= 3
    
    # Todos devem estar pendentes
    for event in pending:
        assert event.status == "pending"


def test_mark_sent(db_session):
    """Testa marcação de evento como enviado."""
    repo = EventRepository(db_session)
    
    event_id = generate_event_id()
    payload = {"event_id": event_id}
    repo.create_event(
        event_id=event_id,
        event_type="test",
        payload_json=json.dumps(payload)
    )
    
    # Marcar como enviado
    repo.mark_sent(event_id)
    
    # Verificar
    pending = repo.get_pending_events(limit=10)
    event_ids = [e.event_id for e in pending]
    assert event_id not in event_ids


def test_event_stats(db_session):
    """Testa estatísticas de eventos."""
    repo = EventRepository(db_session)
    
    # Criar eventos
    for i in range(5):
        event_id = generate_event_id()
        repo.create_event(
            event_id=event_id,
            event_type="test",
            payload_json=json.dumps({"test": i})
        )
    
    # Marcar alguns como enviados
    pending = repo.get_pending_events(limit=10)
    if len(pending) >= 2:
        repo.mark_sent(pending[0].event_id)
        repo.mark_sent(pending[1].event_id)
    
    # Verificar stats
    stats = repo.get_stats()
    assert stats["total"] >= 5
    assert stats["pending"] >= 3
    assert stats["sent"] >= 2
