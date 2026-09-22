"""F0 automated tests — Enrollment Escalavel A foundation (claim/session/TTL).

Run from modulo2_poc:
  python -m pytest tests/test_enrollment_f0.py -v
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

MODULO2 = Path(__file__).resolve().parents[1]
SCRIPTS = MODULO2 / "scripts"
sys.path.insert(0, str(SCRIPTS))

from enrollment_store import (  # noqa: E402
    CLAIM_GENERIC_ERROR,
    CLAIM_MISSING_CODE,
    CLAIM_RATE_LIMITED,
    ROSTER_CLAIMED,
    ROSTER_COMPLETED,
    ROSTER_IN_PROGRESS,
    ROSTER_PENDING,
    ClaimFailure,
    ClaimSuccess,
    EnrollmentStore,
)
from enrollment_tokens import (  # noqa: E402
    mint_session_token,
    qr_path_for_campaign_token,
)


SCHOOL_ID = "escola_demo_presenca"
CLASS_ID = "turma_familia_lab"
HMAC = "test-hmac-secret-f0-enrollment"


@pytest.fixture()
def store(tmp_path: Path) -> EnrollmentStore:
    return EnrollmentStore(
        tmp_path / "poc_enrollment.db",
        hmac_secret=HMAC,
        campaign_ttl_sec=3600,
        session_ttl_sec=1800,
        rate_limit_max=100,
        rate_limit_window_sec=60,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
    )


def _create(store: EnrollmentStore, **kwargs) -> dict:
    return store.create_campaign(
        school_id=SCHOOL_ID, class_group_id=CLASS_ID, **kwargs
    )


def test_fixtures_have_dulin_and_mae(store: EnrollmentStore):
    schools = store.list_schools()
    assert len(schools) == 1
    students = schools[0]["class_groups"][0]["students"]
    names = {s["display_name"] for s in students}
    assert names == {"Dulin", "Mae"}


def test_campaign_token_opaque_qr_path_only(store: EnrollmentStore):
    camp = _create(store)
    token = camp["campaign_token"]
    assert token
    assert "/" not in token
    assert camp["qr_path"] == f"/a/{token}"
    assert camp["qr_path"] == qr_path_for_campaign_token(token)
    # QR / token must not embed claim codes or names
    for sheet in camp["claim_sheet"]:
        assert sheet["claim_code"] not in token
        assert sheet["display_name"] not in token
    public = store.get_campaign_public_by_token(token)
    assert public is not None
    assert "Dulin" not in str(public)
    assert "Mae" not in str(public)
    assert "claim" not in str(public).lower()
    assert public["class_label"] == "8º Ano A"


def test_claim_valid_reveals_name_only_after_code(store: EnrollmentStore):
    camp = _create(store)
    sheet = {r["display_name"]: r["claim_code"] for r in camp["claim_sheet"]}
    result = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=sheet["Dulin"],
        client_ip="10.0.0.1",
    )
    assert isinstance(result, ClaimSuccess)
    ui = result.ui_safe()
    assert ui["display_name"] == "Dulin"
    assert "8º Ano A" in ui["message"]
    assert ui["session_token"]
    assert result.roster_status == ROSTER_CLAIMED
    # session bound to Dulin
    info = store.validate_session_token(ui["session_token"])
    assert info["display_name"] == "Dulin"
    assert info["roster_status"] == ROSTER_CLAIMED


def test_claim_invalid_generic_message(store: EnrollmentStore):
    camp = _create(store)
    bad = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code="000000",
        client_ip="10.0.0.2",
    )
    assert isinstance(bad, ClaimFailure)
    assert bad.error == CLAIM_GENERIC_ERROR
    # wrong token also generic
    bad2 = store.claim(
        campaign_token="not-a-real-campaign-token-xxxxx",
        claim_code=camp["claim_sheet"][0]["claim_code"],
        client_ip="10.0.0.2",
    )
    assert isinstance(bad2, ClaimFailure)
    assert bad2.error == CLAIM_GENERIC_ERROR


def test_claim_code_mandatory(store: EnrollmentStore):
    camp = _create(store)
    for empty in (None, "", "  "):
        r = store.claim(
            campaign_token=camp["campaign_token"],
            claim_code=empty,
            client_ip="10.0.0.3",
        )
        assert isinstance(r, ClaimFailure)
        assert r.error == CLAIM_MISSING_CODE


def test_claim_already_used_after_completed(store: EnrollmentStore):
    camp = _create(store)
    code = camp["claim_sheet"][0]["claim_code"]
    first = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.4",
    )
    assert isinstance(first, ClaimSuccess)
    store.mark_in_progress(first.session_token)
    store.complete_enrollment(first.session_token)
    assert (
        store.get_roster_status_by_claim(camp["campaign_id"], code)
        == ROSTER_COMPLETED
    )
    again = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.4",
    )
    assert isinstance(again, ClaimFailure)
    assert again.error == CLAIM_GENERIC_ERROR
    # same message as never-existed — no leak
    never = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code="111111",
        client_ip="10.0.0.4",
    )
    assert isinstance(never, ClaimFailure)
    assert never.error == again.error


def test_claim_already_claimed_blocks_second(store: EnrollmentStore):
    camp = _create(store)
    code = camp["claim_sheet"][0]["claim_code"]
    first = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.5",
    )
    assert isinstance(first, ClaimSuccess)
    second = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.6",
    )
    assert isinstance(second, ClaimFailure)
    assert second.error == CLAIM_GENERIC_ERROR
    assert second.http_status in (400, 409)


def test_concurrent_same_claim_only_one_wins(store: EnrollmentStore):
    camp = _create(store)
    code = camp["claim_sheet"][0]["claim_code"]
    barrier = threading.Barrier(8)
    results: list = []

    def worker(ip_suffix: int):
        barrier.wait()
        return store.claim(
            campaign_token=camp["campaign_token"],
            claim_code=code,
            client_ip=f"10.1.0.{ip_suffix}",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(worker, i) for i in range(8)]
        for f in as_completed(futs):
            results.append(f.result())

    successes = [r for r in results if isinstance(r, ClaimSuccess)]
    failures = [r for r in results if isinstance(r, ClaimFailure)]
    assert len(successes) == 1
    assert len(failures) == 7
    assert all(f.error == CLAIM_GENERIC_ERROR for f in failures)
    assert (
        store.get_roster_status_by_claim(camp["campaign_id"], code)
        == ROSTER_CLAIMED
    )


def test_expired_campaign_blocks_claim(store: EnrollmentStore):
    t0 = time.time()
    camp = _create(store, now=t0, campaign_ttl_sec=10)
    code = camp["claim_sheet"][0]["claim_code"]
    # After expiry
    bad = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.7",
        now=t0 + 11,
    )
    assert isinstance(bad, ClaimFailure)
    assert bad.error == CLAIM_GENERIC_ERROR


def test_revoked_campaign_blocks_claim(store: EnrollmentStore):
    camp = _create(store)
    store.revoke_campaign(camp["campaign_id"])
    code = camp["claim_sheet"][0]["claim_code"]
    bad = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.8",
    )
    assert isinstance(bad, ClaimFailure)
    assert bad.error == CLAIM_GENERIC_ERROR


def test_session_expiry_releases_roster_to_pending(tmp_path: Path):
    store = EnrollmentStore(
        tmp_path / "sess_ttl.db",
        hmac_secret=HMAC,
        campaign_ttl_sec=3600,
        session_ttl_sec=5,
        rate_limit_max=100,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
    )
    t0 = time.time()
    camp = _create(store, now=t0)
    code = next(c["claim_code"] for c in camp["claim_sheet"] if c["display_name"] == "Dulin")
    claimed = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.9",
        now=t0,
    )
    assert isinstance(claimed, ClaimSuccess)
    store.mark_in_progress(claimed.session_token, now=t0 + 1)
    assert (
        store.get_roster_status_by_claim(camp["campaign_id"], code)
        == ROSTER_IN_PROGRESS
    )

    t_late = t0 + 10
    sweep = store.sweep_expirations(now=t_late)
    assert sweep["expired_sessions"] >= 1
    assert sweep["released_roster"] >= 1
    assert (
        store.get_roster_status_by_claim(camp["campaign_id"], code)
        == ROSTER_PENDING
    )
    with pytest.raises(PermissionError):
        store.validate_session_token(claimed.session_token, now=t_late)

    # Can claim again after session expiry release
    again = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.0.9",
        now=t_late + 1,
    )
    assert isinstance(again, ClaimSuccess)


def test_session_token_bound_to_correct_student(store: EnrollmentStore):
    camp = _create(store)
    by_name = {r["display_name"]: r["claim_code"] for r in camp["claim_sheet"]}
    dulin = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=by_name["Dulin"],
        client_ip="10.0.1.1",
    )
    mae = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=by_name["Mae"],
        client_ip="10.0.1.2",
    )
    assert isinstance(dulin, ClaimSuccess)
    assert isinstance(mae, ClaimSuccess)

    dulin_info = store.validate_session_token(dulin.session_token)
    mae_info = store.validate_session_token(mae.session_token)
    assert dulin_info["roster_student_id"] != mae_info["roster_student_id"]

    # Dulin's token cannot be required as Mae
    with pytest.raises(PermissionError, match="does not belong"):
        store.validate_session_token(
            dulin.session_token,
            require_roster_id=mae_info["roster_student_id"],
        )

    # Forged token with Mae's roster id but Dulin's session id fails HMAC / DB
    forged = mint_session_token(
        session_id=dulin_info["session_id"],
        campaign_id=dulin_info["campaign_id"],
        roster_student_id=mae_info["roster_student_id"],
        exp=time.time() + 1000,
        secret=HMAC.encode("utf-8"),
    )
    with pytest.raises(PermissionError):
        store.validate_session_token(forged)


def test_decline_identity_returns_pending(store: EnrollmentStore):
    camp = _create(store)
    code = camp["claim_sheet"][0]["claim_code"]
    claimed = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.1.3",
    )
    assert isinstance(claimed, ClaimSuccess)
    store.decline_identity(claimed.session_token)
    assert (
        store.get_roster_status_by_claim(camp["campaign_id"], code)
        == ROSTER_PENDING
    )
    # reclaim ok
    again = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.1.3",
    )
    assert isinstance(again, ClaimSuccess)


def test_rate_limit_on_claim(tmp_path: Path):
    store = EnrollmentStore(
        tmp_path / "rl.db",
        hmac_secret=HMAC,
        rate_limit_max=3,
        rate_limit_window_sec=60,
        fixtures_path=MODULO2 / "data" / "fixtures" / "schools.json",
    )
    camp = _create(store)
    ip = "10.0.2.50"
    # Burn limit with invalid codes
    for i in range(3):
        r = store.claim(
            campaign_token=camp["campaign_token"],
            claim_code=f"{i:06d}",
            client_ip=ip,
        )
        assert isinstance(r, ClaimFailure)
        assert r.error == CLAIM_GENERIC_ERROR

    blocked = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code="999999",
        client_ip=ip,
    )
    assert isinstance(blocked, ClaimFailure)
    assert blocked.error == CLAIM_RATE_LIMITED
    assert blocked.http_status == 429


def test_lifecycle_pending_claimed_in_progress_completed(store: EnrollmentStore):
    camp = _create(store)
    code = camp["claim_sheet"][0]["claim_code"]
    assert store.get_roster_status_by_claim(camp["campaign_id"], code) == ROSTER_PENDING
    c = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="10.0.3.1",
    )
    assert isinstance(c, ClaimSuccess)
    assert store.get_roster_status_by_claim(camp["campaign_id"], code) == ROSTER_CLAIMED
    store.mark_in_progress(c.session_token)
    assert (
        store.get_roster_status_by_claim(camp["campaign_id"], code)
        == ROSTER_IN_PROGRESS
    )
    store.complete_enrollment(c.session_token)
    assert (
        store.get_roster_status_by_claim(camp["campaign_id"], code)
        == ROSTER_COMPLETED
    )
    prog = store.get_roster_progress(camp["campaign_id"])
    assert prog["completed"] == 1
    assert prog["total"] == 2
