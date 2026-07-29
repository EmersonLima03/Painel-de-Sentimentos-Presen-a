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
        allow_index_fallback: bool = False,
        auto_select: bool = False,
    ):
        self.device_index = device_index
        self.default_index = default_index
        self.width = width
        self.height = height
        self.reconnect_delay = reconnect_delay
        self.max_failures = max_failures_before_reconnect
        # Se False, NÃO troca silenciosamente para a webcam do notebook.
        self.allow_index_fallback = allow_index_fallback
        # Se True, escolhe o índice com maior resolução útil (típico USB 1080p).
        self.auto_select = auto_select

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
        self.requested_index = device_index
        self.opened_width = 0
        self.opened_height = 0

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
        self.opened_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.opened_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        with self._lock:
            self._latest_frame = frame.copy()
            self._latest_ts = time.time()
            self._frame_count += 1
        logger.info(
            "async_capture_opened",
            device_index=index,
            requested_index=self.requested_index,
            width=self.opened_width,
            height=self.opened_height,
            mean_brightness=round(float(np.mean(frame)), 1),
        )
        return True

    def _probe_best_index(self) -> Optional[int]:
        """Escolhe índice com frame válido e maior área (USB 1080p costuma ganhar do notebook)."""
        best_idx = None
        best_area = -1
        for idx in range(0, 6):
            # Abrir só para medir; liberar em seguida.
            if _WINDOWS and _CAP_DSHOW is not None:
                cap = cv2.VideoCapture(idx, _CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                continue
            try:
                try:
                    cap.set(cv2.CAP_PROP_FOURCC, MJPG_FOURCC)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                ret, frame = cap.read()
                if not ret or frame is None:
                    continue
                if float(np.mean(frame)) < 3.0:
                    continue
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or frame.shape[1])
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or frame.shape[0])
                area = w * h
                logger.info(
                    "webcam_probe_candidate",
                    device_index=idx,
                    width=w,
                    height=h,
                    mean_brightness=round(float(np.mean(frame)), 1),
                )
                if area > best_area:
                    best_area = area
                    best_idx = idx
            finally:
                try:
                    cap.release()
                except Exception:
                    pass
        if best_idx is not None:
            logger.info("webcam_auto_selected", device_index=best_idx, area=best_area)
        return best_idx

    def connect(self) -> bool:
        # Já conectado com frame recente: não reabre (evita race com orchestrator.start).
        if (
            self._connected
            and self._cap is not None
            and self._cap.isOpened()
            and self._latest_frame is not None
            and (time.time() - self._latest_ts) < 15.0
        ):
            if not (self._thread and self._thread.is_alive()):
                self.start()
            return True

        candidates = []
        if self.auto_select:
            best = self._probe_best_index()
            if best is not None:
                candidates.append(best)
        candidates.append(self.requested_index)
        if self.allow_index_fallback:
            for i in (self.default_index, 0, 1, 2, 3):
                if i not in candidates:
                    candidates.append(i)

        # Sem duplicatas, preservando ordem
        ordered = []
        for i in candidates:
            if i not in ordered:
                ordered.append(i)

        for idx in ordered:
            if self._open_device(idx):
                if idx != self.requested_index:
                    logger.warning(
                        "async_capture_opened_different_index",
                        requested_index=self.requested_index,
                        opened_index=idx,
                        width=self.opened_width,
                        height=self.opened_height,
                    )
                # Próximas reconexões ficam no índice escolhido (não re-probe).
                self.auto_select = False
                self.requested_index = idx
                return True
        self._connected = False
        self._last_error = (
            f"failed to open requested camera index {self.requested_index}"
            + (" (fallback disabled)" if not self.allow_index_fallback else "")
        )
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
                # Frame preto contínuo (USB sleep / índice errado) conta como falha —
                # senão o loop nunca reconecta e o MJPEG fica preto para sempre.
                if float(np.mean(frame)) < 3.0:
                    self._fail_streak += 1
                    self._last_error = "black frame"
                    if self._fail_streak >= self.max_failures:
                        logger.warning(
                            "async_capture_black_streak_reconnect",
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
                else:
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
            "requested_index": self.requested_index,
            "opened_width": self.opened_width,
            "opened_height": self.opened_height,
            "auto_select": self.auto_select,
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
