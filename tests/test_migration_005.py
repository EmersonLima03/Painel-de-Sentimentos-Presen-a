"""Migration 005 experimental — apenas em DBs temporários (nunca dulino_edge.db)."""

from __future__ import annotations

import importlib.util
import shutil
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROD_DB = (ROOT / "data" / "dulino_edge.db").resolve()
MIG005 = ROOT / "migrations" / "sqlite" / "005_observation_windows.py"


def _load_005():
    spec = importlib.util.spec_from_file_location("migration_005_test", MIG005)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_migration_005_empty_db(tmp_path):
    mod = _load_005()
    db = tmp_path / "empty.db"
    assert db.resolve() != PROD_DB
    sqlite3.connect(str(db)).close()
    mod.apply(str(db))
    conn = sqlite3.connect(str(db))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for t in mod.TABLES_005:
        assert t in names
    mod.apply(str(db))  # idempotente
    mod.rollback(str(db))
    conn = sqlite3.connect(str(db))
    names2 = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for t in mod.TABLES_005:
        assert t not in names2


def test_migration_005_on_copy_of_existing(tmp_path):
    if not PROD_DB.exists():
        pytest.skip("production db missing")
    mod = _load_005()
    copy = tmp_path / "copy_edge.db"
    shutil.copy2(PROD_DB, copy)
    assert copy.resolve() != PROD_DB
    before = PROD_DB.stat().st_mtime_ns
    mod.apply(str(copy))
    after = PROD_DB.stat().st_mtime_ns
    assert before == after, "production DB must not be touched"
    conn = sqlite3.connect(str(copy))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in mod.TABLES_005:
        assert t in names
        conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
    conn.close()
    mod.rollback(str(copy))
    assert PROD_DB.stat().st_mtime_ns == before
