"""M2 proxy: only selected prefixes; no catch-all; no collision with core Edge routes."""

from app.m2_proxy import is_m2_proxy_path


def test_m2_proxy_allowlist():
    assert is_m2_proxy_path("/gestor")
    assert is_m2_proxy_path("/gestor/")
    assert is_m2_proxy_path("/gestor-static/app.js")
    assert is_m2_proxy_path("/a/abc.token")
    assert is_m2_proxy_path("/aluno-static/x.js")
    assert is_m2_proxy_path("/api/gestor/campaigns")
    assert is_m2_proxy_path("/api/aluno/claim")
    assert is_m2_proxy_path("/m2/healthz")


def test_m2_proxy_does_not_swallow_core_routes():
    for path in (
        "/dashboard",
        "/dashboard/api/live",
        "/debug/vision",
        "/debug/mjpeg",
        "/health",
        "/api/v1/live",
        "/static/x",
        "/assets/index.js",
        "/homolog/simulator-admin",
        "/",
        "/docs",
    ):
        assert not is_m2_proxy_path(path), path
