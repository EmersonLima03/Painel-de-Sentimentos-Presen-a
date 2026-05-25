"""Leitor RTSP com reconexão robusta. Também suporta webcam (device index)."""

import sys
import cv2
import time
from typing import Optional, Tuple, Any
from threading import Lock
from app.logging import get_logger

logger = get_logger(__name__)

# No Windows, câmeras virtuais (ex.: Iriun Webcam) podem precisar de backend explícito
_WINDOWS = sys.platform == "win32"
if _WINDOWS:
    try:
        _CAP_DSHOW = cv2.CAP_DSHOW
    except AttributeError:
        _CAP_DSHOW = None
    try:
        _CAP_MSMF = cv2.CAP_MSMF
    except AttributeError:
        _CAP_MSMF = None
else:
    _CAP_DSHOW = _CAP_MSMF = None


class RTSPReader:
    """Leitor RTSP com reconexão automática. Suporta webcam (índice) e fallback para default."""
    
    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        reconnect_delay: float = 5.0,
        default_camera_index: int = 0,
        webcam_width: Optional[int] = None,
        webcam_height: Optional[int] = None,
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.reconnect_delay = reconnect_delay
        self.default_camera_index = default_camera_index
        self.webcam_width = webcam_width
        self.webcam_height = webcam_height
        self.cap: Optional[cv2.VideoCapture] = None
        self.lock = Lock()
        self.is_connected = False
        self.last_frame_time = 0.0
        self.frame_count = 0
        self.last_error: Optional[str] = None
        self.is_webcam = False
        self.device_index: Optional[int] = None
        
        try:
            device_idx = int((rtsp_url or "").strip())
            if device_idx >= 0:
                self.is_webcam = True
                self.device_index = device_idx
                logger.info("rtsp_reader_webcam", camera_id=camera_id, device_index=device_idx)
        except (ValueError, AttributeError, TypeError):
            self.is_webcam = False
            self.device_index = None

    def _apply_webcam_resolution(self) -> None:
        """Solicita resolução ao driver (webcam/USB); o driver pode ajustar ao modo mais próximo."""
        if not self.cap or not self.is_webcam:
            return
        w, h = self.webcam_width, self.webcam_height
        if w is None or h is None or w <= 0 or h <= 0:
            return
        try:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(w))
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(h))
        except Exception:
            pass
    
    def connect(self) -> bool:
        """Conecta ao stream RTSP ou webcam."""
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            
            try:
                if self.is_webcam and self.device_index is not None:
                    logger.info("rtsp_connecting_webcam", camera_id=self.camera_id, device_index=self.device_index)
                    # No Windows: tentar backends que funcionam melhor com câmera virtual (Iriun, etc.)
                    if _WINDOWS and _CAP_DSHOW is not None:
                        self.cap = cv2.VideoCapture(self.device_index, _CAP_DSHOW)
                    else:
                        self.cap = cv2.VideoCapture(self.device_index)
                    self._apply_webcam_resolution()
                    ret, frame = self.cap.read() if self.cap is not None else (False, None)
                    if (not ret or frame is None) and _WINDOWS and _CAP_MSMF is not None:
                        if self.cap:
                            self.cap.release()
                            self.cap = None
                        logger.info("rtsp_webcam_try_msmf", camera_id=self.camera_id, device_index=self.device_index)
                        self.cap = cv2.VideoCapture(self.device_index, _CAP_MSMF)
                        self._apply_webcam_resolution()
                    # Webcam não precisa de timeout
                else:
                    logger.info("rtsp_connecting", camera_id=self.camera_id, url=self.rtsp_url)
                    self.cap = cv2.VideoCapture(self.rtsp_url)
                    # Timeout de conexão (5 segundos) - só para RTSP
                    try:
                        self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                    except:
                        pass  # Algumas versões do OpenCV não suportam
                
                # Configurar buffer (reduzir latência)
                try:
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except:
                    pass

                # Testar leitura
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    self.is_connected = True
                    self.last_error = None
                    self.last_frame_time = time.time()
                    source_type = "webcam" if self.is_webcam else "rtsp"
                    logger.info("rtsp_connected", camera_id=self.camera_id, source=source_type)
                    return True

                # Webcam: fallback para default se índice atual falhou (ex.: iPhone não conectado)
                if self.is_webcam and self.device_index is not None and self.device_index != self.default_camera_index:
                    self.cap.release()
                    self.cap = None
                    logger.warning("camera_open_failed", camera_id=self.camera_id, device_index=self.device_index, fallback_to_default=self.default_camera_index)
                    self.device_index = self.default_camera_index
                    if _WINDOWS and _CAP_DSHOW is not None:
                        self.cap = cv2.VideoCapture(self.device_index, _CAP_DSHOW)
                    else:
                        self.cap = cv2.VideoCapture(self.device_index)
                    try:
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    except Exception:
                        pass
                    self._apply_webcam_resolution()
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        self.is_connected = True
                        self.last_error = None
                        self.last_frame_time = time.time()
                        logger.info("rtsp_connected", camera_id=self.camera_id, source="webcam_fallback", device_index=self.device_index)
                        return True

                if self.cap:
                    self.cap.release()
                    self.cap = None
                self.is_connected = False
                self.last_error = "Failed to read initial frame"
                logger.warning("rtsp_connection_failed", camera_id=self.camera_id, error=self.last_error)
                return False

            except Exception as e:
                self.is_connected = False
                self.last_error = str(e)
                logger.error("rtsp_connection_error", camera_id=self.camera_id, error=str(e))
                if self.cap:
                    self.cap.release()
                    self.cap = None
                return False
    
    def read_frame(self) -> Tuple[bool, Optional[Any]]:
        """Lê um frame do stream.
        
        Returns:
            Tuple[bool, Optional[Any]]: (sucesso, frame) ou (False, None)
        """
        with self.lock:
            if not self.is_connected or self.cap is None:
                return False, None
            
            try:
                ret, frame = self.cap.read()
                
                if ret and frame is not None:
                    self.last_frame_time = time.time()
                    self.frame_count += 1
                    return True, frame
                else:
                    # Frame inválido - possível desconexão
                    self.is_connected = False
                    self.last_error = "Failed to read frame"
                    logger.warning("rtsp_frame_read_failed", camera_id=self.camera_id)
                    return False, None
                    
            except Exception as e:
                self.is_connected = False
                self.last_error = str(e)
                logger.error("rtsp_read_error", camera_id=self.camera_id, error=str(e))
                return False, None
    
    def ensure_connected(self) -> bool:
        """Garante que está conectado, reconecta se necessário."""
        if self.is_connected and self.cap is not None:
            # Verificar se ainda está vivo
            if time.time() - self.last_frame_time > 30.0:  # Timeout de 30s sem frames
                logger.warning("rtsp_timeout", camera_id=self.camera_id)
                self.is_connected = False
        
        if not self.is_connected:
            return self.connect()
        
        return True
    
    def disconnect(self) -> None:
        """Desconecta do stream."""
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            self.is_connected = False
            logger.info("rtsp_disconnected", camera_id=self.camera_id)
    
    def get_status(self) -> dict:
        """Retorna status do reader."""
        return {
            "camera_id": self.camera_id,
            "is_connected": self.is_connected,
            "last_frame_time": self.last_frame_time,
            "frame_count": self.frame_count,
            "last_error": self.last_error
        }
