"""Testes leves do agregador de homologação LXP (sem TRI, sem produção)."""

from urllib.parse import urlparse

from app.api.homolog_lxp import PROD_HOST_MARKERS, _host_from_url, _outbox_counts


def test_prod_host_markers_block_sistemadulino():
    assert any(m in "https://sde.sistemadulino.com.br/x" for m in PROD_HOST_MARKERS)


def test_host_from_simulator_url():
    h = _host_from_url(
        "https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events"
    )
    assert h == "zasbmqwwkecmjbebejev.supabase.co"


def test_outbox_counts():
    events = [
        {"status": "pending", "retries": 1},
        {"status": "sent", "retries": 0},
        {"status": "sent", "retries": 2},
        {"status": "failed", "retries": 3},
    ]
    c = _outbox_counts(events)
    assert c["pending"] == 1
    assert c["sent"] == 2
    assert c["failed"] == 1
    assert c["retries_total"] == 6
    assert c["total"] == 4


def test_urlparse_not_prod_for_simulator():
    host = urlparse(
        "https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events"
    ).hostname
    assert host and not any(m in host for m in PROD_HOST_MARKERS)
