"""Watchdog para monitorar múltiplos streams RTSP."""

import time
from typing import Dict
from app.rtsp.reader import RTSPReader
from app.logging import get_logger

logger = get_logger(__name__)


class RTSPWatchdog:
    """Monitora e gerencia múltiplos readers RTSP."""
    
    def __init__(self, readers: Dict[str, RTSPReader], check_interval: float = 10.0):
        self.readers = readers
        self.check_interval = check_interval
    
    def check_all(self) -> Dict[str, bool]:
        """Verifica todos os readers e reconecta se necessário."""
        results = {}
        for camera_id, reader in self.readers.items():
            was_connected = reader.is_connected
            is_now_connected = reader.ensure_connected()
            results[camera_id] = is_now_connected
            
            if not was_connected and is_now_connected:
                logger.info("rtsp_reconnected", camera_id=camera_id)
        
        return results
    
    def get_all_status(self) -> Dict[str, dict]:
        """Retorna status de todos os readers."""
        return {camera_id: reader.get_status() for camera_id, reader in self.readers.items()}
