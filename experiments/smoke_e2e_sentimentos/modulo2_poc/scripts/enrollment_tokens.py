"""HMAC helpers for Enrollment Escalavel A (POC only).

campaign_token: opaque random urlsafe string (never embeds student/biometrics).
session_token: opaque token bound via HMAC to campaign + roster + session + exp.
claim_code: 6-digit numeric string (not a token; generated separately).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional


DEFAULT_HMAC_ENV = "M2_ENROLL_HMAC_SECRET"
CLAIM_CODE_DIGITS = 6


def get_hmac_secret(explicit: Optional[str] = None) -> bytes:
    if explicit is not None:
        raw = explicit
    else:
        raw = os.environ.get(DEFAULT_HMAC_ENV, "").strip()
        if not raw:
            # POC fallback — tests/lab only; production must set env.
            raw = "poc-m2-enroll-dev-secret-not-for-prod"
    return raw.encode("utf-8")


def generate_campaign_token() -> str:
    """Opaque campaign identifier for QR path /a/<token>. No PII/biometrics."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Store-only fingerprint (SHA-256 hex)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_claim_code(existing: set[str]) -> str:
    """6-digit claim code unique within the provided set (per campaign)."""
    for _ in range(10_000):
        code = f"{secrets.randbelow(10**CLAIM_CODE_DIGITS):0{CLAIM_CODE_DIGITS}d}"
        if code not in existing:
            return code
    raise RuntimeError("unable to allocate unique claim_code")


def _b64url_nopad(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    import base64

    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


@dataclass(frozen=True)
class SessionTokenParts:
    session_id: str
    campaign_id: str
    roster_student_id: str
    exp: float


def mint_session_token(
    *,
    session_id: str,
    campaign_id: str,
    roster_student_id: str,
    exp: float,
    secret: Optional[bytes] = None,
) -> str:
    """Bind session to the correct roster student via HMAC.

    Format: base64url(session_id)|base64url(campaign_id)|base64url(roster_id)|exp|sig
    QR and claim_code never contain this token.
    """
    key = secret if secret is not None else get_hmac_secret()
    payload = (
        f"{session_id}|{campaign_id}|{roster_student_id}|{exp:.0f}"
    ).encode("utf-8")
    sig = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return "|".join(
        [
            _b64url_nopad(session_id.encode("utf-8")),
            _b64url_nopad(campaign_id.encode("utf-8")),
            _b64url_nopad(roster_student_id.encode("utf-8")),
            f"{exp:.0f}",
            sig,
        ]
    )


def parse_and_verify_session_token(
    token: str,
    *,
    secret: Optional[bytes] = None,
    now: Optional[float] = None,
) -> SessionTokenParts:
    """Verify HMAC binding. Raises ValueError on any invalid/expired token."""
    key = secret if secret is not None else get_hmac_secret()
    parts = token.split("|")
    if len(parts) != 5:
        raise ValueError("invalid session token")
    try:
        session_id = _b64url_decode(parts[0]).decode("utf-8")
        campaign_id = _b64url_decode(parts[1]).decode("utf-8")
        roster_student_id = _b64url_decode(parts[2]).decode("utf-8")
        exp = float(parts[3])
        sig = parts[4]
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid session token") from exc

    payload = (
        f"{session_id}|{campaign_id}|{roster_student_id}|{exp:.0f}"
    ).encode("utf-8")
    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("invalid session token")

    ts = time.time() if now is None else now
    if ts > exp:
        raise ValueError("session expired")

    return SessionTokenParts(
        session_id=session_id,
        campaign_id=campaign_id,
        roster_student_id=roster_student_id,
        exp=exp,
    )


def qr_path_for_campaign_token(campaign_token: str) -> str:
    """QR payload path: only opaque campaign token — never claim/student/bio."""
    if not campaign_token or "/" in campaign_token or ".." in campaign_token:
        raise ValueError("bad campaign_token")
    return f"/a/{campaign_token}"
