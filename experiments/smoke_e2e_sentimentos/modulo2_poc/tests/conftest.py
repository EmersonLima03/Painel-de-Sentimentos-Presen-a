"""Force fixture roster for unit/API tests (no live Supabase A dependency)."""
import os

import pytest


@pytest.fixture(autouse=True)
def _force_fixture_roster(monkeypatch):
    monkeypatch.setenv("M2_ROSTER_SOURCE", "fixtures")
    # Avoid accidental dual-write during unit tests
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("M2_OPS_SUPABASE_SERVICE_KEY", raising=False)
    try:
        import enrollment_ops_sync as sync

        sync.reset_config_for_tests()
    except Exception:
        pass
