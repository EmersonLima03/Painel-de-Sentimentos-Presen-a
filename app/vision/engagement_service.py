"""Factory de cálculo de engajamento por face (head_pose | emoção | heurística)."""

from typing import Callable, Tuple

import numpy as np

from app.config import get_settings
from app.logging import get_logger
from app.vision.engagement import calculate_engagement_state as heuristic_state

logger = get_logger(__name__)

StateFn = Callable[[np.ndarray, tuple], str]


def _make_head_pose_fn() -> StateFn:
    from app.vision.head_pose_engagement import calculate_head_pose_engagement

    def _fn(face_roi: np.ndarray, bbox: tuple) -> str:
        state, _, _ = calculate_head_pose_engagement(face_roi, bbox)
        return state

    return _fn


def _make_emotion_fn() -> StateFn:
    from app.vision.emotion_engagement import predict_emotion

    def _fn(face_roi: np.ndarray, bbox: tuple) -> str:
        try:
            _, _, state = predict_emotion(face_roi)
            return state
        except Exception as e:
            logger.debug("emotion_predict_fallback", error=str(e))
            return heuristic_state(face_roi, bbox)

    return _fn


def _make_hybrid_fn() -> StateFn:
    """Híbrido atual: pose da cabeça (principal) + heurística se landmarks falharem."""
    head_fn = _make_head_pose_fn()

    def _fn(face_roi: np.ndarray, bbox: tuple) -> str:
        from app.vision.head_pose_engagement import calculate_head_pose_engagement

        state, _, dbg = calculate_head_pose_engagement(face_roi, bbox)
        if dbg.get("reason") in ("no_landmarks", "face_too_small"):
            return heuristic_state(face_roi, bbox)
        return state

    return _fn


def get_engagement_calculator() -> Tuple[StateFn, str]:
    """
    Retorna (função de estado, model_version para eventos).
    """
    settings = get_settings()
    backend = (
        getattr(settings, "vision_engagement_backend", None) or "head_pose"
    ).strip().lower()
    version = getattr(settings, "vision_engagement_model_version", None) or "eng-v2-headpose"

    if backend in ("heuristic", "brightness"):
        return heuristic_state, "eng-v0-heuristic"

    if backend in ("head_pose", "headpose", "classroom", "pose"):
        from app.vision.head_pose_engagement import is_head_pose_available

        if is_head_pose_available():
            return _make_head_pose_fn(), version
        logger.warning("head_pose_unavailable", fallback="heuristic")
        return heuristic_state, "eng-v0-heuristic"

    if backend == "emotion":
        from app.vision.emotion_engagement import is_emotion_backend_available

        if is_emotion_backend_available():
            return _make_emotion_fn(), version
        logger.warning("engagement_emotion_unavailable", fallback="head_pose")
        from app.vision.head_pose_engagement import is_head_pose_available

        if is_head_pose_available():
            return _make_head_pose_fn(), "eng-v2-headpose"
        return heuristic_state, "eng-v0-heuristic"

    # hybrid = head_pose + fallback heurístico (recomendado produção)
    from app.vision.head_pose_engagement import is_head_pose_available

    if is_head_pose_available():
        return _make_hybrid_fn(), version if version else "eng-v2-headpose"
    return heuristic_state, "eng-v0-heuristic"
