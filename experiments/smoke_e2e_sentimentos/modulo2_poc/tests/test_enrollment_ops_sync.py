"""enrollment_ops_sync: no-op without credentials; timestamps format."""

import enrollment_ops_sync as sync


def test_ops_sync_disabled_without_env(monkeypatch):
    monkeypatch.delenv("M2_OPS_SUPABASE_URL", raising=False)
    monkeypatch.delenv("M2_OPS_SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    sync.reset_config_for_tests()
    assert sync.configured() is False
    # Must not raise
    sync.upsert_campaign(
        campaign_id="c1",
        school_id="s",
        school_name="S",
        class_group_id="g",
        class_label="G",
        campaign_token_hash="h",
        status="active",
        expires_at=1.0,
        created_at=1.0,
    )


def test_ts_iso():
    assert sync._ts(None) is None
    assert "T" in sync._ts(1700000000.0)
