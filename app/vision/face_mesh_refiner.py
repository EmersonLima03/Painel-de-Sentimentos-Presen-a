"""
Refinador de ROI usando MediaPipe Face Mesh.

Objetivo: quando a caixa do Face Detection (bbox) está "alta demais" ou imprecisa em
distância/ângulo, usamos landmarks do Face Mesh para recortar melhor a região do rosto
antes de gerar embeddings (FaceNet) e fazer matching (FAISS).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RefinedBox:
    x: int
    y: int
    w: int
    h: int


class FaceMeshRefiner:
    """Usa MediaPipe Face Mesh para refinar o bbox do rosto para recorte do embedding."""

    def __init__(self, refine_landmarks: bool = True):
        try:
            import mediapipe as mp
        except ImportError as e:
            raise RuntimeError("mediapipe not installed") from e

        self._mp = mp

        # Face Mesh: landmarks são mais robustos para manter "face" mesmo quando bbox inclui tronco.
        # max_num_faces=1 porque refinamos ROI por bbox individual.
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=refine_landmarks,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def refine_bbox(
        self,
        frame_bgr: np.ndarray,
        bbox: Tuple[int, int, int, int],
        padding_ratio: float = 0.15,
    ) -> Optional[RefinedBox]:
        """
        Retorna bbox refinado em coordenadas do frame original.

        Args:
            frame_bgr: frame completo (BGR - OpenCV)
            bbox: (x, y, w, h) do detector de face
            padding_ratio: padding aplicado proporcional ao tamanho do bbox
        """
        x, y, w, h = bbox
        if w <= 0 or h <= 0:
            return None

        frame_h, frame_w = frame_bgr.shape[:2]
        x2 = max(0, x)
        y2 = max(0, y)
        w2 = max(1, min(frame_w - x2, w))
        h2 = max(1, min(frame_h - y2, h))

        roi = frame_bgr[y2 : y2 + h2, x2 : x2 + w2]
        if roi.size == 0:
            return None

        roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(roi_rgb)

        if not results.multi_face_landmarks:
            return None

        landmarks = results.multi_face_landmarks[0].landmark
        if not landmarks:
            return None

        xs = [lm.x for lm in landmarks]
        ys = [lm.y for lm in landmarks]

        min_x = float(min(xs))
        max_x = float(max(xs))
        min_y = float(min(ys))
        max_y = float(max(ys))

        # Converter proporções (0..1) para pixels do ROI
        box_w = max_x - min_x
        box_h = max_y - min_y
        if box_w <= 0.001 or box_h <= 0.001:
            return None

        pad_x = box_w * padding_ratio
        pad_y = box_h * padding_ratio

        rx1 = int((min_x - pad_x) * w2)
        ry1 = int((min_y - pad_y) * h2)
        rx2 = int((max_x + pad_x) * w2)
        ry2 = int((max_y + pad_y) * h2)

        rx1 = max(0, min(w2 - 1, rx1))
        ry1 = max(0, min(h2 - 1, ry1))
        rx2 = max(rx1 + 1, min(w2, rx2))
        ry2 = max(ry1 + 1, min(h2, ry2))

        refined = RefinedBox(
            x=x2 + rx1,
            y=y2 + ry1,
            w=rx2 - rx1,
            h=ry2 - ry1,
        )
        return refined

