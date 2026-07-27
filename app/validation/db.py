"""SQLite isolado para validação manual — nunca usa dulino_edge.db."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_sessions (
    id TEXT PRIMARY KEY,
    operator TEXT,
    camera_id TEXT,
    student_id TEXT,
    started_at REAL,
    ended_at REAL,
    runtime_mode TEXT,
    providers_json TEXT,
    versions_json TEXT,
    thresholds_json TEXT,
    overall_result TEXT,
    notes TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS validation_steps (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    scenario_key TEXT NOT NULL,
    scenario_name TEXT,
    sort_order INTEGER,
    expected_json TEXT,
    instruction TEXT,
    duration_expected REAL,
    started_at REAL,
    ended_at REAL,
    duration_real REAL,
    result TEXT,
    observation TEXT,
    received_json TEXT,
    evidence_json TEXT,
    snapshot_start_json TEXT,
    snapshot_end_json TEXT,
    FOREIGN KEY(session_id) REFERENCES validation_sessions(id)
);

CREATE TABLE IF NOT EXISTS validation_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    step_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    ts REAL,
    payload_json TEXT,
    FOREIGN KEY(step_id) REFERENCES validation_steps(id)
);

CREATE TABLE IF NOT EXISTS validation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    summary_json TEXT,
    created_at REAL,
    FOREIGN KEY(session_id) REFERENCES validation_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_val_steps_session ON validation_steps(session_id);
CREATE INDEX IF NOT EXISTS idx_val_samples_step ON validation_samples(step_id);
"""


def validation_db_path() -> Path:
    settings = get_settings()
    raw = getattr(settings, "validation_db_path", None) or "./data/validation/validation.db"
    path = Path(raw)
    if path.name == "dulino_edge.db" or "dulino_edge" in path.name:
        raise ValueError("validation DB must not be production dulino_edge.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def connect() -> sqlite3.Connection:
    path = validation_db_path()
    if path.name == "dulino_edge.db":
        raise ValueError("refusing production DB")
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_validation_db() -> Path:
    with _lock:
        path = validation_db_path()
        conn = connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            logger.info("validation_db_ready", path=str(path))
        finally:
            conn.close()
        return path
