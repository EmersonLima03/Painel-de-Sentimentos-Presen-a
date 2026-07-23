"""Modos de módulo: disabled | debug | shadow | production."""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class ModuleMode(str, Enum):
    DISABLED = "disabled"
    DEBUG = "debug"
    SHADOW = "shadow"
    PRODUCTION = "production"


ALLOWED_MODES = {m.value for m in ModuleMode}


def parse_module_mode(value: str | None, default: ModuleMode = ModuleMode.DISABLED) -> ModuleMode:
    if value is None or str(value).strip() == "":
        return default
    v = str(value).strip().lower()
    if v not in ALLOWED_MODES:
        raise ValueError(f"Invalid module mode: {value!r}. Allowed: {sorted(ALLOWED_MODES)}")
    return ModuleMode(v)


def is_active(mode: ModuleMode) -> bool:
    return mode != ModuleMode.DISABLED


def exposes_debug(mode: ModuleMode) -> bool:
    return mode in (ModuleMode.DEBUG, ModuleMode.SHADOW, ModuleMode.PRODUCTION)


def persists_shadow_or_prod(mode: ModuleMode) -> bool:
    return mode in (ModuleMode.SHADOW, ModuleMode.PRODUCTION)


def is_production(mode: ModuleMode) -> bool:
    return mode == ModuleMode.PRODUCTION


def assert_max_shadow_after_spike(mode: ModuleMode) -> None:
    """Pós-spike o máximo inicial permitido é shadow."""
    if mode == ModuleMode.PRODUCTION:
        raise ValueError(
            "Providers cannot be promoted directly to production after spike; max is shadow"
        )


def validate_modes(modes: Iterable[str]) -> None:
    for m in modes:
        parse_module_mode(m)
