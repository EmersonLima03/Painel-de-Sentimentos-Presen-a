"""Contrato cloud MVP do outbox — tipos sincronizáveis vs telemetria local.

Não apaga histórico. TRI/relatórios locais leem a tabela events
independentemente de pending/sent.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# Lane PRODUCT — enviados ao ingest Sentimentos no MVP
CLOUD_MVP_SYNCABLE_TYPES: Tuple[str, ...] = (
    "class_session_upsert",
    "session_event_upsert",
    "session_report_snapshot",
    "device_heartbeat",
)

# Lane LXP — enviados ao Attendance Simulator (não ao ingest Sentimentos)
LXP_SYNCABLE_TYPES: Tuple[str, ...] = (
    "lxp_attendance_event",
)

# Ordem de prioridade dentro do lane product (menor = primeiro)
CLOUD_MVP_PRIORITY_ORDER: Tuple[str, ...] = CLOUD_MVP_SYNCABLE_TYPES

# Telemetria / legado: permanecem no SQLite local; NÃO entram no SyncWorker cloud
TELEMETRY_LOCAL_TYPES: FrozenSet[str] = frozenset(
    {
        "climate_window",
        "engagement_window",
        "behavioral_event",
        "attendance_checkin",
        "test",
    }
)

CLOUD_MVP_SYNCABLE_SET: FrozenSet[str] = frozenset(CLOUD_MVP_SYNCABLE_TYPES)
LXP_SYNCABLE_SET: FrozenSet[str] = frozenset(LXP_SYNCABLE_TYPES)

# Tipos que o SyncWorker seleciona (product + lxp)
SYNC_WORKER_TYPES: Tuple[str, ...] = CLOUD_MVP_SYNCABLE_TYPES + LXP_SYNCABLE_TYPES
SYNC_WORKER_PRIORITY: Tuple[str, ...] = CLOUD_MVP_SYNCABLE_TYPES + LXP_SYNCABLE_TYPES


def classify_outbox_lane(event_type: str) -> str:
    """product | lxp | telemetry | ignored (outros)."""
    if event_type in CLOUD_MVP_SYNCABLE_SET:
        return "product"
    if event_type in LXP_SYNCABLE_SET:
        return "lxp"
    if event_type in TELEMETRY_LOCAL_TYPES:
        return "telemetry"
    return "ignored"
