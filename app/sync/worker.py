"""Worker de sincronização assíncrono — lanes PRODUCT (Sentimentos) + LXP (simulador)."""

from __future__ import annotations

import asyncio
import json
from typing import Optional, Sequence

from app.config import get_settings
from app.db.init_db import close_session, get_session
from app.db.repo import EventRepository
from app.integrations.attendance_lxp import LXP_ATTENDANCE_EVENT_TYPE, LxpAttendanceClient
from app.logging import get_logger
from app.sync.client import SupabaseClient
from app.sync.outbox_contract import (
    CLOUD_MVP_PRIORITY_ORDER,
    CLOUD_MVP_SYNCABLE_TYPES,
    LXP_SYNCABLE_TYPES,
    SYNC_WORKER_TYPES,
)

logger = get_logger(__name__)


class SyncWorker:
    """Sincroniza tipos product → Sentimentos e lxp_attendance_event → Simulator.

    Lanes são processadas de forma independente: falha 401 no ingest A
    não deve impedir envio de presença ao LXP B.
    """

    def __init__(
        self,
        client: Optional[SupabaseClient] = None,
        lxp_client: Optional[LxpAttendanceClient] = None,
    ):
        self.settings = get_settings()
        self.client = client or SupabaseClient()
        self.lxp_client = lxp_client or LxpAttendanceClient()
        self.running = False
        self.batch_size = getattr(self.settings, "sync_batch_size", 10)
        self.retry_attempts = getattr(self.settings, "sync_retry_attempts", 3)
        self.retry_backoff = getattr(self.settings, "sync_retry_backoff_seconds", 5)
        self.sync_interval = getattr(self.settings, "sync_interval_seconds", 10)
        self.syncable_types = list(SYNC_WORKER_TYPES)

    async def start(self) -> None:
        """Inicia worker de sincronização."""
        self.running = True
        logger.info(
            "sync_worker_started",
            syncable_types=self.syncable_types,
            batch_size=self.batch_size,
            lanes=["lxp", "product"],
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
        """Sincroniza um lote de eventos product + lxp (lanes isoladas)."""
        session = get_session()
        try:
            await self._sync_batch_with_session(session)
        finally:
            close_session(session)

    async def _dispatch(self, payload: dict) -> bool:
        et = str(payload.get("event_type") or "")
        if et == LXP_ATTENDANCE_EVENT_TYPE:
            return await self.lxp_client.send_attendance_event(payload)
        return await self.client.send_event(payload)

    async def _sync_batch_with_session(self, session) -> None:
        # LXP primeiro e isolado — não compete com fila product (ex.: snapshots 401)
        await self._sync_lane(
            session,
            event_types=LXP_SYNCABLE_TYPES,
            prioritize_types=LXP_SYNCABLE_TYPES,
            lane="lxp",
        )
        await self._sync_lane(
            session,
            event_types=CLOUD_MVP_SYNCABLE_TYPES,
            prioritize_types=CLOUD_MVP_PRIORITY_ORDER,
            lane="product",
        )

    async def _sync_lane(
        self,
        session,
        *,
        event_types: Sequence[str],
        prioritize_types: Sequence[str],
        lane: str,
    ) -> None:
        event_repo = EventRepository(session)

        pending_events = event_repo.get_pending_events(
            limit=self.batch_size,
            event_types=list(event_types),
            prioritize_types=list(prioritize_types),
        )

        if not pending_events:
            return

        logger.info(
            "sync_batch_start",
            lane=lane,
            count=len(pending_events),
            types=[e.event_type for e in pending_events],
        )

        for event in pending_events:
            try:
                payload = json.loads(event.payload_json)
                success = await self._dispatch(payload)

                if success:
                    event_repo.mark_sent(event.event_id)
                    logger.info(
                        "event_synced",
                        lane=lane,
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
                            lane=lane,
                            event_id=event.event_id,
                            retries=current_retries,
                        )
                    else:
                        backoff_time = self.retry_backoff * (2 ** (current_retries - 1))
                        logger.debug(
                            "event_retry_backoff",
                            lane=lane,
                            event_id=event.event_id,
                            retry=current_retries,
                            backoff=backoff_time,
                        )
                        await asyncio.sleep(backoff_time)

            except Exception as e:
                logger.error(
                    "sync_event_error",
                    lane=lane,
                    event_id=event.event_id,
                    error=str(e),
                )
                if event.retries >= self.retry_attempts:
                    event_repo.mark_failed(event.event_id, str(e))
                else:
                    event.retries += 1
                    event.last_error = str(e)
                    session.commit()

        logger.info("sync_batch_complete", lane=lane, count=len(pending_events))
