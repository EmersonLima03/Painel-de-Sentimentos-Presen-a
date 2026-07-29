"""Confirma overlay PRESENCA_CONFIG_OVERLAY e env de expressão TRI."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import reload_settings

tri = pytest.mark.tri


@tri
def test_config_tri_yaml_exists():
    assert Path("config.tri.yaml").is_file()


@tri
def test_presenca_config_overlay_merges_fer_onnx(monkeypatch):
    monkeypatch.setenv("PRESENCA_CONFIG_OVERLAY", "config.tri.yaml")
    monkeypatch.delenv("EXPRESSION_PROVIDER", raising=False)
    monkeypatch.delenv("EXPRESSION_FALLBACK_CHAIN", raising=False)
    monkeypatch.delenv("MODULE_EXPRESSION_MODE", raising=False)
    s = reload_settings()
    assert s.expression_provider == "fer_onnx"
    assert "fer_onnx" in (s.expression_fallback_chain or "")
    assert "hsemotion" not in (s.expression_fallback_chain or "").lower()
    assert s.module_expression_mode == "debug"


@tri
def test_expression_env_names_exact(monkeypatch):
    monkeypatch.delenv("PRESENCA_CONFIG_OVERLAY", raising=False)
    monkeypatch.setenv("EXPRESSION_PROVIDER", "fer_onnx")
    monkeypatch.setenv("EXPRESSION_FALLBACK_CHAIN", "fer_onnx")
    monkeypatch.setenv("MODULE_EXPRESSION_MODE", "debug")
    s = reload_settings()
    assert s.expression_provider == "fer_onnx"
    assert s.expression_fallback_chain == "fer_onnx"
    assert s.module_expression_mode == "debug"


@tri
def test_expression_provider_alone_does_not_silent_fallback_chain(monkeypatch):
    """Só EXPRESSION_PROVIDER=fer_onnx força chain fer_onnx (sem HSEmotion silencioso)."""
    monkeypatch.delenv("PRESENCA_CONFIG_OVERLAY", raising=False)
    monkeypatch.delenv("EXPRESSION_FALLBACK_CHAIN", raising=False)
    monkeypatch.setenv("EXPRESSION_PROVIDER", "fer_onnx")
    monkeypatch.setenv("MODULE_EXPRESSION_MODE", "debug")
    s = reload_settings()
    assert s.expression_provider == "fer_onnx"
    assert s.expression_fallback_chain == "fer_onnx"
