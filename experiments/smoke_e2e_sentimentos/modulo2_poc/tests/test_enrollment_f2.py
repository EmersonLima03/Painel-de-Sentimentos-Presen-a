"""F2 API/UI tests — fluxo aluno (claim/sessao) sem camera."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

MODULO2 = Path(__file__).resolve().parents[1]
SCRIPTS = MODULO2 / "scripts"
sys.path.insert(0, str(SCRIPTS))

from enrollment_gestor_server import build_app  # noqa: E402
from enrollment_store import (  # noqa: E402
    CLAIM_GENERIC_ERROR,
    EnrollmentStore,
    ROSTER_CLAIMED,
    ROSTER_COMPLETED,
    ROSTER_IN_PROGRESS,
    ROSTER_PENDING,
)

HMAC = "test-hmac-secret-f2-aluno"
SCHOOL_ID = "escola_demo_presenca"
CLASS_ID = "turma_familia_lab"


@pytest.fixture()
def client(tmp_path: Path):
    store = EnrollmentStore(
        tmp_path / "aluno.db",
        hmac_secret=HMAC,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
        rate_limit_max=100,
    )
    app = build_app(store)
    with TestClient(app) as c:
        c.store = store  # type: ignore[attr-defined]
        yield c


def _create(client: TestClient) -> dict:
    return client.post(
        "/api/gestor/campaigns",
        json={"school_id": SCHOOL_ID, "class_group_id": CLASS_ID},
    ).json()


def _code_for(camp: dict, name: str) -> str:
    return next(r["claim_code"] for r in camp["claim_sheet"] if r["display_name"] == name)


def test_aluno_page_served(client: TestClient):
    camp = _create(client)
    r = client.get(f"/a/{camp['campaign_token']}")
    assert r.status_code == 200
    assert "Vamos preparar seu cadastro" in r.text
    assert "claim-code" in r.text
    # Camera is requested only after "Começar cadastro" (F3); page may reference getUserMedia in JS
    assert "FaceNet" not in r.text
    assert "YuNet" not in r.text
    assert "threshold" not in r.text.lower()


def test_campaign_public_valid(client: TestClient):
    camp = _create(client)
    r = client.get(f"/api/aluno/campaign/{camp['campaign_token']}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "active"
    assert body["class_label"] == "8º Ano A"
    assert "Dulin" not in r.text
    assert "claim" not in r.text.lower() or "claim_code" not in r.text


def test_campaign_inexistente(client: TestClient):
    r = client.get("/api/aluno/campaign/token-que-nao-existe")
    assert r.json()["ok"] is False


def test_campaign_expirada(client: TestClient, tmp_path: Path):
    store = EnrollmentStore(
        tmp_path / "exp.db",
        hmac_secret=HMAC,
        campaign_ttl_sec=1,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
    )
    app = build_app(store)
    with TestClient(app) as c:
        t0 = time.time()
        camp = store.create_campaign(
            school_id=SCHOOL_ID, class_group_id=CLASS_ID, now=t0, campaign_ttl_sec=1
        )
        pub = store.get_campaign_public_by_token(camp["campaign_token"], now=t0 + 5)
        assert pub["status"] == "expired"
        r = c.get(f"/api/aluno/campaign/{camp['campaign_token']}")
        # sweep happens inside get
        assert r.json()["status"] == "expired"


def test_campaign_revogada(client: TestClient):
    camp = _create(client)
    client.post(f"/api/gestor/campaigns/{camp['campaign_id']}/revoke")
    r = client.get(f"/api/aluno/campaign/{camp['campaign_token']}")
    assert r.json()["status"] == "revoked"
    claim = client.post(
        "/api/aluno/claim",
        json={
            "campaign_token": camp["campaign_token"],
            "claim_code": _code_for(camp, "Dulin"),
        },
    )
    assert claim.status_code == 400
    assert claim.json()["error"] == CLAIM_GENERIC_ERROR


def test_claim_valido_e_fluxo_start(client: TestClient):
    camp = _create(client)
    claim = client.post(
        "/api/aluno/claim",
        json={
            "campaign_token": camp["campaign_token"],
            "claim_code": _code_for(camp, "Dulin"),
        },
    )
    assert claim.status_code == 200
    body = claim.json()
    assert body["ok"] is True
    assert body["display_name"] == "Dulin"
    assert body["roster_status"] == ROSTER_CLAIMED
    token = body["session_token"]

    start = client.post("/api/aluno/session/start", json={"session_token": token})
    assert start.status_code == 200
    assert start.json()["roster_status"] == ROSTER_IN_PROGRESS
    assert start.json()["camera_enabled"] is True
    assert start.json()["ready_for_facial"] is True
    assert "capture" in start.json()
    assert start.json()["capture"]["phase"] == "front"


def test_claim_invalido_generico(client: TestClient):
    camp = _create(client)
    bad = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": "000000"},
    )
    assert bad.status_code == 400
    assert bad.json()["error"] == CLAIM_GENERIC_ERROR


def test_claim_ja_concluido(client: TestClient):
    camp = _create(client)
    code = _code_for(camp, "Dulin")
    claim = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": code},
    ).json()
    client.post("/api/aluno/session/start", json={"session_token": claim["session_token"]})
    # F3 exige captura; para este teste de reuso do claim usamos o store diretamente
    client.store.complete_enrollment(claim["session_token"])  # type: ignore[attr-defined]
    again = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": code},
    )
    assert again.status_code == 400
    assert again.json()["error"] == CLAIM_GENERIC_ERROR


def test_claim_em_uso(client: TestClient):
    camp = _create(client)
    code = _code_for(camp, "Mae")
    first = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": code},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": code},
    )
    assert second.status_code in (400, 409)
    assert second.json()["error"] == CLAIM_GENERIC_ERROR


def test_nao_sou_eu_libera_claim(client: TestClient):
    camp = _create(client)
    code = _code_for(camp, "Dulin")
    claim = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": code},
    ).json()
    dec = client.post(
        "/api/aluno/session/decline",
        json={"session_token": claim["session_token"]},
    )
    assert dec.status_code == 200
    assert dec.json()["roster_status"] == ROSTER_PENDING
    again = client.post(
        "/api/aluno/claim",
        json={"campaign_token": camp["campaign_token"], "claim_code": code},
    )
    assert again.status_code == 200


def test_sessao_outro_aluno(client: TestClient):
    camp = _create(client)
    dulin = client.post(
        "/api/aluno/claim",
        json={
            "campaign_token": camp["campaign_token"],
            "claim_code": _code_for(camp, "Dulin"),
        },
    ).json()
    mae = client.post(
        "/api/aluno/claim",
        json={
            "campaign_token": camp["campaign_token"],
            "claim_code": _code_for(camp, "Mae"),
        },
    ).json()
    dulin_info = client.get(
        "/api/aluno/session/state",
        params={"session_token": dulin["session_token"]},
    ).json()
    mae_info = client.get(
        "/api/aluno/session/state",
        params={"session_token": mae["session_token"]},
    ).json()
    hijack = client.get(
        "/api/aluno/session/state",
        params={
            "session_token": dulin["session_token"],
            "require_roster_id": mae_info["roster_student_id"],
        },
    )
    assert hijack.status_code == 403
    assert hijack.json()["ok"] is False
    assert dulin_info["roster_student_id"] != mae_info["roster_student_id"]


def test_sessao_expirada(client: TestClient, tmp_path: Path):
    store = EnrollmentStore(
        tmp_path / "sess.db",
        hmac_secret=HMAC,
        session_ttl_sec=2,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
        rate_limit_max=50,
    )
    app = build_app(store)
    with TestClient(app) as c:
        t0 = time.time()
        camp = store.create_campaign(
            school_id=SCHOOL_ID, class_group_id=CLASS_ID, now=t0
        )
        code = next(
            r["claim_code"] for r in camp["claim_sheet"] if r["display_name"] == "Dulin"
        )
        claimed = store.claim(
            campaign_token=camp["campaign_token"],
            claim_code=code,
            client_ip="1.1.1.1",
            now=t0,
        )
        assert claimed.session_token
        store.sweep_expirations(now=t0 + 10)
        r = c.get(
            "/api/aluno/session/state",
            params={"session_token": claimed.session_token},
        )
        # token HMAC also expires
        assert r.status_code == 403


def test_sessao_valida(client: TestClient):
    camp = _create(client)
    claim = client.post(
        "/api/aluno/claim",
        json={
            "campaign_token": camp["campaign_token"],
            "claim_code": _code_for(camp, "Dulin"),
        },
    ).json()
    st = client.get(
        "/api/aluno/session/state",
        params={"session_token": claim["session_token"]},
    )
    assert st.status_code == 200
    assert st.json()["ok"] is True
    assert st.json()["camera_enabled"] is True
