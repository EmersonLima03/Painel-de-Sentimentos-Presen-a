"""Utilitários para geração de IDs."""

import uuid
from datetime import datetime, timezone


def generate_event_id() -> str:
    """Gera UUID v4 para eventos (simulando v7 se necessário)."""
    # Para MVP, usamos UUID v4. Em produção, considerar uuid7 quando disponível.
    return str(uuid.uuid4())


def generate_uuid() -> str:
    """Gera UUID padrão."""
    return str(uuid.uuid4())
