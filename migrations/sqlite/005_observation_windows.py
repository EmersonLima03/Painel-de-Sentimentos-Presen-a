"""
Migration 005 — tabelas tipadas de observação (Fase 6).
Idempotente. Não apaga dados existentes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


DDL = [
    """
    CREATE TABLE IF NOT EXISTS raw_observation_windows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        camera_id TEXT,
        track_id TEXT,
        student_id TEXT,
        started_at TEXT,
        ended_at TEXT,
        observation_coverage REAL,
        observation_quality REAL,
        head_pose_summary_json TEXT,
        facial_features_summary_json TEXT,
        expression_summary_json TEXT,
        object_summary_json TEXT,
        pose_summary_json TEXT,
        provider_versions_json TEXT,
        rule_engine_version TEXT,
        threshold_profile TEXT,
        camera_calibration_version TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS engagement_windows_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        camera_id TEXT,
        track_id TEXT,
        student_id TEXT,
        started_at TEXT,
        ended_at TEXT,
        visual_attention_score REAL,
        state TEXT,
        confidence REAL,
        observation_coverage REAL,
        observation_quality REAL,
        contributing_signals_json TEXT,
        exclusion_reasons_json TEXT,
        provider TEXT,
        model_name TEXT,
        model_version TEXT,
        rule_engine_version TEXT,
        threshold_profile TEXT,
        camera_calibration_version TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS climate_windows_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        camera_id TEXT,
        started_at TEXT,
        ended_at TEXT,
        dominant_state TEXT,
        positive_ratio REAL,
        neutral_ratio REAL,
        negative_ratio REAL,
        mixed_ratio REAL,
        inconclusive_ratio REAL,
        visible_people INTEGER,
        observable_people INTEGER,
        recognized_people INTEGER,
        observation_quality REAL,
        confidence REAL,
        provider TEXT,
        model_name TEXT,
        model_version TEXT,
        rule_engine_version TEXT,
        threshold_profile TEXT,
        camera_calibration_version TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_benchmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT,
        model_name TEXT,
        model_version TEXT,
        device TEXT,
        sample_count INTEGER,
        macro_f1 REAL,
        balanced_accuracy REAL,
        average_latency_ms REAL,
        p95_latency_ms REAL,
        throughput_fps REAL,
        memory_usage_mb REAL,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
]


def apply(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.cursor()
        for ddl in DDL:
            cur.execute(ddl)
        conn.commit()
    finally:
        conn.close()


TABLES_005 = (
    "raw_observation_windows",
    "engagement_windows_v2",
    "climate_windows_v2",
    "model_benchmarks",
)


def rollback(db_path: str) -> None:
    """Remove apenas tabelas da migration 005 (experimental). Não toca tabelas core."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        for name in TABLES_005:
            cur.execute(f"DROP TABLE IF EXISTS {name}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "rollback":
        rollback(sys.argv[2])
    else:
        apply(sys.argv[1] if len(sys.argv) > 1 else "./data/dulino_edge.db")
