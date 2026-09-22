"""Fase 6 — contexto operacional da aula (ao redor do TRI)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def clean_lxp_env(monkeypatch):
    monkeypatch.delenv("LXP_EXTERNAL_LESSON_ID", raising=False)
    monkeypatch.delenv("LXP_STUDENT_MAP_JSON", raising=False)
    from app.config import reload_settings

    reload_settings()
    yield
    reload_settings()


def test_resolve_lesson_prefers_session_metadata_over_env(db_session, monkeypatch, clean_lxp_env):
    from app.config import get_settings
    from app.db.models import ClassSession
    from app.integrations.attendance_lxp import resolve_external_lesson_id

    settings = get_settings()
    monkeypatch.setattr(settings, "lxp_external_lesson_id", "lesson-FROM-ENV")

    sid = "fase6-lesson-meta-001"
    row = ClassSession(
        session_id=sid,
        school_id="1",
        room_id="r1",
        device_id="dev",
        title="Aula",
        status="active",
        metadata_json=json.dumps(
            {
                "external_lesson_id": "lesson-FROM-SESSION",
                "lesson_context": {
                    "lesson_occurrence_id": "occ-1",
                    "external_lesson_id": "lesson-FROM-SESSION",
                    "class_group_name": "8B",
                },
            }
        ),
    )
    db_session.add(row)
    db_session.commit()

    assert resolve_external_lesson_id(sid) == "lesson-FROM-SESSION"


def test_resolve_student_prefers_roster_map(db_session, monkeypatch, clean_lxp_env):
    from app.db.models import ClassSession
    from app.integrations.attendance_lxp import resolve_external_student_id

    sid = "fase6-roster-001"
    row = ClassSession(
        session_id=sid,
        school_id="1",
        room_id="r1",
        device_id="dev",
        title="Aula",
        status="active",
        metadata_json=json.dumps(
            {
                "lesson_context": {
                    "lesson_occurrence_id": "occ-2",
                    "student_map": {"p99": "ext-stu-999"},
                }
            }
        ),
    )
    db_session.add(row)
    db_session.commit()

    assert resolve_external_student_id("p99", session_id=sid) == "ext-stu-999"
    assert resolve_external_student_id("p01", session_id=sid) == "ext-stu-001"  # seed fallback


def test_start_with_context_conflict_and_resume(db_session, monkeypatch, tmp_path, clean_lxp_env):
    from app.config import get_settings, reload_settings
    from app.services import lesson_context as lc

    monkeypatch.setattr(lc, "_cache_path", lambda: tmp_path / "today.json")
    settings = get_settings()
    monkeypatch.setattr(settings, "school_id", "1")
    monkeypatch.setattr(settings, "device_id", "edge-test")
    monkeypatch.setattr(settings, "cameras", [])

    body_a = {
        "lesson_occurrence_id": "11111111-1111-1111-1111-111111111111",
        "class_group_name": "8º B",
        "subject_name": "Matemática",
        "teacher_name": "Marcos",
        "scheduled_duration_minutes": 50,
        "external_lesson_id": "lesson-8b-math-50",
        "roster": [{"edge_student_key": "p01", "external_ref": "ext-stu-001"}],
    }
    r1 = lc.start_session_with_context(body_a)
    assert r1["ok"] is True
    assert r1["status"] == "started"
    sid1 = r1["session_id"]

    # mesma ocorrência → resume
    r2 = lc.start_session_with_context(body_a)
    assert r2["ok"] is True
    assert r2["status"] == "resumed"
    assert r2["session_id"] == sid1

    # outra ocorrência → conflito
    body_b = {
        **body_a,
        "lesson_occurrence_id": "22222222-2222-2222-2222-222222222222",
        "class_group_name": "9º A",
        "subject_name": "História",
    }
    r3 = lc.start_session_with_context(body_b)
    assert r3["ok"] is False
    assert r3["code"] == "conflict_active_session"
    assert "active_label" in r3 or "message" in r3

    reload_settings()


def test_start_with_context_supersedes_automatic_session(db_session, monkeypatch, tmp_path, clean_lxp_env):
    """Sessão automática (sem lesson_context) não deve bloquear aula formal."""
    from app.config import get_settings
    from app.db.models import ClassSession
    from app.db.repo import ClassSessionRepository
    from app.services import lesson_context as lc

    monkeypatch.setattr(lc, "_cache_path", lambda: tmp_path / "today.json")
    settings = get_settings()
    monkeypatch.setattr(settings, "school_id", "1")
    monkeypatch.setattr(settings, "device_id", "edge-test")
    monkeypatch.setattr(settings, "cameras", [])

    repo = ClassSessionRepository(db_session)
    auto_sid = "auto-session-no-context-001"
    repo.create_session(
        session_id=auto_sid,
        school_id="1",
        room_id="DEV",
        device_id="edge-test",
        title="Sessão automática",
    )
    assert db_session.query(ClassSession).filter(ClassSession.session_id == auto_sid).one().status == "active"

    body = {
        "lesson_occurrence_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "class_group_name": "Turma Teste 1",
        "subject_name": "Matemática",
        "external_lesson_id": "lesson-8b-math-50",
        "scheduled_duration_minutes": 50,
        "roster": [{"edge_student_key": "p01", "external_ref": "ext-stu-001"}],
    }
    r = lc.start_session_with_context(body)
    assert r["ok"] is True
    assert r["status"] == "started"
    assert r["session_id"] != auto_sid
    assert r["context"]["lesson_occurrence_id"] == body["lesson_occurrence_id"]

    ended = db_session.query(ClassSession).filter(ClassSession.session_id == auto_sid).one()
    assert ended.status == "ended"


def test_reopen_creates_new_session(db_session, monkeypatch, tmp_path, clean_lxp_env):
    from app.db.models import ClassSession
    from app.db.repo import ClassSessionRepository
    from app.services import lesson_context as lc

    monkeypatch.setattr(lc, "_cache_path", lambda: tmp_path / "today.json")
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "school_id", "1")
    monkeypatch.setattr(settings, "device_id", "edge-test")
    monkeypatch.setattr(settings, "cameras", [])

    occ = "33333333-3333-3333-3333-333333333333"
    body = {
        "lesson_occurrence_id": occ,
        "class_group_name": "8º B",
        "subject_name": "Matemática",
        "external_lesson_id": "lesson-8b-math-50",
        "scheduled_duration_minutes": 50,
        "roster": [],
    }
    r1 = lc.start_session_with_context(body)
    assert r1["ok"]
    sid1 = r1["session_id"]

    repo = ClassSessionRepository(db_session)
    assert repo.end_session(sid1)

    r2 = lc.start_session_with_context(body)
    assert r2["ok"] is True
    assert r2["status"] == "started"
    assert r2["reopen"] is True
    assert r2["session_id"] != sid1
    assert r2.get("warning")


def test_day_cache_roundtrip(tmp_path, monkeypatch):
    from app.services import lesson_context as lc

    monkeypatch.setattr(lc, "_cache_path", lambda: tmp_path / "today.json")
    saved = lc.save_day_cache(
        [{"id": "occ-x", "class_group_name": "8B", "external_lesson_id": "lesson-8b-math-50"}]
    )
    assert Path(tmp_path / "today.json").exists()
    assert saved.get("cached_at")
    loaded = lc.load_day_cache()
    assert len(loaded["occurrences"]) == 1
    assert lc.get_cached_occurrence("occ-x")["external_lesson_id"] == "lesson-8b-math-50"


def test_enqueue_class_session_includes_occurrence_fields(db_session, monkeypatch):
    from app.db.models import Event
    from app.services.session_persistence import enqueue_class_session_upsert
    import time

    enqueue_class_session_upsert(
        session_id="fase6-upsert-1",
        status="active",
        started_at=time.time(),
        title="8B · Mat",
        external_lesson_id="lesson-8b-math-50",
        lesson_occurrence_id="44444444-4444-4444-4444-444444444444",
        class_group_id="55555555-5555-5555-5555-555555555555",
        subject_id="66666666-6666-6666-6666-666666666666",
        scheduled_duration_minutes=50,
        scheduled_start_at="2026-09-18T11:00:00+00:00",
    )
    row = db_session.query(Event).filter(Event.event_id == "session:fase6-upsert-1:active").first()
    assert row is not None
    payload = json.loads(row.payload_json)
    sess = payload["session"]
    assert sess["external_lesson_id"] == "lesson-8b-math-50"
    assert sess["lesson_occurrence_id"] == "44444444-4444-4444-4444-444444444444"
    assert sess["scheduled_duration_minutes"] == 50
    assert sess["class_group_id"] == "55555555-5555-5555-5555-555555555555"
