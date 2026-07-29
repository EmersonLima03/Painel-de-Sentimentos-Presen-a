"""
Engajamento por expressão facial (Real-Time-Classroom + Engagement-Recognition).

- Detecção de emoção: Mini-Xception (FER2013), inspirado no repo Sourish97.
- Mapeamento engaged/disengaged: Nezami et al. 2019 (repo omidmnezami).
- Fallback: heurística leve se TensorFlow não estiver instalado.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)

# FER2013 7 classes (Mini-Xception comum)
EMOTION_LABELS = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]

# Sala de aula (calibrado): FER2013 erra muito sad/fear em rosto neutro + fone/sombra.
# Só angry/disgust são "distraído" forte; sad/fear exigem confiança alta.
STRONG_DISTRACTED = {"angry", "disgust"}
SOFT_NEGATIVE = {"fear", "sad"}  # abaixo do limiar → neutro
ATTENTIVE_EMOTIONS = {"happy", "surprise"}

_state_history: list = []
_history_max = 5
_soft_negative_min_conf = 0.58
_weak_pred_min_conf = 0.40
_happy_prob_min = 0.14          # FER raramente dá happy como 1º na webcam
_smile_heuristic_threshold = 0.28  # webcam + fone; reforço principal agora é MediaPipe smile_score

_model = None
_model_lock = threading.Lock()
_model_path: Optional[Path] = None


def default_model_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "models" / "_mini_XCEPTION.106-0.65.hdf5"


def _download_model(dest: Path) -> bool:
    try:
        import urllib.request

        dest.parent.mkdir(parents=True, exist_ok=True)
        url = (
            "https://github.com/abhijeet3922/FaceEmotion_ID/raw/master/"
            "models/_mini_XCEPTION.106-0.65.hdf5"
        )
        logger.info("emotion_model_download_start", url=url)
        urllib.request.urlretrieve(url, dest)
        return dest.is_file() and dest.stat().st_size > 10000
    except Exception as e:
        logger.warning("emotion_model_download_failed", error=str(e))
        return False


def _load_model(path: Path):
    global _model, _model_path
    with _model_lock:
        if _model is not None and _model_path == path:
            return _model
        try:
            from tf_keras.models import load_model
        except ImportError:
            try:
                from tensorflow.keras.models import load_model
            except ImportError:
                raise RuntimeError("tf-keras ou tensorflow necessario para engajamento por emocao")

        if not path.is_file():
            if not _download_model(path):
                raise FileNotFoundError(f"Modelo de emocao nao encontrado: {path}")

        _model = load_model(str(path), compile=False)
        _model.predict(np.zeros((1, 48, 48, 1), dtype=np.float32), verbose=0)
        _model_path = path
        logger.info("emotion_model_loaded", path=str(path))
        return _model


def _preprocess_face_gray(face_bgr: np.ndarray) -> np.ndarray:
    """Normaliza iluminação (webcam/fone costumam escurecer olhos no FER)."""
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        gray = clahe.apply(gray)
    except Exception:
        pass
    return cv2.resize(gray, (48, 48), interpolation=cv2.INTER_AREA)


def _smile_heuristic_score(face_bgr: np.ndarray) -> float:
    """
    Sorriso via região da boca (webcam 48/64px do FER perde sorriso).
    Boca mais larga + contraste (dentes) → score alto.
    """
    if face_bgr is None or face_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    if h < 24 or w < 24:
        return 0.0
    mouth = gray[int(h * 0.55) : int(h * 0.95), int(w * 0.10) : int(w * 0.90)]
    if mouth.size == 0:
        return 0.0
    mh, mw = mouth.shape[:2]
    aspect = mw / max(mh, 1)
    std = float(np.std(mouth))
    mean_b = float(np.mean(mouth))
    # dentes = pixels claros na faixa inferior da boca
    bright_frac = float(np.mean(mouth > 140))
    score = 0.0
    if aspect >= 2.2:
        score += 0.28
    if aspect >= 3.0:
        score += 0.12
    if std >= 18:
        score += 0.22
    if std >= 28:
        score += 0.10
    if mean_b >= 75:
        score += 0.12
    if bright_frac >= 0.08:
        score += 0.18
    if bright_frac >= 0.18:
        score += 0.12
    return min(1.0, score)


def apply_smile_boost_to_fer_probs(
    face_bgr: np.ndarray,
    raw_probs: Dict[str, float],
    *,
    raw_label: Optional[str] = None,
) -> Tuple[Dict[str, float], str, str]:
    """
    Aplica heurística de sorriso sobre probs FER (TF ou ONNX).
    Retorna (probs_ajustadas, raw_label_efetivo, source).
    source: model|smile|happy_prob
    """
    probs = dict(raw_probs or {})
    smile_s = _smile_heuristic_score(face_bgr)
    happy = float(probs.get("happy", 0.0) or 0.0)
    source = "model"
    label = (raw_label or "").strip().lower() or "neutral"

    if smile_s >= _smile_heuristic_threshold:
        probs["happy"] = max(happy, smile_s)
        # reduz empate com neutral (FER+ tende a neutro em sorriso)
        if float(probs.get("neutral", 0.0) or 0.0) > 0:
            probs["neutral"] = float(probs["neutral"]) * 0.45
        label = "happy"
        source = "smile"
    elif happy >= _happy_prob_min:
        # happy forte no top (mesmo se não for argmax)
        top = max(probs.values()) if probs else 0.0
        if happy >= top * 0.45 or happy >= 0.22:
            probs["happy"] = max(happy, float(probs.get("happy", 0.0)))
            label = "happy"
            source = "happy_prob"

    return probs, label, source


def _resolve_label_from_probs(pred: np.ndarray, face_bgr: np.ndarray) -> Tuple[str, float, str]:
    """
    Escolhe emoção efetiva: argmax + happy no top2 + heurística de sorriso.
    Retorna (label, conf, source) com source model|smile|happy_prob.
    """
    idx = int(np.argmax(pred))
    conf = float(pred[idx])
    label = EMOTION_LABELS[idx] if idx < len(EMOTION_LABELS) else "neutral"

    happy_prob = float(pred[3]) if len(pred) > 3 else 0.0
    surprise_prob = float(pred[5]) if len(pred) > 5 else 0.0
    sorted_idx = np.argsort(pred)[::-1]
    second_idx = int(sorted_idx[1]) if len(sorted_idx) > 1 else idx
    second_label = EMOTION_LABELS[second_idx] if second_idx < len(EMOTION_LABELS) else ""

    smile_s = _smile_heuristic_score(face_bgr)
    if smile_s >= _smile_heuristic_threshold:
        return "happy", max(conf, smile_s), "smile"

    if happy_prob >= _happy_prob_min and happy_prob >= float(pred[idx]) * 0.45:
        return "happy", happy_prob, "happy_prob"

    if second_label == "happy" and float(pred[second_idx]) >= _happy_prob_min:
        return "happy", float(pred[second_idx]), "happy_prob"

    if surprise_prob >= 0.20 and surprise_prob >= conf * 0.5:
        return "surprise", surprise_prob, "model"

    return label, conf, "model"


def _map_emotion_to_state(label: str, conf: float, *, smile_boost: bool = False) -> str:
    if smile_boost or label == "happy":
        return "attentive"
    if conf < _weak_pred_min_conf:
        return "neutral"
    if label in STRONG_DISTRACTED:
        return "distracted"
    if label in SOFT_NEGATIVE:
        return "distracted" if conf >= _soft_negative_min_conf else "neutral"
    if label in ATTENTIVE_EMOTIONS:
        return "attentive"
    if label == "neutral":
        return "neutral"
    return "neutral"


def _smooth_state(state: str) -> str:
    """Voto majoritário; empate favorece attentive > neutral > distracted."""
    global _state_history
    _state_history.append(state)
    if len(_state_history) > _history_max:
        _state_history = _state_history[-_history_max:]
    if len(_state_history) < 2:
        return state
    priority = {"attentive": 2, "neutral": 1, "distracted": 0}
    counts: Dict[str, int] = {}
    for s in _state_history:
        counts[s] = counts.get(s, 0) + 1
    best = max(counts, key=lambda s: (counts[s], priority.get(s, 0)))
    return best


def emotion_backend_health() -> dict:
    """
    Health check real do FER.
    Ordem: TensorFlow Mini-XCEPTION → ONNX emotion-ferplus (fallback sem TF).
    status: available | dependency_missing | model_missing | model_incompatible | inference_failed
    """
    import importlib.util

    has_tf = (
        importlib.util.find_spec("tf_keras") is not None
        or importlib.util.find_spec("tensorflow") is not None
    )
    path = default_model_path()

    if has_tf and path.is_file():
        try:
            model = _load_model(path)
            model.predict(np.zeros((1, 48, 48, 1), dtype=np.float32), verbose=0)
            return {
                "status": "available",
                "provider": "fer_legacy",
                "reason": None,
                "model_path": str(path),
                "model_name": "mini-xception",
                "model_version": "106-0.65",
                "backend": "tensorflow",
            }
        except Exception as e:
            msg = str(e).lower()
            status = "inference_failed"
            if "compatibil" in msg or "hdf5" in msg or "deserialize" in msg:
                status = "model_incompatible"
            tf_fail = {
                "status": status,
                "provider": "fer_legacy",
                "reason": f"{type(e).__name__}:{e}",
                "model_path": str(path),
            }
            # tenta ONNX
            from app.vision.fer_onnx import onnx_fer_health

            oh = onnx_fer_health()
            if oh.get("status") == "available":
                oh["fallback_from"] = tf_fail
                return oh
            return tf_fail

    # Sem TF ou sem hdf5 → ONNX
    from app.vision.fer_onnx import onnx_fer_health

    oh = onnx_fer_health()
    if oh.get("status") == "available":
        oh["note"] = "tensorflow_unavailable_using_onnx_ferplus"
        return oh

    if not has_tf:
        return {
            "status": "dependency_missing",
            "provider": "fer_legacy",
            "reason": "tensorflow_or_tf_keras_missing_and_onnx_unavailable",
            "model_path": str(path),
            "onnx": oh,
        }
    if not path.is_file():
        return {
            "status": "model_missing",
            "provider": "fer_legacy",
            "reason": "hdf5_not_found",
            "model_path": str(path),
            "onnx": oh,
        }
    return oh


def is_emotion_backend_available() -> bool:
    """True somente se dependências + modelo + smoke inference ok."""
    try:
        return emotion_backend_health().get("status") == "available"
    except Exception:
        return False


def _analyze_face(face_bgr: np.ndarray, *, smile_boost: bool = False) -> Tuple[str, float, str, str, str]:
    """Retorna label, conf, state_smooth, state_raw, source."""
    health = emotion_backend_health()
    backend = health.get("backend") or health.get("provider")

    if health.get("provider") == "fer_onnx" or health.get("model_name") == "emotion-ferplus-8":
        from app.vision.fer_onnx import FERPLUS_LABELS, _TO_FER2013, predict_emotion_onnx

        label, conf, probs_arr = predict_emotion_onnx(face_bgr)
        raw_probs = {}
        for i, name in enumerate(FERPLUS_LABELS):
            if i < len(probs_arr):
                fer = _TO_FER2013.get(name, name)
                raw_probs[fer] = raw_probs.get(fer, 0.0) + float(probs_arr[i])
        source = "model"
        if smile_boost:
            raw_probs, label, source = apply_smile_boost_to_fer_probs(
                face_bgr, raw_probs, raw_label=label
            )
        else:
            # Sem boost: argmax puro
            if raw_probs:
                label = max(raw_probs.items(), key=lambda kv: kv[1])[0]
                conf = float(raw_probs[label])
        conf = float(raw_probs.get(label, conf) if label in raw_probs else conf)
        if source == "smile":
            conf = max(conf, float(raw_probs.get("happy", conf)))
        raw_state = _map_emotion_to_state(label, conf, smile_boost=source == "smile")
        state = _smooth_state(raw_state)
        if source == "smile" and state == "neutral":
            state = "attentive"
        return label, conf, state, raw_state, source

    # TensorFlow Mini-XCEPTION
    face48 = _preprocess_face_gray(face_bgr)
    x = face48.astype("float32") / 255.0
    x = x.reshape(1, 48, 48, 1)
    model = _load_model(_model_path or default_model_path())
    pred = model.predict(x, verbose=0)[0]

    label, conf, source = _resolve_label_from_probs(pred, face_bgr) if smile_boost else (
        (EMOTION_LABELS[int(np.argmax(pred))], float(pred[int(np.argmax(pred))]), "model")
        if len(pred)
        else ("neutral", 0.0, "model")
    )
    if not smile_boost and source == "model":
        # Sem boost: usa argmax puro do modelo
        idx = int(np.argmax(pred))
        label = EMOTION_LABELS[idx] if idx < len(EMOTION_LABELS) else "neutral"
        conf = float(pred[idx])
        source = "model"
    smile_flag = smile_boost and source == "smile"
    raw_state = _map_emotion_to_state(label, conf, smile_boost=smile_flag)
    state = _smooth_state(raw_state)
    if smile_flag and state == "neutral":
        state = "attentive"
    return label, conf, state, raw_state, source


def predict_emotion(face_bgr: np.ndarray) -> Tuple[str, float, str]:
    """
    Retorna (emotion_label, confidence, engagement_state).
    engagement_state: attentive | neutral | distracted
    """
    label, conf, state, _, _ = _analyze_face(face_bgr, smile_boost=False)
    return label, conf, state


def predict_emotion_detail(
    face_bgr: np.ndarray, *, smile_boost: bool = False
) -> Tuple[str, float, str, str, str]:
    """Retorna label, conf, state_smooth, state_raw, source (model|smile|happy_prob|onnx)."""
    label, conf, state, raw_state, source = _analyze_face(face_bgr, smile_boost=smile_boost)
    return label, conf, state, raw_state, source