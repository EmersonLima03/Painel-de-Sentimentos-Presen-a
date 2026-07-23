"""Captura assíncrona de webcam/USB e RTSP (thread dedicada, frames em tempo real)."""

from __future__ import annotations

import os
import sys
import time
from threading import Event, Lock, Thread
from typing import Any, Optional, Tuple

import cv2
import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)

_WINDOWS = sys.platform == "win32"
_CAP_DSHOW = getattr(cv2, "CAP_DSHOW", None) if _WINDOWS else None

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
MJPG_FOURCC = cv2.VideoWriter_fourcc(*"MJPG")


class AsyncVideoCapture:
    """
    Thread de captura em background: ML nunca bloqueia o recebimento de frames.
    `.read()` retorna imediatamente o último frame disponível (cópia).
    """

    def __init__(
        self,
        device_index: int,
        *,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        default_index: int = 0,
        reconnect_delay: float = 1.0,
        max_failures_before_reconnect: int = 15,
    ):
        self.device_index = device_index
        self.default_index = default_index
        self.width = width
        self.height = height
        self.reconnect_delay = reconnect_delay
        self.max_failures = max_failures_before_reconnect

        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[Thread] = None
        self._stop = Event()
        self._lock = Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ts: float = 0.0
        self._frame_count = 0
        self._connected = False
        self._last_error: Optional[str] = None
        self._fail_streak = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def last_frame_time(self) -> float:
        return self._latest_ts

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _open_device(self, index: int) -> bool:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        if _WINDOWS and _CAP_DSHOW is not None:
            cap = cv2.VideoCapture(index, _CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(index)

        if not cap.isOpened():
            self._last_error = f"device {index} did not open"
            return False

        try:
            cap.set(cv2.CAP_PROP_FOURCC, MJPG_FOURCC)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception as e:
            logger.debug("webcam_props_partial", error=str(e))

        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            self._last_error = "Failed to read initial frame"
            return False

        # Alguns índices Windows abrem mas entregam frame preto (IR/virtual/privacy).
        if float(np.mean(frame)) < 3.0:
            cap.release()
            self._last_error = f"device {index} returned black frame"
            logger.warning("async_capture_black_frame", device_index=index)
            return False

        self._cap = cap
        self.device_index = index
        self._connected = True
        self._last_error = None
        self._fail_streak = 0
        with self._lock:
            self._latest_frame = frame.copy()
            self._latest_ts = time.time()
            self._frame_count += 1
        logger.info(
            "async_capture_opened",
            device_index=index,
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        return True

    def connect(self) -> bool:
        candidates = []
        for i in (self.device_index, self.default_index, 0, 1, 2, 3):
            if i not in candidates:
                candidates.append(i)
        for idx in candidates:
            if self._open_device(idx):
                if idx != self.device_index:
                    logger.warning(
                        "async_capture_fallback",
                        from_index=self.device_index,
                        to_index=idx,
                    )
                return True
        self._connected = False
        return False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self._connected and not self.connect():
            logger.warning("async_capture_start_without_device")
        self._stop.clear()
        self._thread = Thread(target=self._capture_loop, name="async-video-capture", daemon=True)
        self._thread.start()
        logger.info("async_capture_thread_started", device_index=self.device_index)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._connected = False
        logger.info("async_capture_stopped", device_index=self.device_index)

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._connected = False
                time.sleep(self.reconnect_delay)
                if self._stop.is_set():
                    break
                if self.connect():
                    continue
                time.sleep(self.reconnect_delay)
                continue

            try:
                ret, frame = self._cap.read()
            except Exception as e:
                ret, frame = False, None
                self._last_error = str(e)

            if ret and frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._latest_ts = time.time()
                    self._frame_count += 1
                self._fail_streak = 0
                self._connected = True
                self._last_error = None
            else:
                self._fail_streak += 1
                self._last_error = "Failed to read frame"
                if self._fail_streak >= self.max_failures:
                    logger.warning(
                        "async_capture_reconnect",
                        device_index=self.device_index,
                        failures=self._fail_streak,
                    )
                    self._connected = False
                    if self._cap is not None:
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                        self._cap = None
                    self._fail_streak = 0
                    time.sleep(self.reconnect_delay)
                    self.connect()

            time.sleep(0.001)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Não bloqueante: último frame da thread de captura."""
        with self._lock:
            if self._latest_frame is None:
                return False, None
            return True, self._latest_frame.copy()

    def get_status(self) -> dict:
        return {
            "is_connected": self._connected,
            "last_frame_time": self._latest_ts,
            "frame_count": self._frame_count,
            "last_error": self._last_error,
            "device_index": self.device_index,
        }


class AsyncRTSPCapture:
    """
    Thread de captura RTSP: descarta frames antigos do buffer e expõe só o mais recente.
    Evita delay acumulado quando o pipeline de ML é mais lento que o FPS da câmera.
    """

    def __init__(
        self,
        rtsp_url: str,
        *,
        reconnect_delay: float = 2.0,
        max_failures_before_reconnect: int = 20,
        flush_grabs: int = 3,
    ):
        self.rtsp_url = rtsp_url
        self.reconnect_delay = reconnect_delay
        self.max_failures = max_failures_before_reconnect
        self.flush_grabs = max(0, flush_grabs)

        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[Thread] = None
        self._stop = Event()
        self._lock = Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ts: float = 0.0
        self._frame_count = 0
        self._connected = False
        self._last_error: Optional[str] = None
        self._fail_streak = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def last_frame_time(self) -> float:
        return self._latest_ts

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _open_stream(self) -> bool:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            self._last_error = "Failed to read initial RTSP frame"
            return False

        self._cap = cap
        self._connected = True
        self._last_error = None
        self._fail_streak = 0
        with self._lock:
            self._latest_frame = frame
            self._latest_ts = time.time()
            self._frame_count += 1
        logger.info("async_rtsp_opened", url=self.rtsp_url, width=frame.shape[1], height=frame.shape[0])
        return True

    def connect(self) -> bool:
        return self._open_stream()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self._connected and not self.connect():
            logger.warning("async_rtsp_start_without_stream")
        self._stop.clear()
        self._thread = Thread(target=self._capture_loop, name="async-rtsp-capture", daemon=True)
        self._thread.start()
        logger.info("async_rtsp_thread_started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._connected = False
        logger.info("async_rtsp_stopped")

    def _read_latest(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._cap is None or not self._cap.isOpened():
            return False, None
        try:
            if self.flush_grabs > 0:
                for _ in range(self.flush_grabs):
                    if not self._cap.grab():
                        break
                ret, frame = self._cap.retrieve()
            else:
                ret, frame = self._cap.read()
        except Exception as e:
            self._last_error = str(e)
            return False, None
        if ret and frame is not None:
            return True, frame
        return False, None

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._connected = False
                time.sleep(self.reconnect_delay)
                if self._stop.is_set():
                    break
                if self.connect():
                    continue
                time.sleep(self.reconnect_delay)
                continue

            ret, frame = self._read_latest()
            if ret and frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._latest_ts = time.time()
                    self._frame_count += 1
                self._fail_streak = 0
                self._connected = True
                self._last_error = None
            else:
                self._fail_streak += 1
                self._last_error = "Failed to read RTSP frame"
                if self._fail_streak >= self.max_failures:
                    logger.warning("async_rtsp_reconnect", failures=self._fail_streak)
                    self._connected = False
                    if self._cap is not None:
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                        self._cap = None
                    self._fail_streak = 0
                    time.sleep(self.reconnect_delay)
                    self.connect()

            time.sleep(0.001)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self._lock:
            if self._latest_frame is None:
                return False, None
            return True, self._latest_frame.copy()

    def get_status(self) -> dict:
        return {
            "is_connected": self._connected,
            "last_frame_time": self._latest_ts,
            "frame_count": self._frame_count,
            "last_error": self._last_error,
            "rtsp_url": self.rtsp_url,
        }
