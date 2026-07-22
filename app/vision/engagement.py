"""Cálculo de engajamento (simplificado para MVP)."""

import cv2
import numpy as np
from typing import Dict, List, Optional
from app.logging import get_logger

logger = get_logger(__name__)


def calculate_engagement_state(face_roi: np.ndarray, bbox: tuple) -> str:
    """
    Calcula estado de engajamento de uma face (simplificado).
    
    MVP: usa heurística simples baseada em posição/iluminação.
    Em produção, substituir por modelo de head pose/eye gaze.
    
    Retorna: "attentive", "neutral", "distracted"
    """
    # Placeholder: distribuição determinística baseada em hash simples
    # Em produção, usar modelo real de head pose
    
    # Heurística simples: baseada em posição relativa e brilho
    h, w = face_roi.shape[:2]
    gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY) if len(face_roi.shape) == 3 else face_roi
    
    center_x = w // 2
    center_y = h // 2
    
    # Brilho médio na região central (olhos)
    eye_region = gray[max(0, center_y - h//4):center_y + h//8, center_x - w//4:center_x + w//4]
    if eye_region.size > 0:
        brightness = np.mean(eye_region)
    else:
        brightness = np.mean(gray)
    
    # Heurística simplificada
    # Em produção: usar modelo de head pose/eye gaze
    # Webcam/fone: faixas mais baixas; evita "distraído" por sombra no rosto
    if brightness > 95:
        return "attentive"
    elif brightness > 55:
        return "neutral"
    else:
        return "distracted"


def aggregate_engagement_window(
    states: List[str],
    motion_values: Optional[List[float]] = None
) -> Dict:
    """
    Agrega estados de engajamento em uma janela.
    Não infere emoção individual; engajamento é agregado (faces + atividade geral).

    motion_values: diferença absoluta média entre frames (opcional) para activity_level.

    Retorna: distribuição, engagement_index (0..1), activity_level (low/medium/high).
    """
    if not states:
        return {
            "attentive": 0.0,
            "neutral": 1.0,
            "distracted": 0.0,
            "engagement_index": 0.0,
            "activity_level": "low",
        }
    total = len(states)
    attentive = sum(1 for s in states if s == "attentive")
    neutral = sum(1 for s in states if s == "neutral")
    distracted = sum(1 for s in states if s == "distracted")
    distribution = {
        "attentive": attentive / total,
        "neutral": neutral / total,
        "distracted": distracted / total,
    }
    # Índice agregado: weighted average (sem inferir emoção; sinal de presença/atividade)
    engagement_index = (
        distribution["attentive"] * 1.0
        + distribution["neutral"] * 0.5
        + distribution["distracted"] * 0.0
    )
    engagement_index = max(0.0, min(1.0, engagement_index))

    # Atividade geral (movimento agregado)
    activity_level = "low"
    if motion_values and len(motion_values) > 0:
        mean_motion = float(np.mean(motion_values))
        if mean_motion > 15:
            activity_level = "high"
        elif mean_motion > 5:
            activity_level = "medium"
    out = {**distribution, "engagement_index": engagement_index, "activity_level": activity_level}
    return out
