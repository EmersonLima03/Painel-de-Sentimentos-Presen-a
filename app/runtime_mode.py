"""Modos de runtime: demo | offline | rtsp — nunca misturar dados simulados com real."""

from __future__ import annotations

import os
from enum import Enum


class RuntimeMode(str, Enum):
    DEMO = "demo"
    OFFLINE = "offline"
    RTSP = "rtsp"


def get_runtime_mode() -> RuntimeMode:
    raw = (os.environ.get("RUNTIME_MODE") or "").strip().lower()
    if not raw:
        try:
            from app.config import get_settings

            raw = str(getattr(get_settings(), "runtime_mode", "rtsp") or "rtsp").strip().lower()
        except Exception:
            raw = "rtsp"
    if raw not in {m.value for m in RuntimeMode}:
        return RuntimeMode.RTSP
    return RuntimeMode(raw)


def is_demo() -> bool:
    return get_runtime_mode() == RuntimeMode.DEMO


def is_simulated() -> bool:
    return get_runtime_mode() in (RuntimeMode.DEMO,)


DEMO_BANNER = "MODO DEMONSTRAÇÃO — DADOS SIMULADOS"
DISCLAIMER = (
    "Indicadores estimados a partir de sinais visuais. "
    "Não constituem diagnóstico, avaliação psicológica ou comprovação de aprendizagem."
)

# Nomes fictícios exclusivos do modo demo
DEMO_STUDENTS = [
    {"student_id": "demo-ana", "full_name": "Ana Lima"},
    {"student_id": "demo-bruno", "full_name": "Bruno Costa"},
    {"student_id": "demo-carla", "full_name": "Carla Souza"},
    {"student_id": "demo-daniel", "full_name": "Daniel Alves"},
    {"student_id": "demo-eduarda", "full_name": "Eduarda Rocha"},
    {"student_id": "demo-felipe", "full_name": "Felipe Martins"},
    {"student_id": "demo-gabriela", "full_name": "Gabriela Silva"},
    {"student_id": "demo-henrique", "full_name": "Henrique Santos"},
]
