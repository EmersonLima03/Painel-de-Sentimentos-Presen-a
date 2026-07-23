"""Migration 004 — sessão, behavioral_events, consent, sightings."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def run_migration(db_path: str) -> None:
    path = Path(db_path)
    if not path.exists():
        return
    conn = sqlite3.connect(str(path))
    try:
        if not _has_column(conn, "attendance_cache", "session_id"):
            conn.execute("ALTER TABLE attendance_cache ADD COLUMN session_id TEXT")
        if not _has_column(conn, "attendance_cache", "sightings"):
            conn.execute("ALTER TABLE attendance_cache ADD COLUMN sightings INTEGER DEFAULT 1")
        conn.commit()
    finally:
        conn.close()
