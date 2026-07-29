"""Provider FER+ ONNX (emotion-ferplus-8) — perfil TRI / entrega.

Não substitui HSEmotion no default; ativar via EXPRESSION_PROVIDER=fer_onnx
ou overlay config.tri.yaml (PRESENCA_CONFIG_OVERLAY).
"""

from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from app.vision.domain import FacialExpressionPrediction
from app.vision.expressions.normalization import normalize_probabilities, pick_label
from app.vision.fer_onnx import (
    FERPLUS_LABELS,
    _TO_FER2013,
    onnx_fer_health,
    predict_emotion_onnx,
)


class FerOnnxProvider:
    provider_name = "fer_onnx"
    model_name = "emotion-ferplus-8"
    model_version = "onnx-zoo"

    def __init__(self, minimum_confidence: float = 0.45):
        self.minimum_confidence = minimum_confidence
        self._health_cache: Optional[dict] = None
        self._health_ts: float = 0.0

    def health(self, *, force: bool = False) -> dict:
        now = time.time()
        if not force and self._health_cache and now - self._health_ts < 30.0:
            return self._health_cache
        h = onnx_fer_health()
        self._health_cache = h
        self._health_ts = now
        return h

    @property
    def is_available(self) -> bool:
        return self.health().get("status") == "available"

    def predict_batch(self, face_crops: List[np.ndarray]) -> List[FacialExpressionPrediction]:
        out: List[FacialExpressionPrediction] = []
        health = self.health()
        if health.get("status") != "available":
            return [
                FacialExpressionPrediction(
                    label="inconclusive",
                    probabilities={"inconclusive": 1.0},
                    confidence=0.0,
                    provider=self.provider_name,
                    inference_ms=0.0,
                    face_quality=0.0,
                    is_conclusive=False,
                    raw_label=None,
                )
                for _ in face_crops
            ]

        for crop in face_crops:
            t0 = time.perf_counter()
            try:
                label, _conf_raw, probs_arr = predict_emotion_onnx(crop)
                raw_probs: dict = {}
                for i, name in enumerate(FERPLUS_LABELS):
                    if i < len(probs_arr):
                        fer = _TO_FER2013.get(name, name)
                        raw_probs[fer] = raw_probs.get(fer, 0.0) + float(probs_arr[i])
                probs = normalize_probabilities(raw_probs)
                label_n, conf, ok = pick_label(probs, minimum_confidence=self.minimum_confidence)
                out.append(
                    FacialExpressionPrediction(
                        label=label_n,
                        probabilities=probs,
                        confidence=conf,
                        provider=self.provider_name,
                        inference_ms=(time.perf_counter() - t0) * 1000.0,
                        face_quality=0.5,
                        is_conclusive=ok,
                        raw_label=str(label),
                    )
                )
            except Exception:
                self._health_cache = {
                    "status": "inference_failed",
                    "provider": self.provider_name,
                    "reason": "predict_exception",
                }
                self._health_ts = time.time()
                out.append(
                    FacialExpressionPrediction(
                        label="inconclusive",
                        probabilities={"inconclusive": 1.0},
                        confidence=0.0,
                        provider=self.provider_name,
                        inference_ms=(time.perf_counter() - t0) * 1000.0,
                        face_quality=0.0,
                        is_conclusive=False,
                    )
                )
        return out
