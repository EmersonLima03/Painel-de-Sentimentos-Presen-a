"""Análise de qualidade de face."""

import cv2
import numpy as np
from typing import Tuple, Optional
from app.logging import get_logger

logger = get_logger(__name__)


def calculate_face_quality(face_roi: np.ndarray, min_size: int = 50) -> Tuple[str, float]:
    """
    Calcula qualidade da face detectada.
    
    Retorna: (quality_label, quality_score)
    quality_label: "good", "fair", "poor"
    quality_score: 0.0 a 1.0
    """
    if face_roi is None or face_roi.size == 0:
        return "poor", 0.0
    
    h, w = face_roi.shape[:2]
    
    # 1. Tamanho mínimo
    if min(h, w) < min_size:
        return "poor", 0.3
    
    # 2. Blur (Laplacian variance)
    gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY) if len(face_roi.shape) == 3 else face_roi
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    blur_normalized = min(blur_score / 100.0, 1.0)  # Normalizar
    
    # 3. Iluminação (brightness e contraste)
    mean_brightness = np.mean(gray)
    std_brightness = np.std(gray)
    
    # Brightness ideal: 100-180
    brightness_score = 1.0 - abs(mean_brightness - 140) / 140.0
    brightness_score = max(0.0, min(1.0, brightness_score))
    
    # Contraste mínimo
    contrast_score = min(std_brightness / 50.0, 1.0)
    
    # Score combinado
    quality_score = (blur_normalized * 0.4 + brightness_score * 0.3 + contrast_score * 0.3)
    
    if quality_score >= 0.7:
        quality_label = "good"
    elif quality_score >= 0.4:
        quality_label = "fair"
    else:
        quality_label = "poor"
    
    return quality_label, quality_score
