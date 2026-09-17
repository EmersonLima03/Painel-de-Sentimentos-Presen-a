"""Cliente HTTP para Supabase."""

import httpx
from typing import Dict, Optional
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


class SupabaseClient:
    """Cliente para enviar eventos ao Supabase."""
    
    def __init__(self):
        self.settings = get_settings()
        self.url = self.settings.supabase_ingest_url
        self.token = self.settings.device_token
        self.timeout = 10.0
    
    async def send_event(self, event_payload: Dict) -> bool:
        """
        Envia evento para Supabase (ou mock endpoint).
        
        Retorna: True se sucesso, False caso contrário.
        """
        if not self.url:
            logger.warning("supabase_not_configured")
            return False
        
        # Headers: usar anon key para passar validação inicial do Supabase
        # O Supabase exige Authorization header ANTES da function executar
        # Usamos anon key para passar, e validamos token real via query parameter na function
        headers = {"Content-Type": "application/json"}
        
        # Se tiver anon key, usar para passar validação inicial
        if self.settings.supabase_anon_key:
            headers["apikey"] = self.settings.supabase_anon_key
            headers["Authorization"] = f"Bearer {self.settings.supabase_anon_key}"
            logger.debug("using_anon_key_for_auth", has_anon_key=True)
        else:
            logger.warning("no_anon_key_configured", message="SUPABASE_ANON_KEY not set, requests may fail")
        
        # Construir URL com token real como query parameter (validação na function)
        url_with_token = self.url
        if self.token:
            separator = "&" if "?" in self.url else "?"
            url_with_token = f"{self.url}{separator}token={self.token}"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url_with_token,
                    json=event_payload,
                    headers=headers
                )
                
                if response.status_code in [200, 201]:
                    # Idempotência: inserted | duplicate | ignored contam como sucesso
                    try:
                        body = response.json()
                        st = str(body.get("status") or "")
                        if st in ("unauthorized", "invalid", "retryable_error"):
                            logger.error("event_send_rejected", body=body, event_id=event_payload.get("event_id"))
                            return False
                    except Exception:
                        pass
                    logger.info("event_sent", event_id=event_payload.get("event_id"), url=self.url)
                    return True
                elif response.status_code == 409:
                    logger.info("event_duplicate", event_id=event_payload.get("event_id"))
                    return True
                else:
                    error_text = response.text[:500] if hasattr(response, 'text') else str(response.status_code)
                    logger.error("event_send_failed", 
                                 status_code=response.status_code,
                                 response=error_text,
                                 url=self.url,
                                 event_id=event_payload.get("event_id"),
                                 event_type=event_payload.get("event_type"))
                    return False
                    
        except httpx.TimeoutException:
            logger.warning("supabase_timeout", url=self.url)
            return False
        except Exception as e:
            logger.error("supabase_error", error=str(e), url=self.url)
            return False
    
    def send_event_sync(self, event_payload: Dict) -> bool:
        """Versão síncrona (para testes)."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.send_event(event_payload))
