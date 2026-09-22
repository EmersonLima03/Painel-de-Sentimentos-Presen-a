"""Contrato de identidade facial: promote atomico, edge_student_key, reload, revogacao.

Run from modulo2_poc:
  python -m pytest tests/test_enrollment_identity.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

MODULO2 = Path(__file__).resolve().parents[1]
SCRIPTS = MODULO2 / "scripts"
sys.path.insert(0, str(SCRIPTS))

from enrollment_promote import (  # noqa: E402
    derive_edge_student_key,
    looks_like_uuid,
    promote_completed_enrollment,
    require_edge_student_key,
)
from enrollment_store import EnrollmentStore  # noqa: E402


SCHOOL_ID = "escola_demo_presenca"
CLASS_ID = "turma_familia_lab"


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "identity.db"
    fixtures = MODULO2 / "data" / "fixtures" / "schools.json"
    return EnrollmentStore(
        db_path=db,
        fixtures_path=fixtures,
        hmac_secret="test-identity-hmac",
        campaign_ttl_sec=3600,
        session_ttl_sec=1800,
    )


def _student_a(store: EnrollmentStore):
    schools = store.list_schools()
    school = next(s for s in schools if s["id"] == SCHOOL_ID)
    cg = next(c for c in school["class_groups"] if c["id"] == CLASS_ID)
    return cg["students"][0]


def test_looks_like_uuid():
    assert looks_like_uuid("550e8400-e29b-41d4-a716-446655440000")
    assert not looks_like_uuid("p01")
    assert not looks_like_uuid("aluno_dulin")
    assert not looks_like_uuid("")
    assert not looks_like_uuid("e_550e8400e29b41d4a716446655440000")


def test_derive_edge_student_key_stable_unique_not_uuid():
    sid = "550e8400-e29b-41d4-a716-446655440000"
    k = derive_edge_student_key(sid)
    assert k == "e_550e8400e29b41d4a716446655440000"
    assert k == derive_edge_student_key(sid)
    assert not looks_like_uuid(k)
    other = derive_edge_student_key("660e8400-e29b-41d4-a716-446655440001")
    assert k != other


def test_require_edge_student_key_rejects_uuid_and_derives_from_student_id():
    with pytest.raises(ValueError, match="UUID"):
        require_edge_student_key(
            {
                "student_id": "550e8400-e29b-41d4-a716-446655440000",
                "edge_student_key": "550e8400-e29b-41d4-a716-446655440000",
            }
        )
    # Missing explicit key → derive from students.id
    derived = require_edge_student_key(
        {"student_id": "550e8400-e29b-41d4-a716-446655440000"}
    )
    assert derived == "e_550e8400e29b41d4a716446655440000"
    assert require_edge_student_key({"edge_student_key": "p01"}) == "p01"
    assert require_edge_student_key({"fixture_key": "aluno_dulin"}) == "aluno_dulin"


def test_start_enrollment_auto_derives_edge_key_from_student_id(tmp_path):
    """Aluno so com UUID oficial: sistema deriva e_<hex> e inicia enrollment."""
    import json

    sid = "550e8400-e29b-41d4-a716-446655440099"
    fixtures = {
        "schools": [
            {
                "id": SCHOOL_ID,
                "name": "Escola Demo",
                "class_groups": [
                    {
                        "id": CLASS_ID,
                        "label": "8A",
                        "students": [
                            {
                                "student_id": sid,
                                "display_name": "Sem Chave Manual",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    fp = tmp_path / "schools_uuid.json"
    fp.write_text(json.dumps(fixtures), encoding="utf-8")
    st = EnrollmentStore(
        db_path=tmp_path / "uuid.db",
        fixtures_path=fp,
        hmac_secret="test-uuid",
    )
    out = st.start_student_enrollment(
        school_id=SCHOOL_ID,
        class_group_id=CLASS_ID,
        student_id=sid,
    )
    assert out.get("ok") is True or out.get("invite_token")
    assert out.get("edge_student_key") == derive_edge_student_key(sid)


def test_promote_fails_without_templates_not_enrolled(store: EnrollmentStore, tmp_path):
    a = _student_a(store)
    sid = a.get("student_id") or a.get("fixture_key")
    out = store.start_student_enrollment(
        school_id=SCHOOL_ID, class_group_id=CLASS_ID, student_id=str(sid)
    )
    resolved = store.resolve_invite_token(out["invite_token"])
    done = store.complete_enrollment(resolved["session_token"])
    assert done["product_enrolled"] is False
    assert done["facial_status"] == "failed"
    assert done["promote"].get("ok") is False
    status = store.list_class_facial_status(SCHOOL_ID, CLASS_ID)
    row = next(
        s
        for s in status["students"]
        if s["display_name"] == a["display_name"]
    )
    assert row["facial_status"] != "enrolled"


def test_promote_reload_failure_blocks_enrolled(monkeypatch):
    """Template persistido + reload falha => product_enrolled False."""
    templates = [("front", np.ones(128, dtype=np.float32))]

    monkeypatch.setattr(
        "enrollment_promote.load_templates",
        lambda *a, **k: templates,
    )
    monkeypatch.setattr(
        "enrollment_promote.write_face_embeddings",
        lambda **k: {
            "ok": True,
            "edge_student_key": "p01",
            "n_written": 1,
            "n_confirmed": 1,
            "replaced": True,
        },
    )
    monkeypatch.setattr(
        "enrollment_promote.reload_matcher_via_edge",
        lambda *a, **k: {"ok": False, "error": "connection refused"},
    )
    monkeypatch.setattr(
        "enrollment_promote.update_enroll_meta_flags",
        lambda *a, **k: None,
    )

    result = promote_completed_enrollment(
        campaign_id="camp-x",
        roster_student_id="roster-1",
        edge_student_key="p01",
        display_name="P01",
        call_reload=True,
    )
    assert result["ok"] is False
    assert result["product_enrolled"] is False
    assert result["error"] == "reload_matcher_failed"
    assert result.get("n_confirmed") == 1


def test_promote_success_requires_persist_and_reload(monkeypatch):
    templates = [("front", np.ones(128, dtype=np.float32))]
    monkeypatch.setattr(
        "enrollment_promote.load_templates",
        lambda *a, **k: templates,
    )
    monkeypatch.setattr(
        "enrollment_promote.write_face_embeddings",
        lambda **k: {
            "ok": True,
            "edge_student_key": "p01",
            "n_written": 1,
            "n_confirmed": 1,
            "replaced": True,
        },
    )
    monkeypatch.setattr(
        "enrollment_promote.reload_matcher_via_edge",
        lambda *a, **k: {"ok": True, "http_status": 200, "pipelines_reloaded": 1},
    )
    monkeypatch.setattr(
        "enrollment_promote.update_enroll_meta_flags",
        lambda *a, **k: None,
    )

    result = promote_completed_enrollment(
        campaign_id="camp-x",
        roster_student_id="roster-1",
        edge_student_key="p01",
        display_name="P01",
        call_reload=True,
    )
    assert result["ok"] is True
    assert result["product_enrolled"] is True


def test_promote_rejects_uuid_as_edge_key(monkeypatch):
    monkeypatch.setattr(
        "enrollment_promote.load_templates",
        lambda *a, **k: [("front", np.ones(8, dtype=np.float32))],
    )
    result = promote_completed_enrollment(
        campaign_id="c",
        roster_student_id="r",
        edge_student_key="550e8400-e29b-41d4-a716-446655440000",
        display_name="X",
    )
    assert result["ok"] is False
    assert result["product_enrolled"] is False
    assert "edge_student_key" in result["error"]


def test_revoke_clears_matcher_identity(store: EnrollmentStore, monkeypatch):
    a = _student_a(store)
    sid = a.get("student_id") or a.get("fixture_key")
    edge = a.get("fixture_key") or a.get("edge_student_key")
    out = store.start_student_enrollment(
        school_id=SCHOOL_ID, class_group_id=CLASS_ID, student_id=str(sid)
    )

    called: dict = {}

    def fake_revoke(*, edge_student_key: str, call_reload: bool = True):
        called["key"] = edge_student_key
        called["reload"] = call_reload
        return {
            "ok": True,
            "n_deleted": 3,
            "revoked_from_matcher": True,
            "embeddings_remain": False,
        }

    monkeypatch.setattr(
        "enrollment_promote.revoke_identity_from_matcher",
        fake_revoke,
    )
    rev = store.revoke_student_invite(
        student_id=str(sid), campaign_id=out["campaign_id"]
    )
    assert rev["status"] == "revoked"
    assert called.get("key") == edge
    assert called.get("reload") is True
    assert rev["matcher"].get("revoked_from_matcher") is True

    with pytest.raises(PermissionError):
        store.resolve_invite_token(out["invite_token"])


def test_complete_marks_enrolled_only_when_product_enrolled(
    store: EnrollmentStore, monkeypatch
):
    a = _student_a(store)
    sid = a.get("student_id") or a.get("fixture_key")
    out = store.start_student_enrollment(
        school_id=SCHOOL_ID, class_group_id=CLASS_ID, student_id=str(sid)
    )
    resolved = store.resolve_invite_token(out["invite_token"])

    monkeypatch.setattr(
        "enrollment_promote.promote_completed_enrollment",
        lambda **k: {
            "ok": True,
            "product_enrolled": True,
            "n_written": 4,
            "n_confirmed": 4,
            "reload_matcher_called": True,
        },
    )
    done = store.complete_enrollment(resolved["session_token"])
    assert done["product_enrolled"] is True
    assert done["facial_status"] == "enrolled"

    # Simulate embeddings present for status listing
    monkeypatch.setattr(
        "enrollment_promote.edge_student_has_embeddings",
        lambda key: key == (a.get("fixture_key") or a.get("edge_student_key")),
    )
    status = store.list_class_facial_status(SCHOOL_ID, CLASS_ID)
    row = next(s for s in status["students"] if s["display_name"] == a["display_name"])
    assert row["facial_status"] == "enrolled"
