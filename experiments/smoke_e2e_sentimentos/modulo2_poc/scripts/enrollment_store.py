"""Enrollment Escalavel A — F0 foundation store (POC, SQLite local).

Isolated under modulo2_poc/. No production DB, no biometrics in tokens.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from enrollment_tokens import (
    generate_campaign_token,
    generate_claim_code,
    get_hmac_secret,
    hash_token,
    mint_session_token,
    parse_and_verify_session_token,
    qr_path_for_campaign_token,
)

try:
    import enrollment_ops_sync as _ops_sync
except ImportError:  # pragma: no cover
    _ops_sync = None  # type: ignore

try:
    import enrollment_roster_source as _roster_src
except ImportError:  # pragma: no cover
    _roster_src = None  # type: ignore

# --- Public constants -------------------------------------------------------

ROSTER_PENDING = "pending"
ROSTER_CLAIMED = "claimed"
ROSTER_IN_PROGRESS = "in_progress"
ROSTER_COMPLETED = "completed"
ROSTER_FAILED = "failed"
ROSTER_EXPIRED = "expired"

CAMPAIGN_ACTIVE = "active"
CAMPAIGN_EXPIRED = "expired"
CAMPAIGN_REVOKED = "revoked"

SESSION_CREATED = "SESSION_CREATED"
SESSION_CONSENT_OK = "CONSENT_OK"
SESSION_CAPTURE = "CAPTURE"
SESSION_COMPLETED = "COMPLETED"
SESSION_EXPIRED = "EXPIRED"
SESSION_ABANDONED = "ABANDONED"
SESSION_FAILED = "FAILED"

# Uniform client-facing claim failure (anti-enumeration)
CLAIM_GENERIC_ERROR = "codigo invalido ou indisponivel"
CLAIM_RATE_LIMITED = "muitas tentativas; tente novamente mais tarde"
CLAIM_MISSING_CODE = "claim_code obrigatorio"

DEFAULT_CAMPAIGN_TTL_SEC = 8 * 3600
DEFAULT_SESSION_TTL_SEC = 30 * 60
DEFAULT_RATE_LIMIT_MAX = 10
DEFAULT_RATE_LIMIT_WINDOW_SEC = 60

MODULO2_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = MODULO2_ROOT / "data" / "fixtures" / "schools.json"
DEFAULT_DB_DIR = MODULO2_ROOT / "results" / "enrollment_escalavel"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "poc_enrollment.db"


@dataclass
class ClaimSuccess:
    display_name: str
    class_label: str
    school_name: str
    session_token: str
    session_expires_at: float
    roster_status: str
    # Internal ids intentionally omitted from UI-safe dict

    def ui_safe(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "class_label": self.class_label,
            "school_name": self.school_name,
            "session_token": self.session_token,
            "session_expires_at": self.session_expires_at,
            "roster_status": self.roster_status,
            "message": (
                f"Ola, {self.display_name}! "
                f"Voce esta realizando o cadastro facial da turma {self.class_label}."
            ),
        }


@dataclass
class ClaimFailure:
    error: str
    http_status: int = 400

    def as_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": self.error}


class EnrollmentStore:
    """Thread-safe SQLite store for campaigns, roster claims, and sessions."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        hmac_secret: Optional[str] = None,
        campaign_ttl_sec: float = DEFAULT_CAMPAIGN_TTL_SEC,
        session_ttl_sec: float = DEFAULT_SESSION_TTL_SEC,
        rate_limit_max: int = DEFAULT_RATE_LIMIT_MAX,
        rate_limit_window_sec: float = DEFAULT_RATE_LIMIT_WINDOW_SEC,
        fixtures_path: Path | str = DEFAULT_FIXTURES,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = get_hmac_secret(hmac_secret)
        self.campaign_ttl_sec = float(campaign_ttl_sec)
        self.session_ttl_sec = float(session_ttl_sec)
        self.rate_limit_max = int(rate_limit_max)
        self.rate_limit_window_sec = float(rate_limit_window_sec)
        self.fixtures_path = Path(fixtures_path)
        self._lock = threading.RLock()
        self._init_db()

    # -- schema --------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                # executescript auto-commits; do not wrap in BEGIN/COMMIT
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS campaigns (
                      id TEXT PRIMARY KEY,
                      school_id TEXT NOT NULL,
                      school_name TEXT NOT NULL,
                      class_group_id TEXT NOT NULL,
                      class_label TEXT NOT NULL,
                      campaign_token TEXT NOT NULL UNIQUE,
                      campaign_token_hash TEXT NOT NULL UNIQUE,
                      status TEXT NOT NULL,
                      expires_at REAL NOT NULL,
                      created_at REAL NOT NULL,
                      revoked_at REAL
                    );

                    CREATE TABLE IF NOT EXISTS roster (
                      id TEXT PRIMARY KEY,
                      campaign_id TEXT NOT NULL,
                      fixture_key TEXT,
                      student_id TEXT,
                      display_name TEXT NOT NULL,
                      claim_code TEXT NOT NULL,
                      status TEXT NOT NULL,
                      session_id TEXT,
                      claimed_at REAL,
                      completed_at REAL,
                      UNIQUE (campaign_id, claim_code),
                      FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
                    );

                    CREATE TABLE IF NOT EXISTS enrollment_sessions (
                      id TEXT PRIMARY KEY,
                      campaign_id TEXT NOT NULL,
                      roster_student_id TEXT NOT NULL,
                      token_hash TEXT NOT NULL UNIQUE,
                      status TEXT NOT NULL,
                      expires_at REAL NOT NULL,
                      created_at REAL NOT NULL,
                      consent_ok INTEGER NOT NULL DEFAULT 0,
                      FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                      FOREIGN KEY (roster_student_id) REFERENCES roster(id)
                    );

                    CREATE TABLE IF NOT EXISTS claim_rate_limit (
                      bucket_key TEXT NOT NULL,
                      window_start REAL NOT NULL,
                      hit_count INTEGER NOT NULL,
                      PRIMARY KEY (bucket_key, window_start)
                    );

                    CREATE INDEX IF NOT EXISTS idx_roster_campaign_status
                      ON roster(campaign_id, status);
                    CREATE INDEX IF NOT EXISTS idx_sessions_roster
                      ON enrollment_sessions(roster_student_id);
                    """
                )
                cols = {
                    r[1]
                    for r in conn.execute("PRAGMA table_info(campaigns)").fetchall()
                }
                if cols and "campaign_token" not in cols:
                    conn.executescript(
                        """
                        DROP TABLE IF EXISTS claim_rate_limit;
                        DROP TABLE IF EXISTS enrollment_sessions;
                        DROP TABLE IF EXISTS roster;
                        DROP TABLE IF EXISTS campaigns;
                        """
                    )
                    # recreate with F1 schema (campaign_token column)
                    conn.executescript(
                        """
                        CREATE TABLE campaigns (
                          id TEXT PRIMARY KEY,
                          school_id TEXT NOT NULL,
                          school_name TEXT NOT NULL,
                          class_group_id TEXT NOT NULL,
                          class_label TEXT NOT NULL,
                          campaign_token TEXT NOT NULL UNIQUE,
                          campaign_token_hash TEXT NOT NULL UNIQUE,
                          status TEXT NOT NULL,
                          expires_at REAL NOT NULL,
                          created_at REAL NOT NULL,
                          revoked_at REAL
                        );
                        CREATE TABLE roster (
                          id TEXT PRIMARY KEY,
                          campaign_id TEXT NOT NULL,
                          fixture_key TEXT,
                          student_id TEXT,
                          display_name TEXT NOT NULL,
                          claim_code TEXT NOT NULL,
                          status TEXT NOT NULL,
                          session_id TEXT,
                          claimed_at REAL,
                          completed_at REAL,
                          UNIQUE (campaign_id, claim_code),
                          FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
                        );
                        CREATE TABLE enrollment_sessions (
                          id TEXT PRIMARY KEY,
                          campaign_id TEXT NOT NULL,
                          roster_student_id TEXT NOT NULL,
                          token_hash TEXT NOT NULL UNIQUE,
                          status TEXT NOT NULL,
                          expires_at REAL NOT NULL,
                          created_at REAL NOT NULL,
                          consent_ok INTEGER NOT NULL DEFAULT 0,
                          FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                          FOREIGN KEY (roster_student_id) REFERENCES roster(id)
                        );
                        CREATE TABLE claim_rate_limit (
                          bucket_key TEXT NOT NULL,
                          window_start REAL NOT NULL,
                          hit_count INTEGER NOT NULL,
                          PRIMARY KEY (bucket_key, window_start)
                        );
                        """
                    )
                roster_cols = {
                    r[1]
                    for r in conn.execute("PRAGMA table_info(roster)").fetchall()
                }
                if roster_cols and "student_id" not in roster_cols:
                    conn.execute("ALTER TABLE roster ADD COLUMN student_id TEXT")
            finally:
                conn.close()

    # -- fixtures ------------------------------------------------------------

    def load_fixtures(self) -> dict[str, Any]:
        with self.fixtures_path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def list_schools(self) -> list[dict[str, Any]]:
        if _roster_src is not None:
            _mode, schools = _roster_src.list_schools(self.fixtures_path)
            self._last_roster_mode = _mode
            return schools
        # Legacy fallback
        data = self.load_fixtures()
        return [
            {"id": s["id"], "name": s["name"], "class_groups": s["class_groups"]}
            for s in data["schools"]
        ]

    def roster_source_mode(self) -> str:
        if getattr(self, "_last_roster_mode", None):
            return self._last_roster_mode
        if _roster_src is not None:
            try:
                return _roster_src.resolve_mode()
            except Exception:
                return "fixtures"
        return "fixtures"

    # -- campaign ------------------------------------------------------------

    def create_campaign(
        self,
        *,
        school_id: str,
        class_group_id: str,
        now: Optional[float] = None,
        campaign_ttl_sec: Optional[float] = None,
    ) -> dict[str, Any]:
        """Create campaign + roster claim codes. Returns campaign_token once (for QR)."""
        ts = time.time() if now is None else now
        ttl = self.campaign_ttl_sec if campaign_ttl_sec is None else float(campaign_ttl_sec)

        school, class_group = self._resolve_fixture(school_id, class_group_id)
        students = class_group.get("students") or []
        if not students:
            raise ValueError("turma sem alunos ativos — não é possível iniciar campanha vazia")

        campaign_id = str(uuid.uuid4())
        campaign_token = generate_campaign_token()
        token_hash = hash_token(campaign_token)
        expires_at = ts + ttl

        codes: set[str] = set()
        roster_rows: list[tuple] = []
        claim_sheet: list[dict[str, str]] = []

        for stu in students:
            code = generate_claim_code(codes)
            codes.add(code)
            rid = str(uuid.uuid4())
            student_id = stu.get("student_id")
            roster_rows.append(
                (
                    rid,
                    campaign_id,
                    stu.get("fixture_key") or stu.get("edge_student_key"),
                    student_id,
                    stu["display_name"],
                    code,
                    ROSTER_PENDING,
                )
            )
            claim_sheet.append(
                {"display_name": stu["display_name"], "claim_code": code}
            )

        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO campaigns (
                      id, school_id, school_name, class_group_id, class_label,
                      campaign_token, campaign_token_hash, status, expires_at,
                      created_at, revoked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        campaign_id,
                        school["id"],
                        school["name"],
                        class_group["id"],
                        class_group["label"],
                        campaign_token,
                        token_hash,
                        CAMPAIGN_ACTIVE,
                        expires_at,
                        ts,
                    ),
                )
                conn.executemany(
                    """
                    INSERT INTO roster (
                      id, campaign_id, fixture_key, student_id, display_name, claim_code, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    roster_rows,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

        if _ops_sync is not None:
            _ops_sync.sync_in_background(
                _ops_sync.upsert_campaign,
                campaign_id=campaign_id,
                school_id=school["id"],
                school_name=school["name"],
                class_group_id=class_group["id"],
                class_label=class_group["label"],
                campaign_token_hash=token_hash,
                status=CAMPAIGN_ACTIVE,
                expires_at=expires_at,
                created_at=ts,
                organization_id=school.get("organization_id"),
            )
            _ops_sync.sync_in_background(
                _ops_sync.upsert_roster_rows,
                [
                    {
                        "id": r[0],
                        "campaign_id": r[1],
                        "fixture_key": r[2],
                        "student_id": r[3],
                        "display_name": r[4],
                        "claim_code": r[5],
                        "status": r[6],
                    }
                    for r in roster_rows
                ],
            )

        return {
            "campaign_id": campaign_id,
            "campaign_token": campaign_token,
            "qr_path": qr_path_for_campaign_token(campaign_token),
            "school_name": school["name"],
            "class_label": class_group["label"],
            "expires_at": expires_at,
            "status": CAMPAIGN_ACTIVE,
            "claim_sheet": claim_sheet,
            "roster_count": len(roster_rows),
            "roster_source": self.roster_source_mode(),
        }

    def _resolve_fixture(
        self, school_id: str, class_group_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if _roster_src is not None:
            _mode, school, cg = _roster_src.resolve_class(
                school_id, class_group_id, fixtures_path=self.fixtures_path
            )
            self._last_roster_mode = _mode
            return school, cg
        for school in self.load_fixtures()["schools"]:
            if school["id"] != school_id:
                continue
            for cg in school["class_groups"]:
                if cg["id"] == class_group_id:
                    return school, cg
        raise KeyError(f"fixture not found: {school_id}/{class_group_id}")

    def get_campaign_public_by_token(
        self, campaign_token: str, *, now: Optional[float] = None
    ) -> Optional[dict[str, Any]]:
        """Public campaign info for /a/<token> — no roster names."""
        ts = time.time() if now is None else now
        self.sweep_expirations(now=ts)
        th = hash_token(campaign_token)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM campaigns WHERE campaign_token_hash = ?",
                    (th,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        status = self._effective_campaign_status(row, ts)
        return {
            "school_name": row["school_name"],
            "class_label": row["class_label"],
            "status": status,
            "expires_at": row["expires_at"],
            # Explicitly no student list / claim codes / internal ids for QR page
        }

    def revoke_campaign(self, campaign_id: str, *, now: Optional[float] = None) -> dict[str, Any]:
        ts = time.time() if now is None else now
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    """
                    UPDATE campaigns
                    SET status = ?, revoked_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (CAMPAIGN_REVOKED, ts, campaign_id, CAMPAIGN_ACTIVE),
                )
                changed = cur.rowcount
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        self.sweep_expirations(now=ts)
        if changed == 1 and _ops_sync is not None:
            _ops_sync.sync_in_background(
                _ops_sync.patch_campaign,
                campaign_id,
                status=CAMPAIGN_REVOKED,
                revoked_at=ts,
            )
        return {"campaign_id": campaign_id, "revoked": changed == 1, "status": CAMPAIGN_REVOKED}

    def get_campaign(self, campaign_id: str, *, now: Optional[float] = None) -> Optional[dict[str, Any]]:
        """Gestor view: campaign metadata + opaque token for QR (no biometrics)."""
        ts = time.time() if now is None else now
        self.sweep_expirations(now=ts)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM campaigns WHERE id = ?",
                    (campaign_id,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        status = self._effective_campaign_status(row, ts)
        progress = self.get_roster_progress(campaign_id)
        return {
            "campaign_id": row["id"],
            "school_id": row["school_id"],
            "school_name": row["school_name"],
            "class_group_id": row["class_group_id"],
            "class_label": row["class_label"],
            "campaign_token": row["campaign_token"],
            "qr_path": qr_path_for_campaign_token(row["campaign_token"]),
            "status": status,
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "revoked_at": row["revoked_at"],
            "total": progress["total"],
            "completed": progress["completed"],
            "items": progress["items"],
        }

    def _effective_campaign_status(self, row: sqlite3.Row, now: float) -> str:
        if row["status"] == CAMPAIGN_REVOKED:
            return CAMPAIGN_REVOKED
        if row["status"] == CAMPAIGN_EXPIRED or now > row["expires_at"]:
            return CAMPAIGN_EXPIRED
        return CAMPAIGN_ACTIVE

    # -- claim ---------------------------------------------------------------

    def claim(
        self,
        *,
        campaign_token: str,
        claim_code: Optional[str],
        client_ip: str = "127.0.0.1",
        now: Optional[float] = None,
    ) -> ClaimSuccess | ClaimFailure:
        """Atomic claim. claim_code is mandatory. Uniform errors (no enumeration)."""
        ts = time.time() if now is None else now

        if claim_code is None or str(claim_code).strip() == "":
            return ClaimFailure(error=CLAIM_MISSING_CODE, http_status=400)

        code = str(claim_code).strip()
        if not (code.isdigit() and len(code) == 6):
            # Still generic — do not reveal format details beyond required field
            return ClaimFailure(error=CLAIM_GENERIC_ERROR, http_status=400)

        self.sweep_expirations(now=ts)

        # Rate limit before DB claim (IP + campaign_token bucket)
        if not self._check_and_hit_rate_limit(
            f"ip:{client_ip}", now=ts
        ) or not self._check_and_hit_rate_limit(
            f"ct:{hash_token(campaign_token)[:16]}", now=ts
        ):
            return ClaimFailure(error=CLAIM_RATE_LIMITED, http_status=429)

        th = hash_token(campaign_token)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                camp = conn.execute(
                    "SELECT * FROM campaigns WHERE campaign_token_hash = ?",
                    (th,),
                ).fetchone()
                if camp is None:
                    conn.execute("COMMIT")
                    return ClaimFailure(error=CLAIM_GENERIC_ERROR, http_status=400)

                status = self._effective_campaign_status(camp, ts)
                if status != CAMPAIGN_ACTIVE:
                    if status == CAMPAIGN_EXPIRED and camp["status"] != CAMPAIGN_EXPIRED:
                        conn.execute(
                            "UPDATE campaigns SET status = ? WHERE id = ?",
                            (CAMPAIGN_EXPIRED, camp["id"]),
                        )
                    conn.execute("COMMIT")
                    return ClaimFailure(error=CLAIM_GENERIC_ERROR, http_status=400)

                # Peek for completed / in-use — always same error message
                row = conn.execute(
                    """
                    SELECT * FROM roster
                    WHERE campaign_id = ? AND claim_code = ?
                    """,
                    (camp["id"], code),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return ClaimFailure(error=CLAIM_GENERIC_ERROR, http_status=400)
                if row["status"] != ROSTER_PENDING:
                    conn.execute("COMMIT")
                    return ClaimFailure(error=CLAIM_GENERIC_ERROR, http_status=400)

                session_id = str(uuid.uuid4())
                session_exp = ts + self.session_ttl_sec
                session_token = mint_session_token(
                    session_id=session_id,
                    campaign_id=camp["id"],
                    roster_student_id=row["id"],
                    exp=session_exp,
                    secret=self._secret,
                )
                token_hash_val = hash_token(session_token)

                cur = conn.execute(
                    """
                    UPDATE roster
                    SET status = ?, claimed_at = ?, session_id = ?
                    WHERE campaign_id = ? AND claim_code = ? AND status = ?
                    """,
                    (
                        ROSTER_CLAIMED,
                        ts,
                        session_id,
                        camp["id"],
                        code,
                        ROSTER_PENDING,
                    ),
                )
                if cur.rowcount != 1:
                    # Lost race to concurrent claim
                    conn.execute("COMMIT")
                    return ClaimFailure(error=CLAIM_GENERIC_ERROR, http_status=409)

                conn.execute(
                    """
                    INSERT INTO enrollment_sessions (
                      id, campaign_id, roster_student_id, token_hash,
                      status, expires_at, created_at, consent_ok
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        session_id,
                        camp["id"],
                        row["id"],
                        token_hash_val,
                        SESSION_CREATED,
                        session_exp,
                        ts,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

        if _ops_sync is not None:
            roster_id = row["id"]
            camp_id = camp["id"]
            _ops_sync.sync_in_background(
                _ops_sync.patch_roster,
                roster_id,
                status=ROSTER_CLAIMED,
                session_id=session_id,
                claimed_at=ts,
            )
            _ops_sync.sync_in_background(
                _ops_sync.upsert_session,
                session_id=session_id,
                campaign_id=camp_id,
                roster_id=roster_id,
                token_hash=token_hash_val,
                status=SESSION_CREATED,
                expires_at=session_exp,
                created_at=ts,
                consent_ok=False,
            )

        return ClaimSuccess(
            display_name=row["display_name"],
            class_label=camp["class_label"],
            school_name=camp["school_name"],
            session_token=session_token,
            session_expires_at=session_exp,
            roster_status=ROSTER_CLAIMED,
        )

    def _check_and_hit_rate_limit(self, bucket_key: str, *, now: float) -> bool:
        """Return True if allowed; increments counter. Windowed fixed buckets."""
        window_start = now - (now % self.rate_limit_window_sec)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT hit_count FROM claim_rate_limit
                    WHERE bucket_key = ? AND window_start = ?
                    """,
                    (bucket_key, window_start),
                ).fetchone()
                count = int(row["hit_count"]) if row else 0
                if count >= self.rate_limit_max:
                    conn.execute("COMMIT")
                    return False
                if row:
                    conn.execute(
                        """
                        UPDATE claim_rate_limit
                        SET hit_count = hit_count + 1
                        WHERE bucket_key = ? AND window_start = ?
                        """,
                        (bucket_key, window_start),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO claim_rate_limit (bucket_key, window_start, hit_count)
                        VALUES (?, ?, 1)
                        """,
                        (bucket_key, window_start),
                    )
                conn.execute("COMMIT")
                return True
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    # -- session lifecycle ---------------------------------------------------

    def validate_session_token(
        self,
        session_token: str,
        *,
        now: Optional[float] = None,
        require_roster_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Verify HMAC binding + DB row. Optional require_roster_id detects hijack."""
        ts = time.time() if now is None else now
        self.sweep_expirations(now=ts)
        try:
            parts = parse_and_verify_session_token(
                session_token, secret=self._secret, now=ts
            )
        except ValueError as exc:
            raise PermissionError(str(exc)) from exc

        if require_roster_id is not None and parts.roster_student_id != require_roster_id:
            raise PermissionError("session token does not belong to this student")

        with self._lock:
            conn = self._connect()
            try:
                sess = conn.execute(
                    "SELECT * FROM enrollment_sessions WHERE id = ?",
                    (parts.session_id,),
                ).fetchone()
                camp = conn.execute(
                    "SELECT * FROM campaigns WHERE id = ?",
                    (parts.campaign_id,),
                ).fetchone()
                roster = conn.execute(
                    "SELECT * FROM roster WHERE id = ?",
                    (parts.roster_student_id,),
                ).fetchone()
            finally:
                conn.close()

        if sess is None or camp is None or roster is None:
            raise PermissionError("invalid session token")
        if hash_token(session_token) != sess["token_hash"]:
            raise PermissionError("invalid session token")
        if sess["roster_student_id"] != parts.roster_student_id:
            raise PermissionError("session token does not belong to this student")
        if sess["status"] in (SESSION_EXPIRED, SESSION_COMPLETED, SESSION_ABANDONED):
            raise PermissionError("session not active")
        if ts > sess["expires_at"]:
            raise PermissionError("session expired")
        camp_status = self._effective_campaign_status(camp, ts)
        if camp_status != CAMPAIGN_ACTIVE:
            raise PermissionError("campaign not active")

        return {
            "session_id": parts.session_id,
            "campaign_id": parts.campaign_id,
            "roster_student_id": parts.roster_student_id,
            "display_name": roster["display_name"],
            "roster_status": roster["status"],
            "session_status": sess["status"],
            "expires_at": sess["expires_at"],
        }

    def decline_identity(
        self, session_token: str, *, now: Optional[float] = None
    ) -> None:
        """'Nao sou eu' — abandon claimed session, return roster to pending."""
        ts = time.time() if now is None else now
        info = self.validate_session_token(session_token, now=ts)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                roster = conn.execute(
                    "SELECT status FROM roster WHERE id = ?",
                    (info["roster_student_id"],),
                ).fetchone()
                if roster and roster["status"] == ROSTER_COMPLETED:
                    conn.execute("COMMIT")
                    raise PermissionError("cannot decline completed enrollment")
                conn.execute(
                    """
                    UPDATE enrollment_sessions
                    SET status = ?
                    WHERE id = ?
                    """,
                    (SESSION_ABANDONED, info["session_id"]),
                )
                conn.execute(
                    """
                    UPDATE roster
                    SET status = ?, session_id = NULL, claimed_at = NULL
                    WHERE id = ? AND status IN (?, ?)
                    """,
                    (
                        ROSTER_PENDING,
                        info["roster_student_id"],
                        ROSTER_CLAIMED,
                        ROSTER_IN_PROGRESS,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def mark_in_progress(
        self, session_token: str, *, now: Optional[float] = None
    ) -> dict[str, Any]:
        ts = time.time() if now is None else now
        info = self.validate_session_token(session_token, now=ts)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    UPDATE roster SET status = ?
                    WHERE id = ? AND status IN (?, ?)
                    """,
                    (
                        ROSTER_IN_PROGRESS,
                        info["roster_student_id"],
                        ROSTER_CLAIMED,
                        ROSTER_IN_PROGRESS,
                    ),
                )
                conn.execute(
                    """
                    UPDATE enrollment_sessions SET status = ?
                    WHERE id = ? AND status IN (?, ?, ?)
                    """,
                    (
                        SESSION_CAPTURE,
                        info["session_id"],
                        SESSION_CREATED,
                        SESSION_CONSENT_OK,
                        SESSION_CAPTURE,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        if _ops_sync is not None:
            _ops_sync.sync_in_background(
                _ops_sync.patch_roster,
                info["roster_student_id"],
                status=ROSTER_IN_PROGRESS,
            )
            _ops_sync.sync_in_background(
                _ops_sync.patch_session,
                info["session_id"],
                status=SESSION_CAPTURE,
            )
        return self.validate_session_token(session_token, now=ts)

    def complete_enrollment(
        self, session_token: str, *, now: Optional[float] = None
    ) -> dict[str, Any]:
        """Mark roster completed; claim_code cannot be reused afterward."""
        ts = time.time() if now is None else now
        info = self.validate_session_token(session_token, now=ts)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    UPDATE roster
                    SET status = ?, completed_at = ?
                    WHERE id = ? AND status IN (?, ?)
                    """,
                    (
                        ROSTER_COMPLETED,
                        ts,
                        info["roster_student_id"],
                        ROSTER_CLAIMED,
                        ROSTER_IN_PROGRESS,
                    ),
                )
                conn.execute(
                    """
                    UPDATE enrollment_sessions SET status = ?
                    WHERE id = ?
                    """,
                    (SESSION_COMPLETED, info["session_id"]),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        if _ops_sync is not None:
            _ops_sync.sync_in_background(
                _ops_sync.patch_roster,
                info["roster_student_id"],
                status=ROSTER_COMPLETED,
                completed_at=ts,
            )
            _ops_sync.sync_in_background(
                _ops_sync.patch_session,
                info["session_id"],
                status=SESSION_COMPLETED,
            )
        return {
            "roster_student_id": info["roster_student_id"],
            "roster_status": ROSTER_COMPLETED,
            "session_status": SESSION_COMPLETED,
        }

    def get_roster_progress(self, campaign_id: str) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT display_name, claim_code, status, completed_at
                    FROM roster WHERE campaign_id = ?
                    ORDER BY display_name
                    """,
                    (campaign_id,),
                ).fetchall()
            finally:
                conn.close()
        items = [
            {
                "display_name": r["display_name"],
                "claim_code": r["claim_code"],
                "status": r["status"],
                "completed_at": r["completed_at"],
            }
            for r in rows
        ]
        total = len(items)
        done = sum(1 for i in items if i["status"] == ROSTER_COMPLETED)
        return {
            "campaign_id": campaign_id,
            "total": total,
            "completed": done,
            "items": items,
        }

    def get_roster_status_by_claim(
        self, campaign_id: str, claim_code: str
    ) -> Optional[str]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT status FROM roster
                    WHERE campaign_id = ? AND claim_code = ?
                    """,
                    (campaign_id, claim_code),
                ).fetchone()
            finally:
                conn.close()
        return None if row is None else row["status"]

    # -- expiration / sweep --------------------------------------------------

    def sweep_expirations(self, *, now: Optional[float] = None) -> dict[str, int]:
        """Expire campaigns/sessions; return claimed/in_progress → pending when session TTL hits."""
        ts = time.time() if now is None else now
        expired_campaigns = 0
        expired_sessions = 0
        released_roster = 0

        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    """
                    UPDATE campaigns SET status = ?
                    WHERE status = ? AND expires_at < ?
                    """,
                    (CAMPAIGN_EXPIRED, CAMPAIGN_ACTIVE, ts),
                )
                expired_campaigns = cur.rowcount

                # Sessions past TTL that are not terminal
                sess_rows = conn.execute(
                    """
                    SELECT id, roster_student_id FROM enrollment_sessions
                    WHERE expires_at < ?
                      AND status NOT IN (?, ?, ?, ?)
                    """,
                    (
                        ts,
                        SESSION_COMPLETED,
                        SESSION_EXPIRED,
                        SESSION_ABANDONED,
                        SESSION_FAILED,
                    ),
                ).fetchall()
                for s in sess_rows:
                    conn.execute(
                        "UPDATE enrollment_sessions SET status = ? WHERE id = ?",
                        (SESSION_EXPIRED, s["id"]),
                    )
                    expired_sessions += 1
                    # Release roster back to pending if not completed
                    cur2 = conn.execute(
                        """
                        UPDATE roster
                        SET status = ?, session_id = NULL, claimed_at = NULL
                        WHERE id = ? AND status IN (?, ?)
                        """,
                        (
                            ROSTER_PENDING,
                            s["roster_student_id"],
                            ROSTER_CLAIMED,
                            ROSTER_IN_PROGRESS,
                        ),
                    )
                    released_roster += cur2.rowcount

                # Mark non-completed roster as expired when campaign expired/revoked
                conn.execute(
                    """
                    UPDATE roster
                    SET status = ?
                    WHERE status NOT IN (?, ?)
                      AND campaign_id IN (
                        SELECT id FROM campaigns WHERE status IN (?, ?)
                      )
                    """,
                    (
                        ROSTER_EXPIRED,
                        ROSTER_COMPLETED,
                        ROSTER_EXPIRED,
                        CAMPAIGN_EXPIRED,
                        CAMPAIGN_REVOKED,
                    ),
                )

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

        return {
            "expired_campaigns": expired_campaigns,
            "expired_sessions": expired_sessions,
            "released_roster": released_roster,
        }
