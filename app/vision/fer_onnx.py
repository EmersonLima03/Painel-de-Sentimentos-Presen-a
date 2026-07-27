"""Inferência FER via ONNX Runtime (fallback sem TensorFlow).

Usa emotion-ferplus-8.onnx (ONNX Model Zoo) quando Mini-XCEPTION/TF não está disponível.
Mesmo contrato de saída que o FER legado: label FER2013-like + confiança.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)

# emotion-ferplus-8
FERPLUS_LABELS = [
    "neutral",
    "happiness",
    "surprise",
    "sadness",
    "anger",
    "disgust",
    "fear",
    "contempt",
]

# Map to Mini-XCEPTION / FER2013-ish labels used by normalization
_TO_FER2013 = {
    "neutral": "neutral",
    "happiness": "happy",
    "surprise": "surprise",
    "sadness": "sad",
    "anger": "angry",
    "disgust": "disgust",
    "fear": "fear",
    "contempt": "disgust",
}

_session = None
_lock = threading.Lock()
_input_name = None
_error: Optional[str] = None


def default_onnx_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "models" / "emotion-ferplus-8.onnx"


def _load_session():
    global _session, _input_name, _error
    with _lock:
        if _session is not None:
            return _session
        path = default_onnx_path()
        if not path.is_file():
            _error = "onnx_model_missing"
            raise FileNotFoundError(str(path))
        import onnxruntime as ort

        _session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        _input_name = _session.get_inputs()[0].name
        # smoke
        dummy = np.zeros((1, 1, 64, 64), dtype=np.float32)
        _session.run(None, {_input_name: dummy})
        _error = None
        logger.info("fer_onnx_loaded", path=str(path), provider="emotion_ferplus_onnx")
        return _session


def onnx_fer_health() -> dict:
    try:
        path = default_onnx_path()
        if not path.is_file():
            return {
                "status": "model_missing",
                "provider": "fer_onnx",
                "reason": "emotion-ferplus-8.onnx missing",
                "model_path": str(path),
            }
        import importlib.util

        if importlib.util.find_spec("onnxruntime") is None:
            return {
                "status": "dependency_missing",
                "provider": "fer_onnx",
                "reason": "onnxruntime_missing",
                "model_path": str(path),
            }
        _load_session()
        return {
            "status": "available",
            "provider": "fer_onnx",
            "model_name": "emotion-ferplus-8",
            "model_version": "onnx-zoo",
            "model_path": str(path),
            "reason": None,
        }
    except Exception as e:
        return {
            "status": "inference_failed",
            "provider": "fer_onnx",
            "reason": f"{type(e).__name__}:{e}",
            "model_path": str(default_onnx_path()),
        }


def predict_emotion_onnx(face_bgr: np.ndarray) -> Tuple[str, float, np.ndarray]:
    """Retorna (fer2013_label, confidence, probs_ferplus)."""
    sess = _load_session()
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        gray = clahe.apply(gray)
    except Exception:
        pass
    face = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    x = face.astype(np.float32).reshape(1, 1, 64, 64)
    # ferplus expects mean-centered roughly; many impls just /255
    x = x / 255.0
    out = sess.run(None, {_input_name: x})[0]
    logits = np.array(out).reshape(-1)
    # softmax
    e = np.exp(logits - np.max(logits))
    probs = e / np.sum(e)
    idx = int(np.argmax(probs))
    raw = FERPLUS_LABELS[idx] if idx < len(FERPLUS_LABELS) else "neutral"
    label = _TO_FER2013.get(raw, "neutral")
    conf = float(probs[idx])
    return label, conf, probs
