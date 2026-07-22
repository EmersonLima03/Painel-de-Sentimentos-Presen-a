"""
Engajamento por pose da cabeça (olhar para frente = atento).

Adequado para sala de aula — melhor que FER/Mini-XCEPTION ou DeepFace emotion
em webcam (48px, fone, sombra). Usa MediaPipe Face Mesh (já no projeto).
"""

from __future__ import annotations

import threading
from typing import Optional, Tuple

import cv2
import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)

_mesh = None
_mesh_lock = threading.Lock()
_state_history: list = []
_history_max = 4

# Índices Face Mesh (MediaPipe)
_NOSE_TIP = 1
_CHIN = 152
_LEFT_EYE_OUTER = 33
_RIGHT_EYE_OUTER = 263
_LEFT_EYE_INNER = 133
_RIGHT_EYE_INNER = 362


def _get_face_mesh():
    global _mesh
    with _mesh_lock:
        if _mesh is not None:
            return _mesh
        import mediapipe as mp

        _mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.45,
            min_tracking_confidence=0.45,
        )
        return _mesh


def _eye_aspect_ratio(landmarks, ih: int, iw: int) -> float:
    """EAR aproximado — olho fechado/caindo → valor baixo."""
    def pt(idx):
        lm = landmarks[idx]
        return np.array([lm.x * iw, lm.y * ih], dtype=np.float32)

    try:
        p1, p2, p3, p4, p5, p6 = (
            pt(_LEFT_EYE_OUTER), pt(_LEFT_EYE_INNER), pt(_RIGHT_EYE_INNER),
            pt(_RIGHT_EYE_OUTER), pt(_LEFT_EYE_INNER), pt(_RIGHT_EYE_OUTER),
        )
        v1 = np.linalg.norm(p2 - p6)
        v2 = np.linalg.norm(p3 - p5)
        h = np.linalg.norm(p1 - p4)
        if h < 1e-3:
            return 0.25
        return float((v1 + v2) / (2.0 * h))
    except Exception:
        return 0.25


def _pose_from_landmarks(landmarks, ih: int, iw: int) -> Tuple[float, float, float]:
    """Retorna (yaw_proxy, pitch_proxy, ear)."""
    def xy(idx):
        lm = landmarks[idx]
        return lm.x * iw, lm.y * ih

    nx, ny = xy(_NOSE_TIP)
    lex, ley = xy(_LEFT_EYE_OUTER)
    rex, rey = xy(_RIGHT_EYE_OUTER)
    cx, cy = xy(_CHIN)

    eye_mid_x = (lex + rex) * 0.5
    eye_mid_y = (ley + rey) * 0.5
    eye_span = max(8.0, abs(rex - lex))

    yaw_proxy = (nx - eye_mid_x) / eye_span
    vert_span = max(8.0, cy - eye_mid_y)
    pitch_proxy = (ny - eye_mid_y) / vert_span
    ear = _eye_aspect_ratio(landmarks, ih, iw)
    return float(yaw_proxy), float(pitch_proxy), float(ear)


def _map_pose_to_state(yaw: float, pitch: float, ear: float) -> str:
    """
    Olhando para a câmera: yaw e pitch baixos.
    Virado / olhando chão ou teto / olho quase fechado → distraído.
    """
    if ear < 0.12:
        return "distracted"
    if abs(yaw) <= 0.22 and 0.35 <= pitch <= 0.82:
        return "attentive"
    if abs(yaw) <= 0.42 and 0.22 <= pitch <= 0.95:
        return "neutral"
    return "distracted"


def _smooth(state: str) -> str:
    global _state_history
    _state_history.append(state)
    if len(_state_history) > _history_max:
        _state_history = _state_history[-_history_max:]
    priority = {"attentive": 2, "neutral": 1, "distracted": 0}
    counts: dict = {}
    for s in _state_history:
        counts[s] = counts.get(s, 0) + 1
    return max(counts, key=lambda s: (counts[s], priority.get(s, 0)))


def calculate_head_pose_engagement(face_bgr: np.ndarray, bbox: tuple = ()) -> Tuple[str, str, dict]:
    """
    Retorna (state, label_pt, debug_dict).
    state: attentive | neutral | distracted
    """
    if face_bgr is None or face_bgr.size == 0:
        return "neutral", "Neutro", {}

    rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
    ih, iw = face_bgr.shape[:2]
    if min(ih, iw) < 28:
        return "neutral", "Neutro", {"reason": "face_too_small"}

    try:
        mesh = _get_face_mesh()
        res = mesh.process(rgb)
        if not res.multi_face_landmarks:
            return "neutral", "Neutro", {"reason": "no_landmarks"}
        lm = res.multi_face_landmarks[0].landmark
        yaw, pitch, ear = _pose_from_landmarks(lm, ih, iw)
        raw = _map_pose_to_state(yaw, pitch, ear)
        state = _smooth(raw)
        labels = {"attentive": "Engajado", "neutral": "Neutro", "distracted": "Distraido"}
        dbg = {"yaw": round(yaw, 3), "pitch": round(pitch, 3), "ear": round(ear, 3), "backend": "head_pose"}
        return state, labels.get(state, state), dbg
    except Exception as e:
        logger.debug("head_pose_failed", error=str(e))
        return "neutral", "Neutro", {"reason": str(e)}


def is_head_pose_available() -> bool:
    try:
        import mediapipe  # noqa: F401
        return True
    except ImportError:
        return False
