"""Dual-write of M2 operational enrollment state to Supabase A (presence).

Never writes biometrics/embeddings. SQLite remains the local runtime source;
Supabase A is the durable operational mirror for campaign/roster/session status.

Env:
  M2_OPS_SUPABASE_URL          (fallback: SUPABASE_URL)
  M2_OPS_SUPABASE_SERVICE_KEY  (fallback: SUPABASE_SERVICE_ROLE_KEY)
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

logger = logging.getLogger("m2.ops_sync")

_ENABLED: Optional[bool] = None
_BASE: str = ""
_KEY: str = ""
_lock = threading.Lock()


def _ts(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _configure() -> bool:
    global _ENABLED, _BASE, _KEY
    with _lock:
        if _ENABLED is not None:
            return _ENABLED
        base = (
            os.environ.get("M2_OPS_SUPABASE_URL", "").strip()
            or os.environ.get("SUPABASE_URL", "").strip()
        ).rstrip("/")
        key = (
            os.environ.get("M2_OPS_SUPABASE_SERVICE_KEY", "").strip()
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
        if not base or not key:
            _ENABLED = False
            _BASE = ""
            _KEY = ""
            logger.info("m2_ops_sync_disabled missing_url_or_service_key")
            return False
        _BASE = base
        _KEY = key
        _ENABLED = True
        logger.info("m2_ops_sync_enabled base=%s", base)
        return True


def configured() -> bool:
    return _configure()


def _headers() -> dict[str, str]:
    return {
        "apikey": _KEY,
        "Authorization": f"Bearer {_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }


def _request(method: str, path: str, *, json_body: Any = None, params: str = "") -> None:
    if not _configure():
        return
    try:
        import urllib.error
        import urllib.request

        url = f"{_BASE}/rest/v1/{path}{params}"
        data = None
        headers = _headers()
        if json_body is not None:
            import json as _json

            data = _json.dumps(json_body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=8) as resp:
            _ = resp.read()
    except Exception as exc:  # noqa: BLE001 — never break enrollment on sync failure
        logger.warning("m2_ops_sync_failed method=%s path=%s err=%s", method, path, exc)


def upsert_campaign(
    *,
    campaign_id: str,
    school_id: str,
    school_name: str,
    class_group_id: str,
    class_label: str,
    campaign_token_hash: str,
    status: str,
    expires_at: float,
    created_at: float,
    revoked_at: Optional[float] = None,
    organization_id: Optional[str] = None,
) -> None:
    row: dict[str, Any] = {
        "id": campaign_id,
        "school_id": school_id,
        "school_name": school_name,
        "class_group_id": class_group_id,
        "class_label": class_label,
        "campaign_token_hash": campaign_token_hash,
        "status": status,
        "expires_at": _ts(expires_at),
        "created_at": _ts(created_at),
        "revoked_at": _ts(revoked_at),
        "updated_at": _now_iso(),
    }
    if organization_id:
        row["organization_id"] = organization_id
    _request(
        "POST",
        "facial_enrollment_campaigns",
        json_body=row,
        params="?on_conflict=id",
    )


def upsert_roster_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    payload = []
    for r in rows:
        payload.append(
            {
                "id": r["id"],
                "campaign_id": r["campaign_id"],
                "student_id": r.get("student_id"),
                "fixture_key": r.get("fixture_key"),
                "display_name": r["display_name"],
                "claim_code": r["claim_code"],
                "status": r["status"],
                "session_id": r.get("session_id"),
                "claimed_at": _ts(r.get("claimed_at")),
                "completed_at": _ts(r.get("completed_at")),
                "updated_at": _now_iso(),
            }
        )
    _request(
        "POST",
        "facial_enrollment_roster",
        json_body=payload,
        params="?on_conflict=id",
    )


def patch_roster(
    roster_id: str,
    *,
    status: Optional[str] = None,
    session_id: Optional[str] = None,
    claimed_at: Optional[float] = None,
    completed_at: Optional[float] = None,
) -> None:
    body: dict[str, Any] = {"updated_at": _now_iso()}
    if status is not None:
        body["status"] = status
    if session_id is not None:
        body["session_id"] = session_id
    if claimed_at is not None:
        body["claimed_at"] = _ts(claimed_at)
    if completed_at is not None:
        body["completed_at"] = _ts(completed_at)
    rid = quote(roster_id, safe="")
    _request("PATCH", "facial_enrollment_roster", json_body=body, params=f"?id=eq.{rid}")


def upsert_session(
    *,
    session_id: str,
    campaign_id: str,
    roster_id: str,
    token_hash: str,
    status: str,
    expires_at: float,
    created_at: float,
    consent_ok: bool = False,
) -> None:
    row = {
        "id": session_id,
        "campaign_id": campaign_id,
        "roster_id": roster_id,
        "token_hash": token_hash,
        "status": status,
        "expires_at": _ts(expires_at),
        "created_at": _ts(created_at),
        "consent_ok": bool(consent_ok),
        "updated_at": _now_iso(),
    }
    _request(
        "POST",
        "facial_enrollment_sessions",
        json_body=row,
        params="?on_conflict=id",
    )


def patch_session(
    session_id: str,
    *,
    status: Optional[str] = None,
    consent_ok: Optional[bool] = None,
) -> None:
    body: dict[str, Any] = {"updated_at": _now_iso()}
    if status is not None:
        body["status"] = status
    if consent_ok is not None:
        body["consent_ok"] = bool(consent_ok)
    sid = quote(session_id, safe="")
    _request("PATCH", "facial_enrollment_sessions", json_body=body, params=f"?id=eq.{sid}")


def patch_campaign(
    campaign_id: str,
    *,
    status: Optional[str] = None,
    revoked_at: Optional[float] = None,
) -> None:
    body: dict[str, Any] = {"updated_at": _now_iso()}
    if status is not None:
        body["status"] = status
    if revoked_at is not None:
        body["revoked_at"] = _ts(revoked_at)
    cid = quote(campaign_id, safe="")
    _request("PATCH", "facial_enrollment_campaigns", json_body=body, params=f"?id=eq.{cid}")


def sync_in_background(fn, *args, **kwargs) -> None:
    """Fire-and-forget so SQLite path stays fast."""

    def _run() -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("m2_ops_sync_bg_failed err=%s", exc)

    threading.Thread(target=_run, name="m2-ops-sync", daemon=True).start()
