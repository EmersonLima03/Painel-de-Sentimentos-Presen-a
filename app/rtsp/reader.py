"""Leitor RTSP com reconexão robusta. Webcam usa AsyncVideoCapture (thread dedicada)."""

import sys
import time
from typing import Any, Optional, Tuple

import cv2

from app.logging import get_logger
from app.rtsp.video_capture import AsyncRTSPCapture, AsyncVideoCapture, DEFAULT_HEIGHT, DEFAULT_WIDTH

logger = get_logger(__name__)

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
    """Leitor RTSP ou webcam (índice numérico) com reconexão automática."""

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
        self.webcam_width = webcam_width or DEFAULT_WIDTH
        self.webcam_height = webcam_height or DEFAULT_HEIGHT
        self.cap: Optional[cv2.VideoCapture] = None
        self._async_capture: Optional[AsyncVideoCapture] = None
        self._async_rtsp: Optional[AsyncRTSPCapture] = None
        self.is_connected = False
        self.last_frame_time = 0.0
        self.frame_count = 0
        self.last_error: Optional[str] = None
        self.is_webcam = False
        self.device_index: Optional[int] = None
        self.auto_select = False
        self.allow_index_fallback = False

        try:
            device_idx = int((rtsp_url or "").strip())
            if device_idx >= 0:
                self.is_webcam = True
                self.device_index = device_idx
                logger.info("rtsp_reader_webcam", camera_id=camera_id, device_index=device_idx)
        except (ValueError, AttributeError, TypeError):
            pass

        # rtsp_url: "auto" → escolhe USB/maior resolução automaticamente
        if isinstance(rtsp_url, str) and rtsp_url.strip().lower() == "auto":
            self.is_webcam = True
            self.device_index = int(default_camera_index)
            self.auto_select = True
            logger.info("rtsp_reader_webcam_auto", camera_id=camera_id)

    def _apply_webcam_resolution(self) -> None:
        if not self.cap or not self.is_webcam:
            return
        try:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.webcam_width))
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.webcam_height))
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def connect(self) -> bool:
        if self.is_webcam and self.device_index is not None:
            return self._connect_webcam_async()

        return self._connect_rtsp_async()

    def _connect_rtsp_async(self) -> bool:
        # Idempotente: não derruba stream já saudável (start() chama connect de novo).
        if (
            self._async_rtsp is not None
            and self._async_rtsp.is_connected
            and (time.time() - (self._async_rtsp.last_frame_time or 0)) < 15.0
        ):
            self.is_connected = True
            self.last_error = None
            return True

        if self._async_rtsp is not None:
            self._async_rtsp.stop()

        logger.info("rtsp_connecting", camera_id=self.camera_id, url=self.rtsp_url)
        self._async_rtsp = AsyncRTSPCapture(
            self.rtsp_url,
            reconnect_delay=min(self.reconnect_delay, 2.0),
            flush_grabs=3,
        )
        if not self._async_rtsp.connect():
            self.is_connected = False
            self.last_error = self._async_rtsp.last_error
            logger.warning(
                "rtsp_connection_failed",
                camera_id=self.camera_id,
                error=self.last_error,
            )
            return False

        self._async_rtsp.start()
        self.is_connected = True
        self.last_error = None
        self.last_frame_time = self._async_rtsp.last_frame_time
        self.frame_count = self._async_rtsp.frame_count
        logger.info("rtsp_connected", camera_id=self.camera_id, source="rtsp_async")
        return True

    def _connect_webcam_async(self) -> bool:
        # Idempotente: evita stop()+reopen que mata a webcam no Windows.
        if (
            self._async_capture is not None
            and self._async_capture.is_connected
            and (time.time() - (self._async_capture.last_frame_time or 0)) < 15.0
        ):
            self.is_connected = True
            self.last_error = None
            self.last_frame_time = self._async_capture.last_frame_time
            self.frame_count = self._async_capture.frame_count
            logger.info(
                "webcam_already_connected",
                camera_id=self.camera_id,
                device_index=self._async_capture.device_index,
            )
            return True

        if self._async_capture is not None:
            self._async_capture.stop()

        self._async_capture = AsyncVideoCapture(
            self.device_index,
            width=self.webcam_width,
            height=self.webcam_height,
            default_index=self.default_camera_index,
            reconnect_delay=min(self.reconnect_delay, 2.0),
            allow_index_fallback=self.allow_index_fallback,
            auto_select=self.auto_select,
        )
        if not self._async_capture.connect():
            self.is_connected = False
            self.last_error = self._async_capture.last_error
            return False

        self._async_capture.start()
        self.is_connected = True
        self.last_error = None
        self.last_frame_time = self._async_capture.last_frame_time
        self.frame_count = self._async_capture.frame_count
        logger.info(
            "rtsp_connected",
            camera_id=self.camera_id,
            source="webcam_async",
            device_index=self._async_capture.device_index,
        )
        return True

    def read_frame(self) -> Tuple[bool, Optional[Any]]:
        if self._async_rtsp is not None:
            ret, frame = self._async_rtsp.read()
            if ret and frame is not None:
                self.is_connected = self._async_rtsp.is_connected
                self.last_frame_time = self._async_rtsp.last_frame_time
                self.frame_count = self._async_rtsp.frame_count
                self.last_error = self._async_rtsp.last_error
                return True, frame
            self.is_connected = self._async_rtsp.is_connected
            self.last_error = self._async_rtsp.last_error or "No frame yet"
            return False, None

        if self._async_capture is not None:
            ret, frame = self._async_capture.read()
            if ret and frame is not None:
                self.is_connected = self._async_capture.is_connected
                self.last_frame_time = self._async_capture.last_frame_time
                self.frame_count = self._async_capture.frame_count
                self.last_error = self._async_capture.last_error
                return True, frame
            self.is_connected = self._async_capture.is_connected
            self.last_error = self._async_capture.last_error or "No frame yet"
            return False, None

        if not self.is_connected or self.cap is None:
            return False, None

        try:
            ret, frame = self.cap.read()
            if ret and frame is not None:
                self.last_frame_time = time.time()
                self.frame_count += 1
                return True, frame
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
        if self._async_rtsp is not None:
            if self._async_rtsp.is_connected:
                if time.time() - self._async_rtsp.last_frame_time > 30.0:
                    logger.warning("rtsp_timeout", camera_id=self.camera_id)
                else:
                    self.is_connected = True
                    return True
            return self.connect()

        if self._async_capture is not None:
            if self._async_capture.is_connected:
                if time.time() - self._async_capture.last_frame_time > 30.0:
                    logger.warning("rtsp_timeout", camera_id=self.camera_id)
                else:
                    self.is_connected = True
                    return True
            return self.connect()

        if self.is_connected and self.cap is not None:
            if time.time() - self.last_frame_time > 30.0:
                logger.warning("rtsp_timeout", camera_id=self.camera_id)
                self.is_connected = False

        if not self.is_connected:
            return self.connect()
        return True

    def disconnect(self) -> None:
        if self._async_rtsp is not None:
            self._async_rtsp.stop()
            self._async_rtsp = None
        if self._async_capture is not None:
            self._async_capture.stop()
            self._async_capture = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.is_connected = False
        logger.info("rtsp_disconnected", camera_id=self.camera_id)

    def get_status(self) -> dict:
        if self._async_rtsp is not None:
            st = self._async_rtsp.get_status()
            return {
                "camera_id": self.camera_id,
                "is_connected": st["is_connected"],
                "last_frame_time": st["last_frame_time"],
                "frame_count": st["frame_count"],
                "last_error": st["last_error"],
            }
        if self._async_capture is not None:
            st = self._async_capture.get_status()
            return {
                "camera_id": self.camera_id,
                "is_connected": st["is_connected"],
                "last_frame_time": st["last_frame_time"],
                "frame_count": st["frame_count"],
                "last_error": st["last_error"],
            }
        return {
            "camera_id": self.camera_id,
            "is_connected": self.is_connected,
            "last_frame_time": self.last_frame_time,
            "frame_count": self.frame_count,
            "last_error": self.last_error,
        }
