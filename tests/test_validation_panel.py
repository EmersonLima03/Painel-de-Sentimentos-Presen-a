"""Testes do painel de validação controlada — DB isolado, sem tocar presença."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.validation.db import init_validation_db, validation_db_path
from app.validation.scenarios import SCENARIOS, list_scenarios
from app.validation.service import ValidationService, evaluate_step, _safe


@pytest.fixture()
def val_db(tmp_path, monkeypatch):
    db = tmp_path / "validation_test.db"
    monkeypatch.setenv("VALIDATION_DB_PATH", str(db))
    from app.config import reload_settings
    from app.validation.service import reset_validation_service

    reload_settings()
    from app.config import get_settings

    s = get_settings()
    object.__setattr__(s, "validation_db_path", str(db))
    reset_validation_service()
    init_validation_db()
    assert db.resolve() != Path("data/dulino_edge.db").resolve()
    yield db
    reset_validation_service()


def test_scenarios_catalog():
    keys = {s["key"] for s in list_scenarios()}
    assert "neutral_15s" in keys
    assert "phone_hand_prolonged" in keys
    assert "leave_frame" in keys
    assert len(SCENARIOS) >= 20


def test_create_session_and_steps(val_db):
    svc = ValidationService()
    sess = svc.create_session(operator="tester", camera_id="cam-web", student_id="p01")
    assert sess["id"]
    assert sess["student_id"] == "p01"
    assert len(sess["steps"]) == len(SCENARIOS)
    assert Path(val_db).exists()
    assert "dulino_edge" not in str(val_db)


def test_start_sample_finish_pass(val_db, monkeypatch):
    from app.api import v1 as api_v1

    # fake live snapshot
    api_v1._live_state.update(
        {
            "camera_id": "cam-web",
            "tracks": [
                {
                    "track_id": "p01",
                    "student_id": "p01",
                    "identity_confidence": 0.9,
                    "observation_quality": {"status": "observable", "overall_score": 0.9},
                    "facial_features": {
                        "status": "available",
                        "yaw": 0.0,
                        "pitch": 0.05,
                        "roll": 0.0,
                        "average_eye_openness": 0.3,
                    },
                    "expression": {"status": "available", "sample_count": 3, "confidence": 0.7, "smoothed_state": "predominantly_neutral"},
                    "visual_attention": {"state": "high", "confidence": 0.8, "duration_seconds": 5},
                    "drowsiness": {"state": "none", "confidence": 0.1},
                    "phone": {"status": "available", "state": "not_detected"},
                    "latencies_ms": {"total_analytics": 20.0, "landmarks": 10.0, "expression": 5.0},
                    "active_events": [],
                }
            ],
            "visible_people": 1,
            "recognized_people": 1,
        }
    )
    svc = ValidationService()
    sess = svc.create_session(operator="t", camera_id="cam-web", student_id="p01")
    step = next(s for s in sess["steps"] if s["scenario_key"] == "neutral_15s")
    started = svc.start_step(sess["id"], step_id=step["id"])
    assert started["started_at"]
    svc.record_sample(sess["id"], step["id"])
    svc.record_sample(sess["id"], step["id"])
    finished = svc.finish_step(sess["id"], step["id"], observation="ok")
    assert finished["result"] in ("PASS", "INCONCLUSIVO", "FAIL")
    assert finished["duration_real"] is not None
    assert finished["sample_count"] >= 2


def test_evaluate_fail_confirmed_phone():
    scenario = {
        "key": "phone_none",
        "expected": {"phone_state": ["not_detected"], "phone_never_confirmed": True, "presence_intact": True},
    }
    samples = [
        {
            "track": {
                "student_id": "p01",
                "phone": {"status": "available", "state": "confirmed_phone_interaction"},
                "observation_quality": {"status": "observable"},
            }
        }
    ]
    result, ev = evaluate_step(
        scenario=scenario,
        samples=samples,
        snap_start={},
        snap_end={},
        track_start={"student_id": "p01"},
        track_end={"student_id": "p01"},
    )
    assert result == "FAIL"


def test_evaluate_inconclusive_no_samples():
    scenario = {"key": "x", "expected": {"quality_status": ["observable"]}}
    result, ev = evaluate_step(
        scenario=scenario,
        samples=[],
        snap_start={},
        snap_end={},
        track_start=None,
        track_end=None,
    )
    assert result == "INCONCLUSIVO"


def test_safe_strips_secrets():
    raw = {"embeddings": [1, 2], "frame": "x", "student_id": "p01", "rtsp_url": "secret"}
    clean = _safe(raw)
    assert "embeddings" not in clean
    assert "frame" not in clean
    assert "rtsp_url" not in clean
    assert clean["student_id"] == "p01"


def test_report_json_csv(val_db, monkeypatch):
    from app.api import v1 as api_v1

    api_v1._live_state["tracks"] = [
        {
            "track_id": "p01",
            "student_id": "p01",
            "observation_quality": {"status": "observable", "overall_score": 0.8},
            "facial_features": {"status": "available", "yaw": -0.2, "pitch": 0.1, "average_eye_openness": 0.25},
            "expression": {"status": "available", "sample_count": 2, "confidence": 0.6},
            "visual_attention": {"state": "moderate", "confidence": 0.5},
            "drowsiness": {"state": "none"},
            "phone": {"status": "available", "state": "not_detected"},
            "latencies_ms": {"total_analytics": 15},
        }
    ]
    svc = ValidationService()
    sess = svc.create_session(operator="t", camera_id="cam-web")
    step = sess["steps"][0]
    svc.start_step(sess["id"], step_id=step["id"])
    svc.finish_step(sess["id"], step["id"])
    report = svc.build_report(sess["id"])
    assert "counts" in report
    assert "overall_result" in report
    csv_text = svc.report_csv(sess["id"])
    assert "scenario_key" in csv_text
    assert "PASS" in csv_text or "FAIL" in csv_text or "INCONCLUSIVO" in csv_text


def test_api_validation_endpoints(val_db, monkeypatch):
    monkeypatch.setenv("RUNTIME_MODE", "rtsp")
    monkeypatch.setenv("API_AUTH_TOKEN", "")
    from app.config import reload_settings

    reload_settings()
    from app.main import app

    client = TestClient(app)
    r = client.post(
        "/api/v1/validation/sessions",
        json={"operator": "qa", "camera_id": "cam-web"},
    )
    assert r.status_code == 200
    sess = r.json()
    assert sess["id"]
    sid = sess["id"]
    step_id = sess["steps"][0]["id"]
    r2 = client.post(f"/api/v1/validation/sessions/{sid}/steps/start", json={"step_id": step_id})
    assert r2.status_code == 200
    r3 = client.post(f"/api/v1/validation/sessions/{sid}/steps/{step_id}/sample")
    assert r3.status_code == 200
    r4 = client.post(
        f"/api/v1/validation/sessions/{sid}/steps/{step_id}/finish",
        json={"observation": "teste"},
    )
    assert r4.status_code == 200
    assert r4.json()["result"] in ("PASS", "FAIL", "INCONCLUSIVO")
    r5 = client.get(f"/api/v1/validation/sessions/{sid}/report")
    assert r5.status_code == 200
    body = r5.json()
    assert "embeddings" not in json.dumps(body)
    assert "frame" not in body
    r6 = client.get(f"/api/v1/validation/sessions/{sid}/report.csv")
    assert r6.status_code == 200
    assert "text/csv" in r6.headers.get("content-type", "")


def test_validation_does_not_touch_presence_db(val_db):
    # path isolation
    p = validation_db_path()
    assert p.name != "dulino_edge.db"
    assert "validation" in str(p).lower() or "tmp" in str(p).lower() or "test" in str(p).lower()
