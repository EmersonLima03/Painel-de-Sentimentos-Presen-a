"""Testes do modo demo, API v1, LXP retry/DLQ, sonolência/atenção, E2E simulado."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analytics.attention_drowsiness import evaluate_apparent_drowsiness, evaluate_visual_attention
from app.integrations.lxp import LXPEvent, LXPOutbox, MockLXPClient, new_event_id
from app.vision.person_phone import PersonPhoneAssociator
from app.vision.frame_source import DemoFrameSource


PRODUCTION_DB = Path("data/dulino_edge.db").resolve()


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_MODE", "demo")
    monkeypatch.setenv("API_AUTH_TOKEN", "")
    demo_db = tmp_path / "dulino_edge_demo.db"
    monkeypatch.setenv("DEMO_DB_PATH", str(demo_db))
    # Isola banco prod nos testes
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "prod_isolated.db"))

    from app.config import reload_settings
    from app.db.init_db import reset_db_singleton
    from app.demo.engine import reset_demo_engine_for_tests, get_demo_engine

    reset_db_singleton()
    reload_settings()
    reset_demo_engine_for_tests()
    eng = get_demo_engine()
    eng.demo_db_path = str(demo_db)
    eng._init_demo_db()
    eng.control_update(reset=True, playing=False)

    from app.main import app

    with TestClient(app) as client:
        # Garante que o engine do lifespan aponta ao DB temporário
        eng.demo_db_path = str(demo_db)
        eng._init_demo_db()
        yield client, eng, demo_db

    reset_demo_engine_for_tests()
    reset_db_singleton()


def test_phone_visible_is_not_use():
    assoc = PersonPhoneAssociator(minimum_interaction_seconds=5.0, probable_seconds=12.0)
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    # celular longe do tronco / mesa
    phones_desk = [(180.0, 180.0, 20.0, 30.0, 0.9)]
    s = assoc.update(now=0.0, person_tracks=people, phone_boxes=phones_desk)[0]
    assert s.interaction_level in ("none", "phone_visible", "phone_near_person", "possible", "probable")
    assert s.interaction_level != "confirmed"
    # visível ≠ uso confirmado
    assert "confirmed" not in s.interaction_level


def test_brief_eyes_closed_no_persistent_drowsiness():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=2.0,
        head_pitch=0.1,
        sample_count=10,
        observation_quality=0.9,
        min_duration_seconds=8.0,
    )
    assert st.state == "none"


def test_eyes_only_long_duration_probable():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=30.0,
        head_pitch=0.1,
        sample_count=20,
        observation_quality=0.9,
        min_duration_seconds=30.0,
    )
    assert st.state == "probable"


def test_low_quality_drowsiness_inconclusive():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=20.0,
        head_pitch=0.4,
        sample_count=20,
        observation_quality=0.2,
    )
    assert st.state == "inconclusive"


def test_attention_ignores_negative_expression_concept():
    # expressão negativa não é parâmetro — score baseado em pose/celular/qualidade
    a = evaluate_visual_attention(head_yaw=0.0, observation_quality=0.9)
    assert a.state == "high"
    b = evaluate_visual_attention(observation_quality=0.2)
    assert b.state == "inconclusive"


def test_demo_frame_source_deterministic():
    src = DemoFrameSource(fps=100)
    assert src.open()
    f1 = src.read()
    assert f1 is not None and f1.is_simulated
    src.close()


def test_lxp_retry_and_dead_letter(tmp_path):
    import asyncio

    client = MockLXPClient(fail_until=99)
    box = LXPOutbox(
        path=str(tmp_path / "o.jsonl"),
        dead_letter_path=str(tmp_path / "d.jsonl"),
        max_retries=3,
        base_backoff_seconds=0.001,
    )
    ev = LXPEvent("attendance_checkin", new_event_id(), "s1", {"student_id": "x"})
    assert box.enqueue(ev)

    async def run():
        for i in range(5):
            await box.flush(client, now=time.time() + i * 10)

    asyncio.run(run())
    assert any(r.get("status") == "dead" for r in box.dead_letters()) or len(box.dead_letters()) >= 1


def test_demo_e2e_eight_tracks_and_no_prod_db(demo_client):
    client, eng, demo_db = demo_client
    prod_mtime_before = PRODUCTION_DB.stat().st_mtime if PRODUCTION_DB.exists() else None

    eng.control_update(seek=70.0, playing=False)
    r = client.get("/api/v1/live/tracks")
    assert r.status_code == 200
    data = r.json()
    assert data["is_simulated"] is True
    assert data["runtime_mode"] == "demo"
    assert len(data["tracks"]) == 8

    summary = client.get("/api/v1/live/classroom-summary").json()
    assert summary["recognized_people"] == 8

    eng.control_update(seek=190.0)
    events = client.get("/api/v1/review/events").json()["events"]
    assert any(e["event_type"] == "phone_visible" for e in events)

    eng.control_update(seek=500.0)
    events = client.get("/api/v1/review/events").json()["events"]
    assert any(e["event_type"] == "apparent_drowsiness" for e in events)
    drowsy = next(e for e in events if e["event_id"] == "demo-drowsiness")
    patch = client.patch(
        f"/api/v1/review/events/{drowsy['event_id']}",
        json={"status": "confirmed", "notes": "demo review"},
    )
    assert patch.status_code == 200
    assert patch.json()["event"]["review_status"] == "confirmed"

    report = client.get(f"/api/v1/sessions/{eng.control.session_id}/summary").json()
    assert report["is_simulated"] is True
    assert "limitations" in report

    flush = client.post("/api/v1/demo/lxp/flush")
    assert flush.status_code == 200

    # Banco demo escrito
    assert demo_db.exists()
    conn = sqlite3.connect(demo_db)
    n = conn.execute("SELECT COUNT(*) FROM demo_behavioral_events").fetchone()[0]
    conn.close()
    assert n >= 1

    # Produção não tocada por este fluxo
    if prod_mtime_before is not None:
        assert PRODUCTION_DB.stat().st_mtime == prod_mtime_before
    # path do engine nunca é dulino_edge.db
    assert Path(eng.demo_db_path).resolve().name != "dulino_edge.db"


def test_demo_api_system_and_ws(demo_client):
    client, eng, _ = demo_client
    assert client.get("/api/v1/system/health").json()["status"] == "ok"
    assert client.get("/api/v1/system/models").json()["is_simulated"] is True
    assert client.get("/api/v1/system/configuration").json()["runtime_mode"] == "demo"
    with client.websocket_connect("/api/v1/ws/live") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "system_status"
        assert msg.get("is_simulated") is True or msg.get("runtime_mode") == "demo"


def test_identity_binding_eight_people_demo(demo_client):
    client, eng, _ = demo_client
    eng.control_update(seek=80.0)
    snap = eng.snapshot()
    person_ids = [b["person_track_id"] for b in snap["bindings"]]
    face_ids = [b["face_track_id"] for b in snap["bindings"]]
    students = [b["student_id"] for b in snap["bindings"]]
    assert len(person_ids) == len(set(person_ids)) == 8
    assert len(face_ids) == len(set(face_ids)) == 8
    assert len(students) == len(set(students)) == 8
