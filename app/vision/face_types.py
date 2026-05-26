"""Tipos compartilhados do pipeline de visão."""

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass
class FaceDetectionResult:
    bbox: Tuple[int, int, int, int]
    score: float
    landmarks: np.ndarray  # (5, 2)
