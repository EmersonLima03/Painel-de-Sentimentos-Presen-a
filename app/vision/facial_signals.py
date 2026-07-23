"""
Sinais faciais observáveis via MediaPipe Face Mesh.

EAR clássico (6 pontos por olho), abertura da boca (bocejo), orientação cabeça.
Não afirma emoção interna.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from app.logging import get_logger
from app.vision.behavioral_taxonomy import ObservableSignal

logger = get_logger(__name__)

_mesh = None
_mesh_lock = threading.Lock()

# MediaPipe Face Mesh indices
_LEFT_EYE = (33, 160, 158, 133, 153, 144)  # p1..p6 EAR
_RIGHT_EYE = (362, 385, 387, 263, 373, 380)
_MOUTH_TOP = 13
_MOUTH_BOTTOM = 14
_MOUTH_LEFT = 78
_MOUTH_RIGHT = 308
_NOSE_TIP = 1
_CHIN = 152
_LEFT_EYE_OUTER = 33
_RIGHT_EYE_OUTER = 263


@dataclass
class FacialSignalSample:
    yaw: float
    pitch: float
    ear: float
    mouth_aspect: float
    orientation: str
    eyes_closed: bool
    possible_yawn: bool
    confidence: float
    observation_quality: str  # good | fair | poor
    label_pt: str


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


def _pt(landmarks, idx: int, iw: int, ih: int) -> np.ndarray:
    lm = landmarks[idx]
    return np.array([lm.x * iw, lm.y * ih], dtype=np.float32)


def _ear_six(landmarks, indices: Tuple[int, ...], iw: int, ih: int) -> float:
    try:
        p1, p2, p3, p4, p5, p6 = [_pt(landmarks, i, iw, ih) for i in indices]
        vert = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
        horiz = np.linalg.norm(p1 - p4)
        if horiz < 1e-3:
            return 0.25
        return float(vert / (2.0 * horiz))
    except Exception:
        return 0.25


def _mouth_aspect(landmarks, iw: int, ih: int) -> float:
    try:
        top = _pt(landmarks, _MOUTH_TOP, iw, ih)
        bottom = _pt(landmarks, _MOUTH_BOTTOM, iw, ih)
        left = _pt(landmarks, _MOUTH_LEFT, iw, ih)
        right = _pt(landmarks, _MOUTH_RIGHT, iw, ih)
        vert = np.linalg.norm(top - bottom)
        horiz = np.linalg.norm(left - right)
        if horiz < 1e-3:
            return 0.0
        return float(vert / horiz)
    except Exception:
        return 0.0


def _pose(landmarks, iw: int, ih: int) -> Tuple[float, float]:
    nx, ny = _pt(landmarks, _NOSE_TIP, iw, ih)
    lex, ley = _pt(landmarks, _LEFT_EYE_OUTER, iw, ih)
    rex, rey = _pt(landmarks, _RIGHT_EYE_OUTER, iw, ih)
    cx, cy = _pt(landmarks, _CHIN, iw, ih)
    eye_mid_x = (lex + rex) * 0.5
    eye_mid_y = (ley + rey) * 0.5
    eye_span = max(8.0, abs(rex - lex))
    yaw = float((nx - eye_mid_x) / eye_span)
    vert_span = max(8.0, cy - eye_mid_y)
    pitch = float((ny - eye_mid_y) / vert_span)
    return yaw, pitch


def _orientation(yaw: float, pitch: float, eyes_closed: bool) -> str:
    if eyes_closed:
        return ObservableSignal.EYES_CLOSED_PERSISTENT.value
    if abs(yaw) < 0.22 and pitch < 0.35:
        return ObservableSignal.ORIENTATION_FORWARD.value
    if pitch > 0.45 and abs(yaw) < 0.35:
        return ObservableSignal.ORIENTATION_DOWN_SHORT.value
    if abs(yaw) > 0.35 or pitch > 0.55:
        return ObservableSignal.ORIENTATION_AWAY.value
    return ObservableSignal.ATTENTION_INCONCLUSIVE.value


def analyze_face_roi(
    face_bgr: np.ndarray,
    *,
    ear_closed_thresh: float = 0.18,
    yawn_mouth_thresh: float = 0.55,
    min_side: int = 28,
) -> Optional[FacialSignalSample]:
    """Analisa ROI facial. Retorna None se qualidade insuficiente."""
    if face_bgr is None or face_bgr.size == 0:
        return None
    h, w = face_bgr.shape[:2]
    if min(h, w) < min_side:
        return FacialSignalSample(
            yaw=0.0,
            pitch=0.0,
            ear=0.25,
            mouth_aspect=0.0,
            orientation=ObservableSignal.LOW_OBSERVATION_QUALITY.value,
            eyes_closed=False,
            possible_yawn=False,
            confidence=0.2,
            observation_quality="poor",
            label_pt="Baixa qualidade de observação",
        )

    mesh = _get_face_mesh()
    rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
    result = mesh.process(rgb)
    if not result.multi_face_landmarks:
        return FacialSignalSample(
            yaw=0.0,
            pitch=0.0,
            ear=0.25,
            mouth_aspect=0.0,
            orientation=ObservableSignal.ATTENTION_INCONCLUSIVE.value,
            eyes_closed=False,
            possible_yawn=False,
            confidence=0.3,
            observation_quality="fair",
            label_pt="Atenção não conclusiva",
        )

    lm = result.multi_face_landmarks[0].landmark
    ih, iw = h, w
    ear_l = _ear_six(lm, _LEFT_EYE, iw, ih)
    ear_r = _ear_six(lm, _RIGHT_EYE, iw, ih)
    ear = (ear_l + ear_r) * 0.5
    mouth = _mouth_aspect(lm, iw, ih)
    yaw, pitch = _pose(lm, iw, ih)
    eyes_closed = ear < ear_closed_thresh
    possible_yawn = mouth >= yawn_mouth_thresh
    orientation = _orientation(yaw, pitch, eyes_closed)
    quality = "good" if min(h, w) >= 64 else ("fair" if min(h, w) >= 40 else "poor")
    conf = 0.85 if quality == "good" else (0.6 if quality == "fair" else 0.35)

    from app.vision.behavioral_taxonomy import label_pt

    return FacialSignalSample(
        yaw=yaw,
        pitch=pitch,
        ear=float(ear),
        mouth_aspect=float(mouth),
        orientation=orientation,
        eyes_closed=eyes_closed,
        possible_yawn=possible_yawn,
        confidence=conf,
        observation_quality=quality,
        label_pt=label_pt(orientation),
    )
