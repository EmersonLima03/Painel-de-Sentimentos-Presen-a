"""Worker de sincronização assíncrono."""

import asyncio
import json
import time
from typing import List
from app.db.init_db import get_session
from app.db.repo import EventRepository
from app.sync.client import SupabaseClient
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


class SyncWorker:
    """Worker que sincroniza eventos pendentes com Supabase."""
    
    def __init__(self):
        self.settings = get_settings()
        self.client = SupabaseClient()
        self.running = False
        self.batch_size = getattr(self.settings, 'sync_batch_size', 10)
        self.retry_attempts = getattr(self.settings, 'sync_retry_attempts', 3)
        self.retry_backoff = getattr(self.settings, 'sync_retry_backoff_seconds', 5)
        self.sync_interval = getattr(self.settings, 'sync_interval_seconds', 10)
    
    async def start(self) -> None:
        """Inicia worker de sincronização."""
        self.running = True
        logger.info("sync_worker_started")
        
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
    
    async def sync_batch(self) -> None:
        """Sincroniza um lote de eventos."""
        session = get_session()
        event_repo = EventRepository(session)
        
        # Buscar eventos pendentes
        pending_events = event_repo.get_pending_events(limit=self.batch_size)
        
        if not pending_events:
            return
        
        # Filtrar por whitelist se configurado
        settings = get_settings()
        if settings.event_types_whitelist:
            whitelist = [t.strip() for t in settings.event_types_whitelist.split(",") if t.strip()]
            pending_events = [e for e in pending_events if e.event_type in whitelist]
        
        if not pending_events:
            return
        
        logger.info("sync_batch_start", count=len(pending_events))
        
        for event in pending_events:
            try:
                # Parse payload
                payload = json.loads(event.payload_json)
                
                # Tentar enviar
                success = await self.client.send_event(payload)
                
                if success:
                    event_repo.mark_sent(event.event_id)
                    logger.info("event_synced", event_id=event.event_id)
                else:
                    # Incrementar retry
                    current_retries = event.retries + 1
                    event.retries = current_retries
                    event.last_error = "Send failed"
                    session.commit()
                    
                    # Marcar como falho se excedeu tentativas
                    if current_retries >= self.retry_attempts:
                        event_repo.mark_failed(event.event_id, "Max retries exceeded")
                        logger.warning("event_max_retries", event_id=event.event_id, retries=current_retries)
                    else:
                        # Backoff exponencial
                        backoff_time = self.retry_backoff * (2 ** (current_retries - 1))
                        logger.debug("event_retry_backoff", event_id=event.event_id, retry=current_retries, backoff=backoff_time)
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
