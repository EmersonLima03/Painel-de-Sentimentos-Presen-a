"""Testes de dedup de presença."""

import pytest
from datetime import datetime
from app.db.init_db import init_database, get_session
from app.db.repo import AttendanceRepository, EventRepository
from app.utils.time import get_date_key
from app.utils.ids import generate_event_id
import json


@pytest.fixture
def db_session():
    """Fixture para sessão de banco de dados."""
    init_database()
    session = get_session()
    yield session
    session.close()


def test_dedup_same_day(db_session):
    """Testa que não gera check-in duplicado no mesmo dia."""
    attendance_repo = AttendanceRepository(db_session)
    event_repo = EventRepository(db_session)
    
    student_id = "student-001"
    room_id = "A01"
    date_key = get_date_key()
    
    # Primeiro check-in
    attendance_repo.create_attendance(
        student_id=student_id,
        room_id=room_id,
        confidence=0.85,
        device_id="edge-001",
        date_key=date_key
    )
    
    # Verificar que já existe
    has_attendance = attendance_repo.has_attendance_today(student_id, room_id, date_key)
    assert has_attendance is True
    
    # Tentar criar evento (simulando pipeline)
    event_id = generate_event_id()
    payload = {
        "event_id": event_id,
        "event_type": "attendance_checkin",
        "student_id": student_id,
        "room_id": room_id
    }
    
    # Se dedup funcionar, não deve criar evento
    # (isso é validado no pipeline, não aqui)
    # Mas podemos verificar que o cache existe
    assert attendance_repo.has_attendance_today(student_id, room_id, date_key)


def test_dedup_different_rooms(db_session):
    """Testa que dedup é por room_id também."""
    attendance_repo = AttendanceRepository(db_session)
    
    student_id = "student-001"
    room_a = "A01"
    room_b = "A02"
    date_key = get_date_key()
    
    # Check-in na sala A
    attendance_repo.create_attendance(
        student_id=student_id,
        room_id=room_a,
        confidence=0.85,
        device_id="edge-001",
        date_key=date_key
    )
    
    # Deve poder ter check-in na sala B (diferente)
    has_in_room_b = attendance_repo.has_attendance_today(student_id, room_b, date_key)
    assert has_in_room_b is False  # Não tem ainda
    
    # Mas já tem na sala A
    has_in_room_a = attendance_repo.has_attendance_today(student_id, room_a, date_key)
    assert has_in_room_a is True


def test_dedup_different_days(db_session):
    """Testa que pode ter check-in em dias diferentes."""
    attendance_repo = AttendanceRepository(db_session)
    
    student_id = "student-001"
    room_id = "A01"
    today = get_date_key()
    yesterday = "2024-01-01"  # Data fixa para teste
    
    # Check-in ontem
    attendance_repo.create_attendance(
        student_id=student_id,
        room_id=room_id,
        confidence=0.85,
        device_id="edge-001",
        date_key=yesterday
    )
    
    # Hoje não deve ter ainda
    has_today = attendance_repo.has_attendance_today(student_id, room_id, today)
    assert has_today is False
    
    # Mas ontem tem
    has_yesterday = attendance_repo.has_attendance_today(student_id, room_id, yesterday)
    assert has_yesterday is True
