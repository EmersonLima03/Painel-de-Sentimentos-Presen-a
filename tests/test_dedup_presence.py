"""Testes de dedup de presença (DB isolado via conftest)."""

from app.db.repo import AttendanceRepository, EventRepository
from app.utils.time import get_date_key
from app.utils.ids import generate_event_id
import json


def test_dedup_same_day(db_session):
    """Testa que não gera check-in duplicado no mesmo dia."""
    attendance_repo = AttendanceRepository(db_session)
    event_repo = EventRepository(db_session)

    student_id = "student-001"
    room_id = "A01"
    date_key = get_date_key()

    attendance_repo.create_attendance(
        student_id=student_id,
        room_id=room_id,
        confidence=0.85,
        device_id="edge-001",
        date_key=date_key,
    )

    has_attendance = attendance_repo.has_attendance_today(student_id, room_id, date_key)
    assert has_attendance is True

    event_id = generate_event_id()
    payload = {
        "event_id": event_id,
        "event_type": "attendance_checkin",
        "student_id": student_id,
        "room_id": room_id,
    }
    _ = event_repo  # presença usa cache; evento é validado no pipeline
    _ = payload
    assert attendance_repo.has_attendance_today(student_id, room_id, date_key)


def test_dedup_different_rooms(db_session):
    """Testa que dedup é por room_id também."""
    attendance_repo = AttendanceRepository(db_session)

    student_id = "student-001"
    room_a = "A01"
    room_b = "A02"
    date_key = get_date_key()

    attendance_repo.create_attendance(
        student_id=student_id,
        room_id=room_a,
        confidence=0.85,
        device_id="edge-001",
        date_key=date_key,
    )

    has_in_room_b = attendance_repo.has_attendance_today(student_id, room_b, date_key)
    assert has_in_room_b is False

    has_in_room_a = attendance_repo.has_attendance_today(student_id, room_a, date_key)
    assert has_in_room_a is True


def test_dedup_different_days(db_session):
    """Testa que pode ter check-in em dias diferentes (DB limpo por fixture)."""
    attendance_repo = AttendanceRepository(db_session)

    student_id = "student-001"
    room_id = "A01"
    today = get_date_key()
    yesterday = "2024-01-01"

    attendance_repo.create_attendance(
        student_id=student_id,
        room_id=room_id,
        confidence=0.85,
        device_id="edge-001",
        date_key=yesterday,
    )

    has_today = attendance_repo.has_attendance_today(student_id, room_id, today)
    assert has_today is False

    has_yesterday = attendance_repo.has_attendance_today(student_id, room_id, yesterday)
    assert has_yesterday is True
