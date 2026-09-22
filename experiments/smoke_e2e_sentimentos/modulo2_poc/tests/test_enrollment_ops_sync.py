"""enrollment_ops_sync: disable without credentials; idempotent upsert on 409."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import HTTPError

import enrollment_ops_sync as sync
import pytest


def test_ops_sync_disabled_without_env(monkeypatch):
    monkeypatch.delenv("M2_OPS_SUPABASE_URL", raising=False)
    monkeypatch.delenv("M2_OPS_SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    sync.reset_config_for_tests()
    assert sync.configured() is False
    # Must not raise
    sync.upsert_campaign(
        campaign_id="c1",
        school_id="s",
        school_name="S",
        class_group_id="g",
        class_label="G",
        campaign_token_hash="h",
        status="active",
        expires_at=1.0,
        created_at=1.0,
    )


def test_ts_iso():
    assert sync._ts(None) is None
    assert "T" in sync._ts(1700000000.0)


class _FakeResp:
    def __init__(self, status: int = 200, body: bytes = b""):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(code: int, body: bytes = b'{"code":"23505"}') -> HTTPError:
    return HTTPError(
        url="http://example/rest/v1/x",
        code=code,
        msg="Conflict",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


@pytest.fixture()
def sync_enabled(monkeypatch):
    monkeypatch.setenv("M2_OPS_SUPABASE_URL", "http://example.supabase.co")
    monkeypatch.setenv("M2_OPS_SUPABASE_SERVICE_KEY", "service-role-test")
    sync.reset_config_for_tests()
    assert sync.configured() is True
    yield
    sync.reset_config_for_tests()


def test_upsert_retry_same_id_after_409_patches(monkeypatch, sync_enabled):
    """Retry do mesmo registro: POST 409 + linha existe no PK → PATCH."""
    calls: list[tuple[str, str]] = []

    def fake_urlopen(req, timeout=8):  # noqa: ARG001
        method = req.get_method()
        url = req.full_url
        calls.append((method, url))
        if method == "POST":
            raise _http_error(409)
        if method == "GET":
            return _FakeResp(200, b'[{"id":"r1"}]')
        if method == "PATCH":
            return _FakeResp(204, b"")
        raise AssertionError(f"unexpected {method}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    ok = sync._upsert_by_id(
        "facial_enrollment_roster",
        {
            "id": "r1",
            "campaign_id": "c1",
            "claim_code": "111111",
            "display_name": "A",
            "status": "pending",
        },
        row_id="r1",
    )
    assert ok is True
    assert any(m == "POST" for m, _ in calls)
    assert any(m == "PATCH" and "id=eq.r1" in u for m, u in calls)


def test_upsert_409_other_unique_refuses_overwrite(monkeypatch, sync_enabled):
    """Mesmo claim_code/token_hash de outro id: não sobrescreve."""
    calls: list[str] = []

    def fake_urlopen(req, timeout=8):  # noqa: ARG001
        method = req.get_method()
        calls.append(method)
        if method == "POST":
            raise _http_error(409)
        if method == "GET":
            return _FakeResp(200, b"[]")  # PK ausente → conflito de outro registro
        raise AssertionError("PATCH não deve ocorrer")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    ok = sync._upsert_by_id(
        "facial_enrollment_roster",
        {
            "id": "new-id",
            "campaign_id": "c1",
            "claim_code": "111111",
            "display_name": "Intruder",
            "status": "pending",
        },
        row_id="new-id",
    )
    assert ok is False
    assert "PATCH" not in calls


def test_upsert_session_idempotent_retry(monkeypatch, sync_enabled):
    def fake_urlopen(req, timeout=8):  # noqa: ARG001
        if req.get_method() == "POST":
            raise _http_error(409)
        if req.get_method() == "GET":
            return _FakeResp(200, b'[{"id":"s1"}]')
        return _FakeResp(204, b"")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sync.upsert_session(
        session_id="s1",
        campaign_id="c1",
        roster_id="r1",
        token_hash="th1",
        status="CREATED",
        expires_at=2.0,
        created_at=1.0,
    )


def test_sync_create_orders_campaign_before_roster(monkeypatch, sync_enabled):
    order: list[str] = []

    def fake_urlopen(req, timeout=8):  # noqa: ARG001
        url = req.full_url
        if "facial_enrollment_campaigns" in url and req.get_method() == "POST":
            order.append("campaign")
            return _FakeResp(201, b"")
        if "facial_enrollment_roster" in url and req.get_method() == "POST":
            order.append("roster")
            return _FakeResp(201, b"")
        return _FakeResp(200, b"[]")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sync.sync_create_campaign_and_roster(
        campaign_kwargs={
            "campaign_id": "c1",
            "school_id": "s",
            "school_name": "S",
            "class_group_id": "g",
            "class_label": "G",
            "campaign_token_hash": "h",
            "status": "active",
            "expires_at": 2.0,
            "created_at": 1.0,
        },
        roster_rows=[
            {
                "id": "r1",
                "campaign_id": "c1",
                "display_name": "A",
                "claim_code": "101",
                "status": "pending",
            },
            {
                "id": "r2",
                "campaign_id": "c1",
                "display_name": "B",
                "claim_code": "102",
                "status": "pending",
            },
        ],
    )
    assert order[0] == "campaign"
    assert order.count("roster") == 2


def test_sync_claim_orders_roster_before_session(monkeypatch, sync_enabled):
    order: list[str] = []

    def fake_urlopen(req, timeout=8):  # noqa: ARG001
        url = req.full_url
        method = req.get_method()
        if "facial_enrollment_roster" in url and method == "PATCH":
            order.append("patch_roster")
            return _FakeResp(204, b"")
        if "facial_enrollment_sessions" in url and method == "POST":
            order.append("upsert_session")
            return _FakeResp(201, b"")
        return _FakeResp(200, b"[]")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sync.sync_claim(
        roster_id="r1",
        session_id="s1",
        campaign_id="c1",
        token_hash="th",
        claimed_at=1.0,
        expires_at=2.0,
        created_at=1.0,
    )
    assert order == ["patch_roster", "upsert_session"]


def test_prefer_merge_only_on_upsert_post(monkeypatch, sync_enabled):
    seen: list[dict[str, Any]] = []

    def fake_urlopen(req, timeout=8):  # noqa: ARG001
        seen.append(dict(req.headers))
        return _FakeResp(204, b"")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sync.patch_roster("r1", status="claimed")
    assert "resolution=merge-duplicates" not in seen[0].get("Prefer", "")

    seen.clear()
    sync._request(
        "POST",
        "facial_enrollment_roster",
        json_body={"id": "r1"},
        params="?on_conflict=id",
        upsert=True,
    )
    assert "resolution=merge-duplicates" in seen[0].get("Prefer", "")
