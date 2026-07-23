"""Fontes de frame: demo | offline | rtsp — desacopladas do orquestrador."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Protocol, Tuple

import numpy as np


@dataclass
class FramePacket:
    frame: np.ndarray
    camera_id: str
    ts: float
    source_kind: str  # demo | offline | rtsp
    is_simulated: bool = False
    meta: Optional[dict] = None


class FrameSource(Protocol):
    def open(self) -> bool: ...
    def read(self) -> Optional[FramePacket]: ...
    def close(self) -> None: ...
    @property
    def status(self) -> str: ...


class DemoFrameSource:
    """Gera frames sintéticos determinísticos (grade 8 células) — sem câmera."""

    def __init__(self, camera_id: str = "demo-cam", width: int = 960, height: int = 540, fps: float = 5.0):
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.fps = fps
        self._open = False
        self._n = 0
        self._last = 0.0

    def open(self) -> bool:
        self._open = True
        return True

    @property
    def status(self) -> str:
        return "demo_running" if self._open else "closed"

    def read(self) -> Optional[FramePacket]:
        if not self._open:
            return None
        now = time.time()
        if self._last and (now - self._last) < (1.0 / max(0.1, self.fps)):
            return None
        self._last = now
        self._n += 1
        # Frame cinza + retângulos fictícios (não é imagem real)
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (36, 42, 52)
        for i in range(8):
            col, row = i % 4, i // 4
            x0, y0 = 40 + col * 220, 40 + row * 240
            shade = 80 + ((i * 17 + self._n) % 40)
            frame[y0 : y0 + 160, x0 : x0 + 140] = (shade, shade + 10, shade + 20)
        return FramePacket(
            frame=frame,
            camera_id=self.camera_id,
            ts=now,
            source_kind="demo",
            is_simulated=True,
            meta={"frame_index": self._n},
        )

    def close(self) -> None:
        self._open = False


class OfflineFrameSource:
    """Lê pasta de imagens ou arquivo de vídeo. Sem labels ⇒ nunca validação real."""

    def __init__(self, path: str, camera_id: str = "offline-cam"):
        self.path = Path(path)
        self.camera_id = camera_id
        self._open = False
        self._images: list[Path] = []
        self._idx = 0
        self._cap = None
        self._status = "idle"

    def open(self) -> bool:
        import cv2

        if self.path.is_dir():
            self._images = sorted(
                [p for p in self.path.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")]
            )
            self._open = bool(self._images)
            self._status = "offline_images" if self._open else "empty_corpus"
            return self._open
        if self.path.is_file():
            self._cap = cv2.VideoCapture(str(self.path))
            self._open = bool(self._cap.isOpened())
            self._status = "offline_video" if self._open else "open_failed"
            return self._open
        self._status = "path_missing"
        return False

    @property
    def status(self) -> str:
        return self._status

    def read(self) -> Optional[FramePacket]:
        import cv2

        if not self._open:
            return None
        if self._images:
            if self._idx >= len(self._images):
                self._status = "eof"
                return None
            img = cv2.imread(str(self._images[self._idx]))
            self._idx += 1
            if img is None:
                return None
            return FramePacket(img, self.camera_id, time.time(), "offline", False, {"path": str(self._images[self._idx - 1])})
        if self._cap is not None:
            ok, frame = self._cap.read()
            if not ok:
                self._status = "eof"
                return None
            return FramePacket(frame, self.camera_id, time.time(), "offline", False)
        return None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._open = False


class RTSPFrameSource:
    """Wrapper fino — falha clara sem derrubar a app."""

    def __init__(self, rtsp_url: str, camera_id: str = "rtsp-cam"):
        self.rtsp_url = rtsp_url
        self.camera_id = camera_id
        self._cap = None
        self._status = "idle"
        self._last_error = ""

    def open(self) -> bool:
        import cv2

        # Não logar URL completa (pode conter senha)
        try:
            self._cap = cv2.VideoCapture(self.rtsp_url)
            if not self._cap.isOpened():
                self._status = "connection_failed"
                self._last_error = "rtsp_open_failed"
                return False
            self._status = "connected"
            return True
        except Exception as e:
            self._status = "connection_failed"
            self._last_error = str(e)
            return False

    @property
    def status(self) -> str:
        return self._status

    @property
    def last_error(self) -> str:
        return self._last_error

    def read(self) -> Optional[FramePacket]:
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        if not ok:
            self._status = "read_failed"
            return None
        return FramePacket(frame, self.camera_id, time.time(), "rtsp", False)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._status = "closed"


def build_frame_source(mode: str, **kwargs) -> FrameSource:
    m = (mode or "rtsp").lower()
    if m == "demo":
        return DemoFrameSource(camera_id=kwargs.get("camera_id", "demo-cam"))
    if m == "offline":
        return OfflineFrameSource(path=kwargs.get("path", "./data/spike"), camera_id=kwargs.get("camera_id", "offline-cam"))
    return RTSPFrameSource(rtsp_url=kwargs.get("rtsp_url", ""), camera_id=kwargs.get("camera_id", "rtsp-cam"))
