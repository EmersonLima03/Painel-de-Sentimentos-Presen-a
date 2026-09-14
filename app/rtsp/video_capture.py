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
# Iriun/IR/privacy: frame “abre” mas fica preto uniforme. Exige brilho + textura.
# mean~8–12 ainda parece preto no debug; limiar mais alto evita publicar tela preta.
_MIN_FRAME_MEAN = 12.0
_MIN_FRAME_STD = 6.0
# Queda brusca de brilho (USB sleep / índice virtual) → tratar como sinal perdido.
_BRIGHTNESS_DROP_RATIO = 0.35
_BRIGHTNESS_DROP_MIN_PREV = 40.0
_WARMUP_READS = 12
# Reconecta mais cedo em streak preto (antes: 15 frames ≈ “conectado” mentindo).
_BLACK_STREAK_DEGRADE = 3
_BLACK_STREAK_RECONNECT = 8


def _frame_signal(frame: np.ndarray) -> Tuple[float, float]:
    # np.mean/std em 1080p uint8 promove a float64 (~47 MiB) e já derrubou
    # o capture thread + o Cursor. meanStdDev não copia o frame inteiro.
    mean_s, std_s = cv2.meanStdDev(frame)
    return float(mean_s.mean()), float(std_s.mean())


def _frame_usable(
    frame: Optional[np.ndarray],
    *,
    prev_mean: Optional[float] = None,
) -> bool:
    if frame is None:
        return False
    mean, std = _frame_signal(frame)
    if mean < _MIN_FRAME_MEAN or std < _MIN_FRAME_STD:
        return False
    if (
        prev_mean is not None
        and float(prev_mean) >= _BRIGHTNESS_DROP_MIN_PREV
        and mean < float(prev_mean) * _BRIGHTNESS_DROP_RATIO
    ):
        return False
    return True


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
        # Mantém intenção original: após streak preto, re-probe (evita ficar preso na Iriun).
        self._want_auto = auto_select
        self._skip_indices: set[int] = set()

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
        self._last_good_mean: Optional[float] = None
        self._signal_lost = False
        self.requested_index = device_index
        self.opened_width = 0
        self.opened_height = 0

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and not self._signal_lost)

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def last_frame_time(self) -> float:
        return self._latest_ts

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _new_capture(self, index: int, *, force_msmf: bool = False) -> cv2.VideoCapture:
        if _WINDOWS and not force_msmf and _CAP_DSHOW is not None:
            return cv2.VideoCapture(index, _CAP_DSHOW)
        return cv2.VideoCapture(index)

    @staticmethod
    def _apply_capture_props(
        cap: cv2.VideoCapture,
        *,
        width: int,
        height: int,
        use_mjpg: bool,
        set_size: bool,
    ) -> None:
        try:
            if use_mjpg:
                cap.set(cv2.CAP_PROP_FOURCC, MJPG_FOURCC)
            if set_size:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception as e:
            logger.debug("webcam_props_partial", error=str(e))

    @staticmethod
    def _read_warmed(cap: cv2.VideoCapture, reads: int = _WARMUP_READS) -> Optional[np.ndarray]:
        """Descarta frames iniciais (exposição/USB) e devolve o último utilizável ou o último lido."""
        last: Optional[np.ndarray] = None
        for _ in range(max(1, reads)):
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            last = frame
            if _frame_usable(frame):
                return frame
        return last

    def _open_device(self, index: int) -> bool:
        if index in self._skip_indices:
            self._last_error = f"device {index} skipped (black/virtual)"
            return False

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        # Tentativas: DSHOW+MJPG → DSHOW sem MJPG → DSHOW defaults → MSMF fallback
        # MSMF evita câmeras virtuais brancas/verdes que DSHOW aceita sem reclamar.
        attempts = (
            {"use_mjpg": True, "set_size": True, "force_msmf": False},
            {"use_mjpg": False, "set_size": True, "force_msmf": False},
            {"use_mjpg": False, "set_size": False, "force_msmf": False},
            {"use_mjpg": False, "set_size": False, "force_msmf": True},   # MSMF
        )
        last_err = f"device {index} did not open"
        for props in attempts:
            cap = self._new_capture(index, force_msmf=bool(props["force_msmf"]))
            if not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                continue
            self._apply_capture_props(
                cap,
                width=self.width,
                height=self.height,
                use_mjpg=bool(props["use_mjpg"]),
                set_size=bool(props["set_size"]),
            )
            frame = self._read_warmed(cap)
            if frame is None:
                last_err = "Failed to read initial frame"
                cap.release()
                continue
            if not _frame_usable(frame):
                mean, std = _frame_signal(frame)
                last_err = f"device {index} bad frame mean={mean:.1f} std={std:.1f}"
                logger.warning(
                    "async_capture_bad_frame",
                    device_index=index,
                    mean_brightness=round(mean, 1),
                    std=round(std, 1),
                    use_mjpg=props["use_mjpg"],
                    force_msmf=props["force_msmf"],
                )
                cap.release()
                continue

            mean, std = _frame_signal(frame)
            self._cap = cap
            self.device_index = index
            self._connected = True
            self._signal_lost = False
            self._last_error = None
            self._fail_streak = 0
            self._last_good_mean = mean
            self.opened_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or frame.shape[1])
            self.opened_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or frame.shape[0])
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
                mean_brightness=round(mean, 1),
                std=round(std, 1),
                use_mjpg=props["use_mjpg"],
                force_msmf=props["force_msmf"],
            )
            return True

        self._last_error = last_err
        self._skip_indices.add(index)
        return False

    def _probe_best_index(self) -> Optional[int]:
        """Escolhe índice com imagem real (não preta) e maior área — evita Iriun/virtual 1080p preta."""
        best_idx = None
        best_score = -1.0
        for idx in range(0, 6):
            if idx in self._skip_indices:
                continue
            frame = None
            for force_msmf in (False, True):
                cap = self._new_capture(idx, force_msmf=force_msmf)
                if not cap.isOpened():
                    try:
                        cap.release()
                    except Exception:
                        pass
                    continue
                try:
                    for props in (
                        {"use_mjpg": True, "set_size": True},
                        {"use_mjpg": False, "set_size": False},
                    ):
                        self._apply_capture_props(
                            cap,
                            width=self.width,
                            height=self.height,
                            use_mjpg=bool(props["use_mjpg"]),
                            set_size=bool(props["set_size"]),
                        )
                        frame = self._read_warmed(cap)
                        if _frame_usable(frame):
                            break
                finally:
                    try:
                        cap.release()
                    except Exception:
                        pass
                if _frame_usable(frame):
                    break

            if not _frame_usable(frame):
                mean, std = _frame_signal(frame) if frame is not None else (0.0, 0.0)
                logger.info(
                    "webcam_probe_skip_bad",
                    device_index=idx,
                    mean_brightness=round(mean, 1),
                    std=round(std, 1),
                )
                continue
            assert frame is not None
            mean, std = _frame_signal(frame)
            # Usar dimensão do frame (cap já foi fechado)
            w = frame.shape[1]
            h = frame.shape[0]
            area = float(w * h)
            # Área domina; brilho/textura desempata (USB iluminada > virtual preta).
            score = area + (mean * std * 50.0)
            logger.info(
                "webcam_probe_candidate",
                device_index=idx,
                width=w,
                height=h,
                mean_brightness=round(mean, 1),
                std=round(std, 1),
                score=round(score, 1),
            )
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx is not None:
            logger.info("webcam_auto_selected", device_index=best_idx, score=round(best_score, 1))
        return best_idx

    def connect(self) -> bool:
        # Já conectado com frame recente e utilizável: não reabre.
        if (
            self._connected
            and self._cap is not None
            and self._cap.isOpened()
            and self._latest_frame is not None
            and _frame_usable(self._latest_frame)
            and (time.time() - self._latest_ts) < 15.0
        ):
            if not (self._thread and self._thread.is_alive()):
                self.start()
            return True

        if self._want_auto:
            self.auto_select = True

        candidates = []
        if self.auto_select:
            best = self._probe_best_index()
            if best is not None:
                candidates.append(best)
        candidates.append(self.requested_index)
        if self.allow_index_fallback or self._want_auto:
            for i in (self.default_index, 0, 1, 2, 3, 4, 5):
                if i not in candidates and i not in self._skip_indices:
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
                # Próximas reconexões ficam no índice escolhido (não re-probe) —
                # até streak preto reativar auto via _want_auto.
                self.auto_select = False
                self.requested_index = idx
                return True
        self._connected = False
        self._last_error = (
            f"failed to open requested camera index {self.requested_index}"
            + (" (fallback disabled)" if not self.allow_index_fallback and not self._want_auto else "")
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
                # Frame preto contínuo (Iriun sem celular / USB sleep / índice errado).
                if not _frame_usable(frame, prev_mean=self._last_good_mean):
                    self._fail_streak += 1
                    self._last_error = "black frame"
                    self._signal_lost = True
                    # Degrada cedo: UI/API não fingem "conectado OK" com tela preta.
                    if self._fail_streak >= _BLACK_STREAK_DEGRADE:
                        self._connected = False
                        with self._lock:
                            self._latest_frame = None
                    if self._fail_streak >= max(self.max_failures, _BLACK_STREAK_RECONNECT):
                        bad_idx = self.device_index
                        logger.warning(
                            "async_capture_black_streak_reconnect",
                            device_index=bad_idx,
                            failures=self._fail_streak,
                        )
                        if bad_idx is not None:
                            self._skip_indices.add(int(bad_idx))
                        if self._want_auto:
                            self.auto_select = True
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
                    mean, _std = _frame_signal(frame)
                    with self._lock:
                        self._latest_frame = frame
                        self._latest_ts = time.time()
                        self._frame_count += 1
                    self._fail_streak = 0
                    self._connected = True
                    self._signal_lost = False
                    self._last_error = None
                    self._last_good_mean = mean
            else:
                self._fail_streak += 1
                self._last_error = "Failed to read frame"
                self._signal_lost = True
                if self._fail_streak >= _BLACK_STREAK_DEGRADE:
                    self._connected = False
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
            "is_connected": self._connected and not self._signal_lost,
            "signal_ok": bool(self._connected and not self._signal_lost and self._latest_frame is not None),
            "last_frame_time": self._latest_ts,
            "frame_count": self._frame_count,
            "last_error": self._last_error,
            "device_index": self.device_index,
            "requested_index": self.requested_index,
            "opened_width": self.opened_width,
            "opened_height": self.opened_height,
            "auto_select": self.auto_select,
            "last_good_mean": self._last_good_mean,
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
