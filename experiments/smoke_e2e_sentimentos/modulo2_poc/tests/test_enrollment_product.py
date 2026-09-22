"""Product facial enrollment: student-centric invite + identity isolation.

Run from modulo2_poc:
  python -m pytest tests/test_enrollment_product.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

MODULO2 = Path(__file__).resolve().parents[1]
SCRIPTS = MODULO2 / "scripts"
sys.path.insert(0, str(SCRIPTS))

from enrollment_store import (  # noqa: E402
    ROSTER_CLAIMED,
    ClaimFailure,
    EnrollmentStore,
)


SCHOOL_ID = "escola_demo_presenca"
CLASS_ID = "turma_familia_lab"


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "enroll.db"
    fixtures = MODULO2 / "data" / "fixtures" / "schools.json"
    return EnrollmentStore(
        db_path=db,
        fixtures_path=fixtures,
        hmac_secret="test-product-hmac-secret",
        campaign_ttl_sec=3600,
        session_ttl_sec=1800,
    )


def _first_two_students(store: EnrollmentStore):
    schools = store.list_schools()
    school = next(s for s in schools if s["id"] == SCHOOL_ID)
    cg = next(c for c in school["class_groups"] if c["id"] == CLASS_ID)
    students = cg["students"]
    assert len(students) >= 2
    return students[0], students[1]


def test_start_student_enrollment_creates_invite(store: EnrollmentStore):
    a, _ = _first_two_students(store)
    sid = a.get("student_id") or a.get("fixture_key")
    out = store.start_student_enrollment(
        school_id=SCHOOL_ID,
        class_group_id=CLASS_ID,
        student_id=str(sid),
    )
    assert out["ok"] is True
    assert out["qr_path"].startswith("/e/")
    assert out["invite_token"]
    assert out["display_name"] == a["display_name"]
    assert "student_id" not in out["qr_path"]
    assert a["display_name"] not in out["qr_path"]

    resolved = store.resolve_invite_token(out["invite_token"])
    assert resolved["display_name"] == a["display_name"]
    assert resolved["session_token"]
    info = store.validate_session_token(resolved["session_token"])
    assert info["roster_status"] == ROSTER_CLAIMED


def test_invite_bound_to_student_not_swappable(store: EnrollmentStore):
    """P01 invite must not resolve as P02 identity."""
    a, b = _first_two_students(store)
    sid_a = a.get("student_id") or a.get("fixture_key")
    sid_b = b.get("student_id") or b.get("fixture_key")
    out_a = store.start_student_enrollment(
        school_id=SCHOOL_ID, class_group_id=CLASS_ID, student_id=str(sid_a)
    )
    out_b = store.start_student_enrollment(
        school_id=SCHOOL_ID, class_group_id=CLASS_ID, student_id=str(sid_b)
    )
    ra = store.resolve_invite_token(out_a["invite_token"])
    rb = store.resolve_invite_token(out_b["invite_token"])
    assert ra["display_name"] == a["display_name"]
    assert rb["display_name"] == b["display_name"]
    assert ra["display_name"] != rb["display_name"]
    # Using B's invite cannot yield A's name
    assert ra["session_token"] != rb["session_token"]


def test_class_facial_status_not_fake_completed(store: EnrollmentStore):
    status = store.list_class_facial_status(SCHOOL_ID, CLASS_ID)
    assert status["ok"] is True
    assert status["total"] >= 2
    for st in status["students"]:
        assert st["facial_status"] in (
            "not_enrolled",
            "in_progress",
            "enrolled",
            "expired",
            "revoked",
            "failed",
        )
        # Never invent completed/campaign language as permanent status
        assert st["facial_status"] != "completed"


def test_revoke_invite(store: EnrollmentStore):
    a, _ = _first_two_students(store)
    sid = a.get("student_id") or a.get("fixture_key")
    out = store.start_student_enrollment(
        school_id=SCHOOL_ID, class_group_id=CLASS_ID, student_id=str(sid)
    )
    store.revoke_student_invite(student_id=str(sid), campaign_id=out["campaign_id"])
    with pytest.raises(PermissionError):
        store.resolve_invite_token(out["invite_token"])


def test_legacy_campaign_claim_still_works(store: EnrollmentStore):
    created = store.create_campaign(school_id=SCHOOL_ID, class_group_id=CLASS_ID)
    code = created["claim_sheet"][0]["claim_code"]
    claimed = store.claim(
        campaign_token=created["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.1",
    )
    assert not isinstance(claimed, ClaimFailure)
    assert claimed.session_token
