"""F1 API tests — Gestor campaign / QR / progress (no facial pipeline)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

MODULO2 = Path(__file__).resolve().parents[1]
SCRIPTS = MODULO2 / "scripts"
sys.path.insert(0, str(SCRIPTS))

from enrollment_gestor_server import build_app  # noqa: E402
from enrollment_store import EnrollmentStore  # noqa: E402
from enrollment_tokens import qr_path_for_campaign_token  # noqa: E402

HMAC = "test-hmac-secret-f1-gestor"
SCHOOL_ID = "escola_demo_presenca"
CLASS_ID = "turma_familia_lab"


@pytest.fixture()
def client(tmp_path: Path):
    store = EnrollmentStore(
        tmp_path / "gestor.db",
        hmac_secret=HMAC,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
    )
    app = build_app(store)
    with TestClient(app) as c:
        c.store = store  # type: ignore[attr-defined]
        yield c


def test_gestor_page_loads(client: TestClient):
    r = client.get("/gestor/")
    assert r.status_code == 200
    assert "Cadastro facial" in r.text
    assert "school-select" in r.text
    assert "POC isolado" not in r.text


def test_schools_fixture_exposed(client: TestClient):
    r = client.get("/api/gestor/schools")
    assert r.status_code == 200
    schools = r.json()["schools"]
    assert schools[0]["name"] == "Escola Demo Presenca"
    cg = schools[0]["class_groups"][0]
    assert cg["label"] == "8º Ano A"
    assert cg["student_count"] == 2
    names = {s["display_name"] for s in cg["students"]}
    assert names == {"Dulin", "Mae"}
    # schools endpoint must not leak claim codes
    assert "claim_code" not in r.text


def test_create_campaign_qr_and_progress(client: TestClient):
    r = client.post(
        "/api/gestor/campaigns",
        json={"school_id": SCHOOL_ID, "class_group_id": CLASS_ID},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active"
    assert body["roster_count"] == 2
    token = body["campaign_token"]
    assert token
    assert body["qr_path"] == qr_path_for_campaign_token(token)
    assert token in body["share_link"]
    assert body["share_link"].endswith(f"/a/{token}")
    # link/token must not embed names or claim codes
    for row in body["claim_sheet"]:
        assert row["claim_code"] not in body["share_link"]
        assert row["display_name"] not in token

    cid = body["campaign_id"]
    prog = client.get(f"/api/gestor/campaigns/{cid}/progress").json()
    assert prog["total"] == 2
    assert prog["completed"] == 0
    assert prog["percent"] == 0.0
    assert prog["status"] == "active"
    by_name = {i["display_name"]: i["status"] for i in prog["items"]}
    assert by_name["Dulin"] == "pending"
    assert by_name["Mae"] == "pending"

    qr = client.get(f"/api/gestor/campaigns/{cid}/qr.png")
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert qr.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_revoke_campaign(client: TestClient):
    created = client.post(
        "/api/gestor/campaigns",
        json={"school_id": SCHOOL_ID, "class_group_id": CLASS_ID},
    ).json()
    cid = created["campaign_id"]
    rev = client.post(f"/api/gestor/campaigns/{cid}/revoke")
    assert rev.status_code == 200
    assert rev.json()["revoked"] is True
    prog = client.get(f"/api/gestor/campaigns/{cid}/progress").json()
    assert prog["status"] == "revoked"


def test_get_campaign_includes_opaque_token_only_in_link(client: TestClient):
    created = client.post(
        "/api/gestor/campaigns",
        json={"school_id": SCHOOL_ID, "class_group_id": CLASS_ID},
    ).json()
    full = client.get(f"/api/gestor/campaigns/{created['campaign_id']}").json()
    link = full["share_link"]
    assert full["campaign_token"] in link
    assert "/a/" in link
    assert "embedding" not in link.lower()
    assert "session" not in link.lower()
