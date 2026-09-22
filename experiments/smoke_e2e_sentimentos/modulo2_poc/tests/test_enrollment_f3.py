"""F3 tests — captura facial + óculos (hooks / frames), sem DB de produção."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

MODULO2 = Path(__file__).resolve().parents[1]
SCRIPTS = MODULO2 / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Enable test hooks before importing server module
os.environ["M2_POC_TEST_HOOKS"] = "1"

import enrollment_gestor_server as egs  # noqa: E402
from enrollment_gestor_server import build_app  # noqa: E402
from enrollment_pipeline import (  # noqa: E402
    CAMPAIGN_GALLERY,
    CAPTURE_STORE,
    process_frame_bgr,
)
from enrollment_store import EnrollmentStore, ROSTER_COMPLETED, ROSTER_IN_PROGRESS  # noqa: E402

# Force reload flag on already-imported module
egs.TEST_HOOKS = True

HMAC = "test-hmac-f3"
SCHOOL_ID = "escola_demo_presenca"
CLASS_ID = "turma_familia_lab"


@pytest.fixture()
def client(tmp_path: Path):
    store = EnrollmentStore(
        tmp_path / "f3.db",
        hmac_secret=HMAC,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
        rate_limit_max=100,
    )
    app = build_app(store)
    with TestClient(app) as c:
        c.store = store  # type: ignore[attr-defined]
        yield c


def _camp(client: TestClient) -> dict:
    return client.post(
        "/api/gestor/campaigns",
        json={"school_id": SCHOOL_ID, "class_group_id": CLASS_ID},
    ).json()


def _code(camp: dict, name: str) -> str:
    return next(r["claim_code"] for r in camp["claim_sheet"] if r["display_name"] == name)


def _session(client: TestClient, camp: dict, name: str = "Dulin") -> str:
    claim = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": _code(camp, name)},
    ).json()
    start = client.post(
        "/api/aluno/session/start", json={"session_token": claim["session_token"]}
    ).json()
    assert start["ok"] is True
    assert start["capture"]["phase"] == "front"
    return claim["session_token"]


def test_force_steps_no_glasses_completes(client: TestClient, tmp_path: Path):
    camp = _camp(client)
    token = _session(client, camp, "Dulin")
    for step in ("front", "lateral_right", "lateral_left", "validate"):
        r = client.post(
            "/api/aluno/session/test/force-step",
            json={"session_token": token, "step": step},
        )
        assert r.status_code == 200, r.text
    assert r.json()["capture"]["phase"] == "glasses_ask"
    g = client.post(
        "/api/aluno/session/glasses",
        json={"session_token": token, "uses_glasses": False},
    )
    assert g.status_code == 200
    assert g.json()["capture"]["completed"] is True
    prog = client.get(f"/api/gestor/campaigns/{camp['campaign_id']}/progress").json()
    by = {i["display_name"]: i["status"] for i in prog["items"]}
    assert by["Dulin"] == ROSTER_COMPLETED
    # TEMP gallery exists, not production
    meta_dirs = list((CAMPAIGN_GALLERY / camp["campaign_id"]).glob("*/enroll_meta.json"))
    assert meta_dirs
    meta = meta_dirs[0].read_text(encoding="utf-8")
    assert "product_db_written\": false" in meta.replace(" ", "") or '"product_db_written": false' in meta
    assert "reload_matcher_called\": false" in meta.replace(" ", "") or '"reload_matcher_called": false' in meta


def test_glasses_yes_extra_template(client: TestClient):
    camp = _camp(client)
    token = _session(client, camp, "Mae")
    for step in ("front", "lateral_right", "lateral_left", "validate"):
        client.post(
            "/api/aluno/session/test/force-step",
            json={"session_token": token, "step": step},
        )
    g = client.post(
        "/api/aluno/session/glasses",
        json={"session_token": token, "uses_glasses": True},
    )
    assert g.json()["capture"]["phase"] == "glasses_habitual"
    assert g.json()["capture"]["completed"] is False
    fin = client.post(
        "/api/aluno/session/test/force-step",
        json={"session_token": token, "step": "glasses_habitual"},
    )
    assert fin.json()["capture"]["completed"] is True
    steps = fin.json()["capture"]["sample_steps"]
    assert "glasses_habitual" in steps
    assert steps.count("front") == 1


def test_complete_blocked_if_incomplete(client: TestClient):
    camp = _camp(client)
    token = _session(client, camp)
    # Temporarily disable hooks gate
    egs.TEST_HOOKS = False
    try:
        r = client.post("/api/aluno/session/complete", json={"session_token": token})
        assert r.status_code == 400
        assert "incompleto" in r.json()["error"]
    finally:
        egs.TEST_HOOKS = True


def test_frame_no_face_ui_code(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Frame válido sem detecção de rosto → ui_code no_face.

    YuNet em JPEG sintético preto pode falhar (adjust) ou falso-positivo;
    o contrato sob teste é o ramo no_face do pipeline, não o detector.
    """
    camp = _camp(client)
    token = _session(client, camp)
    import cv2

    monkeypatch.setattr("enrollment_pipeline.detect_faces_yunet", lambda *a, **k: [])

    frame = np.zeros((480, 360, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    r = client.post(
        "/api/aluno/session/frame",
        files={"frame": ("f.jpg", buf.tobytes(), "image/jpeg")},
        data={"session_token": token},
    )
    assert r.status_code == 200
    assert r.json()["capture"]["ui_code"] == "no_face"
    assert r.json()["capture"]["completed"] is False


def test_multi_face_blocks(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    camp = _camp(client)
    token = _session(client, camp)

    def fake_detect(frame, score_th=0.7):
        # two strong faces
        return [
            {"x": 10, "y": 10, "w": 80, "h": 100, "face_score": 0.9, "det_score": 0.9, "landmarks": []},
            {"x": 200, "y": 10, "w": 80, "h": 100, "face_score": 0.9, "det_score": 0.9, "landmarks": []},
        ]

    monkeypatch.setattr("enrollment_pipeline.detect_faces_yunet", fake_detect)
    import cv2

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", frame)
    r = client.post(
        "/api/aluno/session/frame",
        files={"frame": ("f.jpg", buf.tobytes(), "image/jpeg")},
        data={"session_token": token},
    )
    assert r.status_code == 200
    assert r.json()["capture"]["ui_code"] == "multi_face"
    assert "mais de uma pessoa" in r.json()["capture"]["status_human"].lower()


def test_revoked_campaign_blocks_frame(client: TestClient):
    camp = _camp(client)
    token = _session(client, camp)
    client.post(f"/api/gestor/campaigns/{camp['campaign_id']}/revoke")
    import cv2

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", frame)
    r = client.post(
        "/api/aluno/session/frame",
        files={"frame": ("f.jpg", buf.tobytes(), "image/jpeg")},
        data={"session_token": token},
    )
    assert r.status_code == 403


def test_ui_safe_hides_scores(client: TestClient):
    camp = _camp(client)
    token = _session(client, camp)
    st = client.get("/api/aluno/session/state", params={"session_token": token}).json()
    cap = st["capture"]
    blob = str(cap).lower()
    assert "threshold" not in blob
    assert "embedding" not in blob
    assert "facenet" not in blob
    assert "quality_score" not in blob
