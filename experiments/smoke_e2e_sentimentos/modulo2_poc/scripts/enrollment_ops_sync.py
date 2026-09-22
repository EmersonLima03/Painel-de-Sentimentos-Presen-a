"""Dual-write of M2 operational enrollment state to Supabase A (presence).

Never writes biometrics/embeddings. SQLite remains the local runtime source;
Supabase A is the durable operational mirror for campaign/roster/session status.

Env:
  M2_OPS_SUPABASE_URL          (fallback: SUPABASE_URL)
  M2_OPS_SUPABASE_SERVICE_KEY  (fallback: SUPABASE_SERVICE_ROLE_KEY)

Idempotency notes
-----------------
PostgREST upsert with ``on_conflict=id`` only merges on primary key.
Secondary uniques (roster: campaign_id+claim_code, sessions: token_hash)
and FK races (roster before campaign exists) yield HTTP 409.

Strategy:
1. Callers must order dependent writes (campaign → roster → session).
2. POST upsert on PK; on 409, PATCH by primary key if the row exists.
3. If 409 and PK row absent → secondary unique owned by another row:
   log and refuse to overwrite (never swap students).
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


def reset_config_for_tests() -> None:
    """Clear cached configure() state (unit tests only)."""
    global _ENABLED, _BASE, _KEY
    with _lock:
        _ENABLED = None
        _BASE = ""
        _KEY = ""


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
            logger.warning(
                "m2_ops_sync_DISABLED reason=missing_url_or_service_key "
                "(SQLite local continua; configure SUPABASE_SERVICE_ROLE_KEY para dual-write)"
            )
            return False
        _BASE = base
        _KEY = key
        _ENABLED = True
        logger.info("m2_ops_sync_ENABLED base=%s", base)
        return True


def configured() -> bool:
    return _configure()


def _headers(*, upsert: bool = False) -> dict[str, str]:
    h = {
        "apikey": _KEY,
        "Authorization": f"Bearer {_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if upsert:
        # Prefer merge only on POST upsert — do not attach to PATCH.
        h["Prefer"] = "resolution=merge-duplicates,return=minimal"
    else:
        h["Prefer"] = "return=minimal"
    return h


def _request(
    method: str,
    path: str,
    *,
    json_body: Any = None,
    params: str = "",
    upsert: bool = False,
) -> tuple[bool, int, str]:
    """Returns (ok, http_status, body_or_err). Never raises to sync callers."""
    if not _configure():
        return False, 0, "sync_disabled"
    try:
        import urllib.error
        import urllib.request

        url = f"{_BASE}/rest/v1/{path}{params}"
        data = None
        headers = _headers(upsert=upsert)
        if json_body is not None:
            import json as _json

            data = _json.dumps(json_body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=8) as resp:
            code = int(getattr(resp, "status", 200) or 200)
            body = resp.read().decode("utf-8", errors="replace")
        logger.info("m2_ops_sync_OK method=%s path=%s status=%s", method, path, code)
        return True, code, body
    except Exception as exc:  # noqa: BLE001 — never break enrollment on sync failure
        code = 0
        detail = str(exc)
        try:
            import urllib.error

            if isinstance(exc, urllib.error.HTTPError):
                code = int(exc.code)
                try:
                    detail = exc.read().decode("utf-8", errors="replace") or detail
                except Exception:
                    pass
        except Exception:
            pass
        logger.error(
            "m2_ops_sync_FAIL method=%s path=%s status=%s err=%s",
            method,
            path,
            code or "?",
            detail[:500],
        )
        return False, code, detail


def _row_exists(path: str, row_id: str) -> bool:
    rid = quote(row_id, safe="")
    ok, code, body = _request(
        "GET",
        path,
        params=f"?id=eq.{rid}&select=id",
    )
    if not ok or code != 200:
        return False
    body = (body or "").strip()
    return body not in ("", "[]", "null")


def _upsert_by_id(path: str, row: dict[str, Any], *, row_id: str) -> bool:
    """POST upsert on PK; on 409, PATCH by id if row exists (idempotent retry).

    If 409 and row id is absent, another row owns a secondary unique — refuse
    to overwrite (no student swap).
    """
    ok, code, _ = _request(
        "POST",
        path,
        json_body=row,
        params="?on_conflict=id",
        upsert=True,
    )
    if ok:
        return True
    if code != 409:
        return False
    if not _row_exists(path, row_id):
        logger.error(
            "m2_ops_sync_CONFLICT_OTHER path=%s id=%s "
            "(409 sem linha no PK — unique secundária de outro registro; sem overwrite)",
            path,
            row_id,
        )
        return False
    rid = quote(row_id, safe="")
    ok2, _, _ = _request(
        "PATCH",
        path,
        json_body=row,
        params=f"?id=eq.{rid}",
        upsert=False,
    )
    return ok2


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
    _upsert_by_id("facial_enrollment_campaigns", row, row_id=campaign_id)


def upsert_roster_rows(rows: list[dict[str, Any]]) -> None:
    """Upsert roster one-by-one (PK) so one conflict cannot abort the batch."""
    if not rows:
        return
    for r in rows:
        row = {
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
        _upsert_by_id("facial_enrollment_roster", row, row_id=str(r["id"]))


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
    _request(
        "PATCH",
        "facial_enrollment_roster",
        json_body=body,
        params=f"?id=eq.{rid}",
        upsert=False,
    )


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
    _upsert_by_id("facial_enrollment_sessions", row, row_id=session_id)


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
    _request(
        "PATCH",
        "facial_enrollment_sessions",
        json_body=body,
        params=f"?id=eq.{sid}",
        upsert=False,
    )


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
    _request(
        "PATCH",
        "facial_enrollment_campaigns",
        json_body=body,
        params=f"?id=eq.{cid}",
        upsert=False,
    )


def sync_create_campaign_and_roster(
    *,
    campaign_kwargs: dict[str, Any],
    roster_rows: list[dict[str, Any]],
) -> None:
    """Ordered dual-write: campaign first (FK parent), then roster."""
    upsert_campaign(**campaign_kwargs)
    upsert_roster_rows(roster_rows)


def sync_claim(
    *,
    roster_id: str,
    session_id: str,
    campaign_id: str,
    token_hash: str,
    claimed_at: float,
    expires_at: float,
    created_at: float,
    roster_status: str = "claimed",
    session_status: str = "CREATED",
) -> None:
    """Ordered dual-write: roster patch first, then session upsert (FK child)."""
    patch_roster(
        roster_id,
        status=roster_status,
        session_id=session_id,
        claimed_at=claimed_at,
    )
    upsert_session(
        session_id=session_id,
        campaign_id=campaign_id,
        roster_id=roster_id,
        token_hash=token_hash,
        status=session_status,
        expires_at=expires_at,
        created_at=created_at,
        consent_ok=False,
    )


def sync_in_background(fn, *args, **kwargs) -> None:
    """Fire-and-forget so SQLite path stays fast."""

    def _run() -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("m2_ops_sync_bg_failed err=%s", exc)

    threading.Thread(target=_run, name="m2-ops-sync", daemon=True).start()
