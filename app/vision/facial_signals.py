"""
Sinais faciais observáveis via MediaPipe Tasks Face Landmarker.

EAR clássico (6 pontos por olho), abertura da boca, orientação da cabeça.
Não afirma emoção interna. Compatível com mediapipe>=0.10 sem mp.solutions.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np

from app.logging import get_logger
from app.vision.behavioral_taxonomy import ObservableSignal

logger = get_logger(__name__)

_landmarker = None
_landmarker_lock = threading.Lock()
_landmarker_error: Optional[str] = None

# MediaPipe Face Mesh / Face Landmarker indices (478 mesh)
_LEFT_EYE = (33, 160, 158, 133, 153, 144)
_RIGHT_EYE = (362, 385, 387, 263, 373, 380)
_MOUTH_TOP = 13
_MOUTH_BOTTOM = 14
_MOUTH_LEFT = 78
_MOUTH_RIGHT = 308
_NOSE_TIP = 1
_CHIN = 152
_LEFT_EYE_OUTER = 33
_RIGHT_EYE_OUTER = 263
_FOREHEAD = 10

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)


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
    roll: float = 0.0
    ear_left: Optional[float] = None
    ear_right: Optional[float] = None
    provider: str = "mediapipe"
    landmarks_quality: float = 0.0
    smile_score: float = 0.0


def face_landmarker_health() -> dict:
    """Status do backend de landmarks (sem mock)."""
    err = _landmarker_error
    lm = _get_face_landmarker(create=False)
    if lm is not None:
        return {"status": "available", "provider": "mediapipe_tasks", "reason": None}
    if err:
        return {"status": "unavailable", "provider": "mediapipe_tasks", "reason": err}
    # probe create
    lm2 = _get_face_landmarker(create=True)
    if lm2 is not None:
        return {"status": "available", "provider": "mediapipe_tasks", "reason": None}
    return {
        "status": "unavailable",
        "provider": "mediapipe_tasks",
        "reason": _landmarker_error or "not_initialized",
    }


def _model_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    cache = root / "data" / "mediapipe_models"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / "face_landmarker.task"


def _ensure_model() -> Path:
    path = _model_path()
    if path.is_file() and path.stat().st_size > 100_000:
        return path
    import urllib.request

    logger.info("face_landmarker_downloading", url=_MODEL_URL, path=str(path))
    urllib.request.urlretrieve(_MODEL_URL, path)
    if not path.is_file() or path.stat().st_size < 100_000:
        raise RuntimeError("face_landmarker.task download failed or incomplete")
    logger.info("face_landmarker_downloaded", path=str(path), bytes=path.stat().st_size)
    return path


def _get_face_landmarker(*, create: bool = True):
    global _landmarker, _landmarker_error
    with _landmarker_lock:
        if _landmarker is not None:
            return _landmarker
        if not create:
            return None
        if _landmarker_error and _landmarker is None:
            # allow retry after fix
            pass
        try:
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core import base_options as mp_base_options

            model_path = str(_ensure_model())
            opts = vision.FaceLandmarkerOptions(
                base_options=mp_base_options.BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.45,
                min_face_presence_confidence=0.45,
                min_tracking_confidence=0.45,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=True,
            )
            _landmarker = vision.FaceLandmarker.create_from_options(opts)
            _landmarker_error = None
            logger.info("face_landmarker_ready", provider="mediapipe_tasks", model=model_path)
            return _landmarker
        except Exception as e:
            _landmarker = None
            _landmarker_error = f"{type(e).__name__}:{e}"
            logger.warning("face_landmarker_init_failed", error=_landmarker_error)
            return None


def _pt(landmarks: List[Any], idx: int, iw: int, ih: int) -> np.ndarray:
    lm = landmarks[idx]
    return np.array([float(lm.x) * iw, float(lm.y) * ih], dtype=np.float32)


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


def _smile_from_landmarks(landmarks, iw: int, ih: int, *, mouth_aspect: float) -> float:
    """
    Sorriso geométrico: cantos da boca elevados + boca larga (não bocejo).
    Retorna 0..1 — independente do FER.
    """
    try:
        top = _pt(landmarks, _MOUTH_TOP, iw, ih)
        bottom = _pt(landmarks, _MOUTH_BOTTOM, iw, ih)
        left = _pt(landmarks, _MOUTH_LEFT, iw, ih)
        right = _pt(landmarks, _MOUTH_RIGHT, iw, ih)
        mid_y = float((top[1] + bottom[1]) * 0.5)
        # y menor = mais alto na imagem → cantos acima do meio = sorriso
        lift = (mid_y - float((left[1] + right[1]) * 0.5)) / max(float(ih) * 0.015, 1.0)
        width_ratio = float(np.linalg.norm(right - left)) / max(float(iw), 1.0)
        score = 0.0
        if lift >= 0.25:
            score += 0.30
        if lift >= 0.55:
            score += 0.25
        if lift >= 0.90:
            score += 0.15
        if width_ratio >= 0.32:
            score += 0.18
        if width_ratio >= 0.40:
            score += 0.12
        # boca aberta moderada (dentes) — bocejo é MAR alto
        if 0.12 <= float(mouth_aspect) <= 0.48:
            score += 0.18
        elif 0.08 <= float(mouth_aspect) < 0.12:
            score += 0.08
        if float(mouth_aspect) >= 0.55:
            score *= 0.25  # provável bocejo, não sorriso
        return float(min(1.0, max(0.0, score)))
    except Exception:
        return 0.0


def _pose_from_landmarks(landmarks, iw: int, ih: int) -> Tuple[float, float, float]:
    nx, ny = _pt(landmarks, _NOSE_TIP, iw, ih)
    lex, ley = _pt(landmarks, _LEFT_EYE_OUTER, iw, ih)
    rex, rey = _pt(landmarks, _RIGHT_EYE_OUTER, iw, ih)
    cx, cy = _pt(landmarks, _CHIN, iw, ih)
    fx, fy = _pt(landmarks, _FOREHEAD, iw, ih)
    eye_mid_x = (lex + rex) * 0.5
    eye_mid_y = (ley + rey) * 0.5
    eye_span = max(8.0, abs(rex - lex))
    yaw = float((nx - eye_mid_x) / eye_span)
    vert_span = max(8.0, cy - eye_mid_y)
    pitch = float((ny - eye_mid_y) / vert_span)
    # roll: inclinação da linha dos olhos
    roll = float(math.atan2(rey - ley, rex - lex))
    # refine pitch with forehead-chin axis
    _ = (fx, fy)
    return yaw, pitch, roll


def _pose_from_matrix(matrix) -> Optional[Tuple[float, float, float]]:
    """Extrai yaw/pitch/roll (rad approx → normalizado ~[-1,1] / rad) de matriz 4x4."""
    try:
        m = np.array(matrix, dtype=np.float64).reshape(4, 4)
        r = m[:3, :3]
        # yaw (Y), pitch (X), roll (Z) — convenção OpenCV-ish
        sy = math.sqrt(r[0, 0] * r[0, 0] + r[1, 0] * r[1, 0])
        singular = sy < 1e-6
        if not singular:
            pitch = math.atan2(-r[2, 0], sy)
            yaw = math.atan2(r[1, 0], r[0, 0])
            roll = math.atan2(r[2, 1], r[2, 2])
        else:
            pitch = math.atan2(-r[2, 0], sy)
            yaw = math.atan2(-r[0, 1], r[1, 1])
            roll = 0.0
        # normaliza para faixa comparável à heurística anterior (~[-1,1] para yaw/pitch)
        return float(yaw / (math.pi / 2)), float(pitch / (math.pi / 2)), float(roll)
    except Exception:
        return None


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
            roll=0.0,
            ear=0.25,
            ear_left=0.25,
            ear_right=0.25,
            mouth_aspect=0.0,
            orientation=ObservableSignal.LOW_OBSERVATION_QUALITY.value,
            eyes_closed=False,
            possible_yawn=False,
            confidence=0.2,
            observation_quality="poor",
            label_pt="Baixa qualidade de observação",
            landmarks_quality=0.1,
        )

    landmarker = _get_face_landmarker(create=True)
    if landmarker is None:
        return None

    from mediapipe.tasks.python.vision.core import image as mp_image

    rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
    if not rgb.flags["C_CONTIGUOUS"]:
        rgb = np.ascontiguousarray(rgb)
    mp_img = mp_image.Image(image_format=mp_image.ImageFormat.SRGB, data=rgb)
    try:
        result = landmarker.detect(mp_img)
    except Exception as e:
        logger.debug("face_landmarker_detect_failed", error=str(e))
        return None

    if not result.face_landmarks:
        return FacialSignalSample(
            yaw=0.0,
            pitch=0.0,
            roll=0.0,
            ear=0.25,
            ear_left=0.25,
            ear_right=0.25,
            mouth_aspect=0.0,
            orientation=ObservableSignal.ATTENTION_INCONCLUSIVE.value,
            eyes_closed=False,
            possible_yawn=False,
            confidence=0.3,
            observation_quality="fair",
            label_pt="Atenção não conclusiva",
            landmarks_quality=0.2,
        )

    lm = result.face_landmarks[0]
    ih, iw = h, w
    ear_l = _ear_six(lm, _LEFT_EYE, iw, ih)
    ear_r = _ear_six(lm, _RIGHT_EYE, iw, ih)
    ear = (ear_l + ear_r) * 0.5
    mouth = _mouth_aspect(lm, iw, ih)
    smile = _smile_from_landmarks(lm, iw, ih, mouth_aspect=mouth)
    yaw, pitch, roll = _pose_from_landmarks(lm, iw, ih)

    eyes_closed = ear < ear_closed_thresh
    possible_yawn = mouth >= yawn_mouth_thresh
    orientation = _orientation(yaw, pitch, eyes_closed)
    quality = "good" if min(h, w) >= 64 else ("fair" if min(h, w) >= 40 else "poor")
    conf = 0.85 if quality == "good" else (0.6 if quality == "fair" else 0.35)
    lq = 0.85 if quality == "good" else (0.55 if quality == "fair" else 0.3)

    matrices = getattr(result, "facial_transformation_matrixes", None) or []
    if len(matrices) > 0:
        posed = _pose_from_matrix(matrices[0])
        if posed is not None:
            myaw, mpitch, mroll = posed
            yaw = 0.55 * myaw + 0.45 * yaw
            pitch = 0.55 * mpitch + 0.45 * pitch
            roll = 0.4 * mroll + 0.6 * roll

    from app.vision.behavioral_taxonomy import label_pt

    return FacialSignalSample(
        yaw=float(yaw),
        pitch=float(pitch),
        ear=float(ear),
        mouth_aspect=float(mouth),
        orientation=orientation,
        eyes_closed=eyes_closed,
        possible_yawn=possible_yawn,
        confidence=conf,
        observation_quality=quality,
        label_pt=label_pt(orientation),
        roll=float(roll),
        ear_left=float(ear_l),
        ear_right=float(ear_r),
        provider="mediapipe",
        landmarks_quality=lq,
        smile_score=float(smile),
    )
