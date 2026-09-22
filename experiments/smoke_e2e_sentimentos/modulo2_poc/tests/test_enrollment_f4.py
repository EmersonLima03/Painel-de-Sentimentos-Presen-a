"""F4 automated harness — recognition on campaign gallery (hooks, não físico)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

MODULO2 = Path(__file__).resolve().parents[1]
SCRIPTS = MODULO2 / "scripts"
sys.path.insert(0, str(SCRIPTS))

os.environ["M2_POC_TEST_HOOKS"] = "1"

from enrollment_gestor_server import build_app  # noqa: E402
from enrollment_pipeline import CAMPAIGN_GALLERY, CAPTURE_STORE, ack_glasses  # noqa: E402
from enrollment_store import EnrollmentStore  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from f4_e2e_lab_physical import load_campaign_gallery_by_name  # noqa: E402
from poc_common import match_gallery  # noqa: E402

HMAC = "f4-test"
SCHOOL = "escola_demo_presenca"
CLASS = "turma_familia_lab"


@pytest.fixture()
def client(tmp_path: Path):
    store = EnrollmentStore(
        tmp_path / "f4.db",
        hmac_secret=HMAC,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
        rate_limit_max=100,
    )
    app = build_app(store)
    with TestClient(app) as c:
        c.store = store  # type: ignore[attr-defined]
        yield c


def _enroll_via_hooks(client: TestClient, camp: dict, name: str, glasses: bool) -> str:
    code = next(r["claim_code"] for r in camp["claim_sheet"] if r["display_name"] == name)
    token = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": code},
    ).json()["session_token"]
    client.post("/api/aluno/session/start", json={"session_token": token})
    for step in ("front", "lateral_right", "lateral_left", "validate"):
        client.post(
            "/api/aluno/session/test/force-step",
            json={"session_token": token, "step": step},
        )
    g = client.post(
        "/api/aluno/session/glasses",
        json={"session_token": token, "uses_glasses": glasses},
    ).json()
    if glasses:
        client.post(
            "/api/aluno/session/test/force-step",
            json={"session_token": token, "step": "glasses_habitual"},
        )
    else:
        assert g["capture"]["completed"] is True
    return camp["campaign_id"]


def test_f4_two_identities_recognize_and_unknown(client: TestClient):
    camp = client.post(
        "/api/gestor/campaigns",
        json={"school_id": SCHOOL, "class_group_id": CLASS},
    ).json()
    _enroll_via_hooks(client, camp, "Dulin", glasses=False)
    _enroll_via_hooks(client, camp, "Mae", glasses=True)

    prog = client.get(f"/api/gestor/campaigns/{camp['campaign_id']}/progress").json()
    assert prog["completed"] == 2
    assert all(i["status"] == "completed" for i in prog["items"])

    gallery = load_campaign_gallery_by_name(camp["campaign_id"])
    assert len(gallery) >= 8  # 4+5 with glasses
    names = {n for n, _ in gallery}
    assert "Dulin" in names and "Mae" in names

    # Self-match: each person's front template should ID as themselves
    root = CAMPAIGN_GALLERY / camp["campaign_id"]
    for person_dir in root.iterdir():
        meta = json.loads((person_dir / "enroll_meta.json").read_text(encoding="utf-8"))
        name = meta["display_name"]
        front = np.load(person_dir / "front.npy").astype(np.float32).reshape(-1)
        front /= np.linalg.norm(front) + 1e-12
        m = match_gallery(front, gallery, 0.70, 0.10)
        assert m["decision"] == name, (name, m)

        if name == "Mae":
            assert (person_dir / "glasses_habitual.npy").is_file()

    # UNKNOWN: random unit vector
    rng = np.random.default_rng(42)
    q = rng.normal(size=512).astype(np.float32)
    q /= np.linalg.norm(q) + 1e-12
    unk = match_gallery(q, gallery, 0.70, 0.10)
    assert unk["decision"] == "UNKNOWN"

    # No production flags
    for person_dir in root.iterdir():
        meta = json.loads((person_dir / "enroll_meta.json").read_text(encoding="utf-8"))
        assert meta.get("product_db_written") is False
        assert meta.get("reload_matcher_called") is False
