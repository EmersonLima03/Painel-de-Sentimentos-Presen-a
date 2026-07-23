"""Fixtures isoladas — nenhum teste toca data/dulino_edge.db."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Bloqueia path de produção nos testes
_PRODUCTION_DB = Path("data/dulino_edge.db").resolve()


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """SQLite temporário por teste + reset do singleton."""
    from app.config import get_settings, reload_settings
    from app.db import init_db
    from app.db.init_db import init_database, get_session, reset_db_singleton, close_session

    db_file = tmp_path / "test_edge.db"
    assert db_file.resolve() != _PRODUCTION_DB

    monkeypatch.setenv("SQLITE_PATH", str(db_file))
    # Evita aplicar 005 no fluxo padrão de init durante testes unitários de presença/fila
    monkeypatch.delenv("EXPERIMENTAL_SQLITE_005", raising=False)

    reset_db_singleton()
    reload_settings()
    settings = get_settings()
    object.__setattr__(settings, "sqlite_path", str(db_file))

    init_database(apply_experimental_005=False)
    assert Path(settings.sqlite_path).resolve() != _PRODUCTION_DB

    session = get_session()
    try:
        yield session
    finally:
        close_session(session)
        reset_db_singleton()
