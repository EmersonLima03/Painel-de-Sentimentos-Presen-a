"""Testes FER+ ONNX — gate de entrega TRI.

Suíte genérica: se o modelo estiver ausente, os testes marcados `requires_fer_onnx`
fazem skip.

Gate de fechamento TRI (modelo obrigatório):

  pytest tests/test_fer_onnx.py -m tri -q

Esse marker falha se emotion-ferplus-8.onnx não carregar / inferir / normalizar.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from app.vision.expressions.normalization import NORMALIZED, normalize_expression_label
from app.vision.fer_onnx import default_onnx_path, onnx_fer_health, predict_emotion_onnx

MODEL_PATH = default_onnx_path()
MODEL_PRESENT = MODEL_PATH.is_file()

requires_model = pytest.mark.skipif(
    not MODEL_PRESENT,
    reason="emotion-ferplus-8.onnx ausente — skip fora do gate TRI",
)

tri_gate = pytest.mark.tri


def _synthetic_face(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    face = np.zeros((96, 96, 3), dtype=np.uint8)
    face[:] = (40, 50, 60)
    # “rosto” com variação espacial (não testa acurácia de emoção)
    yy, xx = np.mgrid[0:96, 0:96]
    face[:, :, 0] = np.clip(80 + 40 * np.sin(xx / 12.0) + rng.integers(0, 15, (96, 96)), 0, 255)
    face[:, :, 1] = np.clip(70 + 30 * np.cos(yy / 10.0), 0, 255)
    face[:, :, 2] = np.clip(60 + (xx + yy) // 8, 0, 255)
    return face


def test_model_path_documented():
    assert MODEL_PATH.name == "emotion-ferplus-8.onnx"
    assert "models" in MODEL_PATH.parts


@tri_gate
def test_tri_model_file_must_exist():
    """Gate TRI: arquivo do modelo obrigatório."""
    assert MODEL_PRESENT, f"Modelo TRI ausente: {MODEL_PATH}"


@requires_model
@tri_gate
def test_fer_onnx_health_available():
    h = onnx_fer_health()
    assert h.get("status") == "available", h
    assert h.get("provider") == "fer_onnx"
    assert h.get("model_name") == "emotion-ferplus-8"


@requires_model
@tri_gate
def test_fer_onnx_inference_produces_valid_normalized_state():
    face = _synthetic_face(1)
    t0 = time.perf_counter()
    label, conf, probs = predict_emotion_onnx(face)
    inference_ms = (time.perf_counter() - t0) * 1000.0

    assert isinstance(label, str) and label
    assert 0.0 <= float(conf) <= 1.0
    assert probs is not None and len(probs) >= 1
    assert inference_ms >= 0.0

    norm = normalize_expression_label(label)
    valid = set(NORMALIZED)
    assert norm in valid, f"estado inválido: {norm} (raw={label})"


@requires_model
@tri_gate
def test_fer_onnx_provider_batch():
    from app.vision.expressions import create_expression_provider

    prov = create_expression_provider("fer_onnx")
    h = prov.health(force=True)
    assert h.get("status") == "available", h
    preds = prov.predict_batch([_synthetic_face(2), _synthetic_face(3)])
    assert len(preds) == 2
    for p in preds:
        assert p.label in NORMALIZED
        assert 0.0 <= float(p.confidence) <= 1.0
        assert float(p.inference_ms) >= 0.0
        assert p.provider == "fer_onnx"


@requires_model
@tri_gate
def test_fer_onnx_error_path_handled():
    """Crop inválido não deve derrubar o provider sem tratamento."""
    from app.vision.expressions import create_expression_provider

    prov = create_expression_provider("fer_onnx")
    assert prov.health(force=True).get("status") == "available"
    # imagem minúscula / vazia — deve retornar predicao (possivelmente inconclusiva), não exception
    bad = np.zeros((2, 2, 3), dtype=np.uint8)
    preds = prov.predict_batch([bad])
    assert len(preds) == 1
    assert preds[0].label in NORMALIZED


def test_create_provider_alias_fer_onnx():
    from app.vision.expressions import create_expression_provider

    p = create_expression_provider("fer_onnx")
    assert p.provider_name == "fer_onnx"
