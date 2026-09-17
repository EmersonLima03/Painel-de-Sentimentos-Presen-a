"""Worker de sincronização assíncrono — lane PRODUCT (cloud MVP)."""

from __future__ import annotations

import asyncio
import json
from typing import List, Optional

from app.config import get_settings
from app.db.init_db import close_session, get_session
from app.db.repo import EventRepository
from app.logging import get_logger
from app.sync.client import SupabaseClient
from app.sync.outbox_contract import CLOUD_MVP_PRIORITY_ORDER, CLOUD_MVP_SYNCABLE_TYPES

logger = get_logger(__name__)


class SyncWorker:
    """Sincroniza apenas tipos do contrato cloud MVP.

    Seleção: filter tipos sincronizáveis → ORDER BY prioridade/created_at → LIMIT.
    Telemetria (climate/engagement/…) permanece pending local e não bloqueia.
    """

    def __init__(self, client: Optional[SupabaseClient] = None):
        self.settings = get_settings()
        self.client = client or SupabaseClient()
        self.running = False
        self.batch_size = getattr(self.settings, "sync_batch_size", 10)
        self.retry_attempts = getattr(self.settings, "sync_retry_attempts", 3)
        self.retry_backoff = getattr(self.settings, "sync_retry_backoff_seconds", 5)
        self.sync_interval = getattr(self.settings, "sync_interval_seconds", 10)
        self.syncable_types = list(CLOUD_MVP_SYNCABLE_TYPES)
        self.priority_types = list(CLOUD_MVP_PRIORITY_ORDER)

    async def start(self) -> None:
        """Inicia worker de sincronização."""
        self.running = True
        logger.info(
            "sync_worker_started",
            syncable_types=self.syncable_types,
            batch_size=self.batch_size,
        )

        while self.running:
            try:
                await self.sync_batch()
                await asyncio.sleep(self.sync_interval)
            except Exception as e:
                logger.error("sync_worker_error", error=str(e))
                await asyncio.sleep(self.sync_interval)

    def stop(self) -> None:
        """Para worker."""
        self.running = False
        logger.info("sync_worker_stopped")

    def outbox_status(self) -> dict:
        """Diagnóstico: pending por lane (sem mutar dados)."""
        session = get_session()
        try:
            return EventRepository(session).get_outbox_lane_stats()
        finally:
            close_session(session)

    async def sync_batch(self) -> None:
        """Sincroniza um lote de eventos do lane product."""
        session = get_session()
        try:
            await self._sync_batch_with_session(session)
        finally:
            close_session(session)

    async def _sync_batch_with_session(self, session) -> None:
        event_repo = EventRepository(session)

        # CORRETO: filtrar tipos sincronizáveis ANTES do LIMIT
        pending_events = event_repo.get_pending_events(
            limit=self.batch_size,
            event_types=self.syncable_types,
            prioritize_types=self.priority_types,
        )

        if not pending_events:
            return

        logger.info(
            "sync_batch_start",
            count=len(pending_events),
            types=[e.event_type for e in pending_events],
        )

        for event in pending_events:
            try:
                payload = json.loads(event.payload_json)
                success = await self.client.send_event(payload)

                if success:
                    event_repo.mark_sent(event.event_id)
                    logger.info(
                        "event_synced",
                        event_id=event.event_id,
                        event_type=event.event_type,
                    )
                else:
                    current_retries = event.retries + 1
                    event.retries = current_retries
                    event.last_error = "Send failed"
                    session.commit()

                    if current_retries >= self.retry_attempts:
                        event_repo.mark_failed(event.event_id, "Max retries exceeded")
                        logger.warning(
                            "event_max_retries",
                            event_id=event.event_id,
                            retries=current_retries,
                        )
                    else:
                        backoff_time = self.retry_backoff * (2 ** (current_retries - 1))
                        logger.debug(
                            "event_retry_backoff",
                            event_id=event.event_id,
                            retry=current_retries,
                            backoff=backoff_time,
                        )
                        await asyncio.sleep(backoff_time)

            except Exception as e:
                logger.error("sync_event_error", event_id=event.event_id, error=str(e))
                if event.retries >= self.retry_attempts:
                    event_repo.mark_failed(event.event_id, str(e))
                else:
                    event.retries += 1
                    event.last_error = str(e)
                    session.commit()

        logger.info("sync_batch_complete", count=len(pending_events))
