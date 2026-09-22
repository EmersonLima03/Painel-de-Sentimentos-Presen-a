"""Unit tests for M2 gestor gate RBAC (no live Supabase)."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture()
def gate_client(monkeypatch):
    monkeypatch.setenv("M2_GESTOR_OPEN", "0")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test")

    # Reset settings cache if any
    from app import config

    config.get_settings.cache_clear() if hasattr(config.get_settings, "cache_clear") else None

    from app.m2_proxy import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_gate_rejects_without_token(gate_client):
    r = gate_client.post("/dashboard/api/m2-gestor-gate", json={})
    assert r.status_code == 401


def test_gate_rejects_professor_role(gate_client, monkeypatch):
    async def fake_get(url, headers=None):
        resp = MagicMock()
        if "/auth/v1/user" in url:
            resp.status_code = 200
            resp.json.return_value = {"id": "user-prof"}
        elif "/profiles" in url:
            resp.status_code = 200
            resp.json.return_value = [{"is_platform_admin": False, "status": "active"}]
        elif "/organization_memberships" in url:
            resp.status_code = 200
            resp.json.return_value = []
        elif "/memberships" in url:
            resp.status_code = 200
            resp.json.return_value = [{"role": "professor", "school_id": "sch-1"}]
        else:
            resp.status_code = 404
            resp.json.return_value = {}
        return resp

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=fake_get)

    with patch("app.m2_proxy.httpx.AsyncClient", return_value=mock_client):
        r = gate_client.post(
            "/dashboard/api/m2-gestor-gate",
            json={"access_token": "tok", "school_id": "sch-1"},
        )
    assert r.status_code == 403


def test_gate_allows_gestor_role(gate_client):
    async def fake_get(url, headers=None):
        resp = MagicMock()
        if "/auth/v1/user" in url:
            resp.status_code = 200
            resp.json.return_value = {"id": "user-gestor"}
        elif "/profiles" in url:
            resp.status_code = 200
            resp.json.return_value = [{"is_platform_admin": False, "status": "active"}]
        elif "/organization_memberships" in url:
            resp.status_code = 200
            resp.json.return_value = []
        elif "/memberships" in url:
            resp.status_code = 200
            resp.json.return_value = [{"role": "gestor", "school_id": "sch-1"}]
        else:
            resp.status_code = 404
            resp.json.return_value = {}
        return resp

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=fake_get)

    with patch("app.m2_proxy.httpx.AsyncClient", return_value=mock_client):
        r = gate_client.post(
            "/dashboard/api/m2-gestor-gate",
            json={"access_token": "tok", "school_id": "sch-1"},
        )
    assert r.status_code == 200
    assert r.json().get("ok") is True
    assert "m2_gestor_gate" in r.cookies
