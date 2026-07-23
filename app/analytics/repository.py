"""Writers de analytics — só quando experimental/demo habilitado; nunca no banco real sem flag."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Protocol


class AnalyticsRepository(Protocol):
    def write_observation_window(self, row: Dict[str, Any]) -> None: ...
    def write_behavioral_event(self, row: Dict[str, Any]) -> None: ...
    def write_climate_window(self, row: Dict[str, Any]) -> None: ...


class DemoSqliteAnalyticsRepository:
    """Persistência no banco demo separado."""

    def __init__(self, db_path: str):
        if Path(db_path).resolve().name == "dulino_edge.db":
            raise ValueError("DemoSqliteAnalyticsRepository cannot use production dulino_edge.db")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def write_observation_window(self, row: Dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO demo_observation_windows(
                    session_id, track_id, student_id, started_at, ended_at, state,
                    visual_attention_score, observation_quality, provenance_json
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.get("session_id"),
                    row.get("track_id"),
                    row.get("student_id"),
                    row.get("started_at"),
                    row.get("ended_at"),
                    row.get("state"),
                    row.get("visual_attention_score"),
                    row.get("observation_quality"),
                    json.dumps(row.get("provenance") or {}),
                ),
            )

    def write_behavioral_event(self, row: Dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO demo_behavioral_events(
                    event_id, event_type, student_id, track_id, severity, status,
                    confidence, observation_quality, evidence_json, started_at, ended_at, provenance_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["event_id"],
                    row.get("event_type"),
                    row.get("student_id"),
                    row.get("track_id"),
                    row.get("severity"),
                    row.get("status"),
                    row.get("confidence"),
                    row.get("observation_quality"),
                    json.dumps(row.get("evidence") or {}),
                    row.get("started_at"),
                    row.get("ended_at"),
                    json.dumps(row.get("provenance") or {}),
                ),
            )

    def write_climate_window(self, row: Dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO demo_climate_windows(session_id, started_at, ended_at, dominant_state, provenance_json)
                VALUES (?,?,?,?,?)
                """,
                (
                    row.get("session_id"),
                    row.get("started_at"),
                    row.get("ended_at"),
                    row.get("dominant_state"),
                    json.dumps(row.get("provenance") or {}),
                ),
            )


class NullAnalyticsRepository:
    def write_observation_window(self, row: Dict[str, Any]) -> None:
        return None

    def write_behavioral_event(self, row: Dict[str, Any]) -> None:
        return None

    def write_climate_window(self, row: Dict[str, Any]) -> None:
        return None
