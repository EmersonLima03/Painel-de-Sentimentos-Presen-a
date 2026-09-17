"""
Testes de contrato Sentimentos v1 (persistência/outbox) — sem TRI.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.session_persistence import (
    SNAPSHOT_SCHEMA_VERSION,
    enqueue_class_session_upsert,
    enqueue_outbox,
    enqueue_report_snapshot,
    enqueue_session_event_upsert,
)


def test_session_persistence_module_importable():
    assert SNAPSHOT_SCHEMA_VERSION == 1
    assert callable(enqueue_outbox)
    assert callable(enqueue_class_session_upsert)
    assert callable(enqueue_session_event_upsert)
    assert callable(enqueue_report_snapshot)


def test_orchestrator_wires_session_id_not_none():
    """Guarda: sink oficial não deve hardcodar session_id=None."""
    text = Path("app/pipeline/orchestrator.py").read_text(encoding="utf-8")
    assert "session_id=None" not in text
    assert "session_id=self.active_session_id" in text


def test_ingest_function_source_exists():
    src = Path("supabase/functions/ingest-events/index.ts").read_text(encoding="utf-8")
    assert "class_session_upsert" in src
    assert "session_event_upsert" in src
    assert "session_report_snapshot" in src
    assert "forbidden_fields" in src or "hasForbiddenPayload" in src


def test_migrations_present():
    mig = Path("supabase/migrations")
    names = [p.name for p in mig.glob("*.sql")]
    assert any("secure_rls_auto_enable" in n for n in names)
    assert any("sentimentos_core_schema" in n for n in names)
    assert any("sentimentos_rls" in n for n in names)


def test_live_session_bind_api():
    from app.services.live_session import LiveSessionStore

    store = LiveSessionStore()
    old = store.session_id
    store.bind_session_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert store.session_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert store.session_id != old
