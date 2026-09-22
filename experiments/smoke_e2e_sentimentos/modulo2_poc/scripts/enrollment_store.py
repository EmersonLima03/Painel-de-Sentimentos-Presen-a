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

                    CREATE TABLE IF NOT EXISTS student_facial_status (
                      student_id TEXT PRIMARY KEY,
                      edge_student_key TEXT,
                      status TEXT NOT NULL,
                      version INTEGER NOT NULL DEFAULT 1,
                      completed_at REAL,
                      revoked_at REAL,
                      updated_at REAL NOT NULL
                    );
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
                sess_cols = {
                    r[1]
                    for r in conn.execute("PRAGMA table_info(enrollment_sessions)").fetchall()
                }
                if sess_cols and "invite_token_hash" not in sess_cols:
                    conn.execute(
                        "ALTER TABLE enrollment_sessions ADD COLUMN invite_token_hash TEXT"
                    )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS student_facial_status (
                      student_id TEXT PRIMARY KEY,
                      edge_student_key TEXT,
                      status TEXT NOT NULL,
                      version INTEGER NOT NULL DEFAULT 1,
                      completed_at REAL,
                      revoked_at REAL,
                      updated_at REAL NOT NULL
                    )
                    """
                )
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
        student_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Create campaign + roster claim codes. Returns campaign_token once (for QR).

        Optional student_ids restricts roster to those official students (product
        individual enrollment uses a 1-student campaign under the hood).
        """
        ts = time.time() if now is None else now
        ttl = self.campaign_ttl_sec if campaign_ttl_sec is None else float(campaign_ttl_sec)

        school, class_group = self._resolve_fixture(school_id, class_group_id)
        students = list(class_group.get("students") or [])
        if student_ids is not None:
            wanted = {str(x) for x in student_ids if x}
            students = [
                s
                for s in students
                if str(s.get("student_id") or "") in wanted
                or str(s.get("fixture_key") or "") in wanted
            ]
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
            # Sequential: campaign parent before roster children (avoids FK 409 race).
            _ops_sync.sync_in_background(
                _ops_sync.sync_create_campaign_and_roster,
                campaign_kwargs={
                    "campaign_id": campaign_id,
                    "school_id": school["id"],
                    "school_name": school["name"],
                    "class_group_id": class_group["id"],
                    "class_label": class_group["label"],
                    "campaign_token_hash": token_hash,
                    "status": CAMPAIGN_ACTIVE,
                    "expires_at": expires_at,
                    "created_at": ts,
                    "organization_id": school.get("organization_id"),
                },
                roster_rows=[
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

    def start_student_enrollment(
        self,
        *,
        school_id: str,
        class_group_id: str,
        student_id: str,
        now: Optional[float] = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        """Product path: individual enrollment for one official student.

        Internally uses a 1-student campaign + auto-claim + opaque invite token.
        The invite token is the only thing in the QR (/e/<token>).
        """
        import secrets as _secrets

        ts = time.time() if now is None else now
        sid = str(student_id).strip()
        if not sid:
            raise ValueError("student_id obrigatorio")

        school, class_group = self._resolve_fixture(school_id, class_group_id)
        match = None
        for stu in class_group.get("students") or []:
            if str(stu.get("student_id") or "") == sid:
                match = stu
                break
            if str(stu.get("fixture_key") or "") == sid:
                match = stu
                break
        if match is None:
            raise KeyError(f"aluno nao encontrado na turma: {sid}")

        if replace:
            self._mark_student_facial_local(
                str(match.get("student_id") or sid),
                edge_student_key=str(
                    match.get("fixture_key")
                    or match.get("edge_student_key")
                    or match.get("student_id")
                    or sid
                ),
                status="revoked",
                now=ts,
            )

        created = self.create_campaign(
            school_id=school_id,
            class_group_id=class_group_id,
            now=ts,
            student_ids=[str(match.get("student_id") or match.get("fixture_key") or sid)],
        )
        claim_code = (created.get("claim_sheet") or [{}])[0].get("claim_code")
        if not claim_code:
            raise RuntimeError("falha ao gerar claim_code individual")

        claimed = self.claim(
            campaign_token=created["campaign_token"],
            claim_code=claim_code,
            client_ip="127.0.0.1",
            now=ts,
        )
        if isinstance(claimed, ClaimFailure):
            raise RuntimeError(f"auto-claim falhou: {claimed.error}")

        invite_token = _secrets.token_urlsafe(32)
        invite_hash = hash_token(invite_token)
        info = self.validate_session_token(claimed.session_token, now=ts)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE enrollment_sessions
                    SET invite_token_hash = ?
                    WHERE id = ?
                    """,
                    (invite_hash, info["session_id"]),
                )
                conn.commit()
            finally:
                conn.close()

        edge_key = str(
            match.get("fixture_key")
            or match.get("edge_student_key")
            or match.get("student_id")
            or sid
        )
        self._mark_student_facial_local(
            str(match.get("student_id") or sid),
            edge_student_key=edge_key,
            status="in_progress",
            now=ts,
        )
        if _ops_sync is not None:
            _ops_sync.sync_in_background(
                _ops_sync.upsert_student_facial_status,
                student_id=str(match.get("student_id") or sid),
                edge_student_key=edge_key,
                status="in_progress",
                completed_at=None,
            )

        return {
            "ok": True,
            "mode": "student",
            "student_id": match.get("student_id") or sid,
            "display_name": match["display_name"],
            "school_id": school["id"],
            "school_name": school["name"],
            "class_group_id": class_group["id"],
            "class_label": class_group["label"],
            "edge_student_key": edge_key,
            "campaign_id": created["campaign_id"],
            "session_id": info["session_id"],
            "invite_token": invite_token,
            "qr_path": f"/e/{invite_token}",
            "expires_at": claimed.session_expires_at,
            "facial_status": "in_progress",
            "replace": bool(replace),
            "roster_source": self.roster_source_mode(),
        }

    def resolve_invite_token(
        self, invite_token: str, *, now: Optional[float] = None
    ) -> dict[str, Any]:
        """Resolve opaque /e/<token> invite into a live session (no PII in token)."""
        ts = time.time() if now is None else now
        th = hash_token(invite_token)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT s.id, s.campaign_id, s.roster_student_id, s.token_hash,
                           s.status, s.expires_at, s.invite_token_hash,
                           r.display_name, r.fixture_key, r.student_id AS official_student_id,
                           r.status AS roster_status,
                           c.school_name, c.class_label,
                           c.status AS camp_status, c.expires_at AS camp_expires_at,
                           c.revoked_at AS camp_revoked_at
                    FROM enrollment_sessions s
                    JOIN roster r ON r.id = s.roster_student_id
                    JOIN campaigns c ON c.id = s.campaign_id
                    WHERE s.invite_token_hash = ?
                    """,
                    (th,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            raise PermissionError("convite invalido ou expirado")
        if row["status"] in (SESSION_COMPLETED, "REVOKED", "DECLINED"):
            raise PermissionError("convite invalido ou expirado")
        if float(row["expires_at"]) < ts:
            raise PermissionError("convite invalido ou expirado")
        camp_row = {
            "status": row["camp_status"],
            "expires_at": row["camp_expires_at"],
            "revoked_at": row["camp_revoked_at"],
        }
        camp_status = self._effective_campaign_status(camp_row, ts)
        if camp_status != CAMPAIGN_ACTIVE:
            raise PermissionError("convite invalido ou expirado")

        # Remint session_token for client use (HMAC binding still enforced).
        session_token = mint_session_token(
            session_id=row["id"],
            campaign_id=row["campaign_id"],
            roster_student_id=row["roster_student_id"],
            exp=float(row["expires_at"]),
            secret=self._secret,
        )
        if hash_token(session_token) != row["token_hash"]:
            # Token material changed (secret rotation) — refuse rather than invent.
            raise PermissionError("convite invalido ou expirado")
        return {
            "session_token": session_token,
            "display_name": row["display_name"],
            "school_name": row["school_name"],
            "class_label": row["class_label"],
            "expires_at": row["expires_at"],
            "roster_status": row["roster_status"],
            "student_id": row["official_student_id"],
            "fixture_key": row["fixture_key"],
        }

    def revoke_student_invite(
        self, *, student_id: str, campaign_id: Optional[str] = None, now: Optional[float] = None
    ) -> dict[str, Any]:
        ts = time.time() if now is None else now
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                if campaign_id:
                    conn.execute(
                        """
                        UPDATE campaigns SET status = ?, revoked_at = ?
                        WHERE id = ? AND status = ?
                        """,
                        (CAMPAIGN_REVOKED, ts, campaign_id, CAMPAIGN_ACTIVE),
                    )
                else:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT c.id FROM campaigns c
                        JOIN roster r ON r.campaign_id = c.id
                        WHERE r.student_id = ? AND c.status = ?
                        """,
                        (str(student_id), CAMPAIGN_ACTIVE),
                    ).fetchall()
                    for r in rows:
                        conn.execute(
                            """
                            UPDATE campaigns SET status = ?, revoked_at = ?
                            WHERE id = ?
                            """,
                            (CAMPAIGN_REVOKED, ts, r["id"]),
                        )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        self._mark_student_facial_local(
            str(student_id), edge_student_key="", status="revoked", now=ts
        )
        if _ops_sync is not None:
            _ops_sync.sync_in_background(
                _ops_sync.upsert_student_facial_status,
                student_id=str(student_id),
                edge_student_key="",
                status="revoked",
                completed_at=None,
            )
        return {"ok": True, "student_id": student_id, "status": "revoked"}

    def _mark_student_facial_local(
        self,
        student_id: str,
        *,
        edge_student_key: str,
        status: str,
        now: float,
        completed_at: Optional[float] = None,
    ) -> None:
        if not student_id:
            return
        with self._lock:
            conn = self._connect()
            try:
                prev = conn.execute(
                    "SELECT version FROM student_facial_status WHERE student_id = ?",
                    (student_id,),
                ).fetchone()
                version = int(prev["version"]) + 1 if prev else 1
                revoked_at = now if status == "revoked" else None
                done_at = completed_at if status == "enrolled" else None
                conn.execute(
                    """
                    INSERT INTO student_facial_status (
                      student_id, edge_student_key, status, version,
                      completed_at, revoked_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(student_id) DO UPDATE SET
                      edge_student_key = excluded.edge_student_key,
                      status = excluded.status,
                      version = excluded.version,
                      completed_at = COALESCE(excluded.completed_at, student_facial_status.completed_at),
                      revoked_at = excluded.revoked_at,
                      updated_at = excluded.updated_at
                    """,
                    (
                        student_id,
                        edge_student_key or None,
                        status,
                        version,
                        done_at,
                        revoked_at,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_class_facial_status(
        self, school_id: str, class_group_id: str
    ) -> dict[str, Any]:
        """Official class roster + facial enrollment product status."""
        school, class_group = self._resolve_fixture(school_id, class_group_id)
        students = list(class_group.get("students") or [])

        # Latest operational roster status per student_id / fixture_key
        ops: dict[str, str] = {}
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT r.student_id, r.fixture_key, r.status, r.completed_at, c.created_at
                    FROM roster r
                    JOIN campaigns c ON c.id = r.campaign_id
                    WHERE c.school_id = ? AND c.class_group_id = ?
                    ORDER BY c.created_at DESC
                    """,
                    (school_id, class_group_id),
                ).fetchall()
                local_status = {
                    r["student_id"]: r["status"]
                    for r in conn.execute(
                        "SELECT student_id, status FROM student_facial_status"
                    ).fetchall()
                }
            finally:
                conn.close()
        for r in rows:
            key = str(r["student_id"] or r["fixture_key"] or "")
            if key and key not in ops:
                ops[key] = r["status"]

        items: list[dict[str, Any]] = []
        for stu in students:
            sid = str(stu.get("student_id") or "")
            edge_key = str(
                stu.get("fixture_key")
                or stu.get("edge_student_key")
                or sid
                or ""
            )
            enrolled = False
            try:
                from enrollment_promote import edge_student_has_embeddings

                enrolled = edge_student_has_embeddings(edge_key)
            except Exception:
                enrolled = False

            local = local_status.get(sid) if sid else None
            roster_st = ops.get(sid) or ops.get(edge_key)

            if enrolled or local == "enrolled":
                facial = "enrolled"
            elif local == "revoked" and not enrolled:
                facial = "not_enrolled"
            elif roster_st in (ROSTER_CLAIMED, ROSTER_IN_PROGRESS) or local == "in_progress":
                facial = "in_progress"
            elif roster_st == ROSTER_COMPLETED and not enrolled:
                # Completed POC but not promoted — treat as not permanently enrolled
                facial = "not_enrolled"
            else:
                facial = "not_enrolled"

            items.append(
                {
                    "student_id": sid or None,
                    "display_name": stu.get("display_name"),
                    "edge_student_key": edge_key or None,
                    "facial_status": facial,
                    "action": (
                        "recadastrar"
                        if facial == "enrolled"
                        else ("aguardar" if facial == "in_progress" else "cadastrar")
                    ),
                }
            )

        return {
            "ok": True,
            "school_id": school["id"],
            "school_name": school["name"],
            "class_group_id": class_group["id"],
            "class_label": class_group["label"],
            "roster_source": self.roster_source_mode(),
            "students": items,
            "total": len(items),
            "enrolled": sum(1 for i in items if i["facial_status"] == "enrolled"),
            "in_progress": sum(1 for i in items if i["facial_status"] == "in_progress"),
            "not_enrolled": sum(1 for i in items if i["facial_status"] == "not_enrolled"),
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
            # Sequential: roster patch before session upsert (FK child).
            _ops_sync.sync_in_background(
                _ops_sync.sync_claim,
                roster_id=row["id"],
                session_id=session_id,
                campaign_id=camp["id"],
                token_hash=token_hash_val,
                claimed_at=ts,
                expires_at=session_exp,
                created_at=ts,
                roster_status=ROSTER_CLAIMED,
                session_status=SESSION_CREATED,
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
            "fixture_key": roster["fixture_key"] if "fixture_key" in roster.keys() else None,
            "student_id": roster["student_id"] if "student_id" in roster.keys() else None,
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

            def _sync_in_progress() -> None:
                _ops_sync.patch_roster(
                    info["roster_student_id"], status=ROSTER_IN_PROGRESS
                )
                _ops_sync.patch_session(info["session_id"], status=SESSION_CAPTURE)

            _ops_sync.sync_in_background(_sync_in_progress)
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

            def _sync_complete() -> None:
                _ops_sync.patch_roster(
                    info["roster_student_id"],
                    status=ROSTER_COMPLETED,
                    completed_at=ts,
                )
                _ops_sync.patch_session(
                    info["session_id"], status=SESSION_COMPLETED
                )

            _ops_sync.sync_in_background(_sync_complete)

        # Promote TEMP gallery → Edge face_embeddings (official matcher path).
        promote_result: dict[str, Any] = {"ok": False, "skipped": True}
        try:
            from enrollment_promote import promote_completed_enrollment

            edge_key = info.get("fixture_key") or ""
            promote_result = promote_completed_enrollment(
                campaign_id=str(info["campaign_id"]),
                roster_student_id=str(info["roster_student_id"]),
                edge_student_key=str(edge_key),
                display_name=str(info.get("display_name") or edge_key),
                replace=True,
                call_reload=True,
            )
            official_sid = info.get("student_id")
            if promote_result.get("ok"):
                self._mark_student_facial_local(
                    str(official_sid or edge_key),
                    edge_student_key=str(edge_key),
                    status="enrolled",
                    now=ts,
                    completed_at=ts,
                )
            if (
                _ops_sync is not None
                and promote_result.get("ok")
                and official_sid
            ):
                _ops_sync.sync_in_background(
                    _ops_sync.upsert_student_facial_status,
                    student_id=str(official_sid),
                    edge_student_key=str(edge_key),
                    status="enrolled",
                    completed_at=ts,
                )
        except Exception as exc:  # noqa: BLE001 — enrollment complete must not fail on promote
            promote_result = {"ok": False, "error": str(exc)}

        return {
            "roster_student_id": info["roster_student_id"],
            "roster_status": ROSTER_COMPLETED,
            "session_status": SESSION_COMPLETED,
            "promote": promote_result,
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
