"""FER legado (Mini-XCEPTION) como provider — lazy import."""

from __future__ import annotations

import time
from typing import List

import numpy as np

from app.vision.domain import FacialExpressionPrediction
from app.vision.expressions.normalization import normalize_probabilities, pick_label


class FerLegacyProvider:
    provider_name = "fer_legacy"
    model_name = "mini_xception_fer2013"
    model_version = "106-0.65"

    def __init__(self, minimum_confidence: float = 0.60):
        self.minimum_confidence = minimum_confidence
        self._available = None

    def predict_batch(self, face_crops: List[np.ndarray]) -> List[FacialExpressionPrediction]:
        out: List[FacialExpressionPrediction] = []
        try:
            from app.vision.emotion_engagement import is_emotion_backend_available, predict_emotion_detail
        except Exception:
            return [
                FacialExpressionPrediction(
                    label="inconclusive",
                    probabilities={"inconclusive": 1.0},
                    confidence=0.0,
                    provider=self.provider_name,
                    inference_ms=0.0,
                    face_quality=0.0,
                    is_conclusive=False,
                )
                for _ in face_crops
            ]

        if not is_emotion_backend_available():
            return [
                FacialExpressionPrediction(
                    label="inconclusive",
                    probabilities={"inconclusive": 1.0},
                    confidence=0.0,
                    provider=self.provider_name,
                    inference_ms=0.0,
                    face_quality=0.0,
                    is_conclusive=False,
                )
                for _ in face_crops
            ]

        for crop in face_crops:
            t0 = time.perf_counter()
            try:
                detail = predict_emotion_detail(crop)
                # (state, conf, emotion_label, model_version, backend)
                if isinstance(detail, (tuple, list)) and len(detail) >= 2:
                    raw_label = detail[0]
                    conf_raw = float(detail[1])
                    raw_probs = {str(raw_label): conf_raw}
                else:
                    raw_label = None
                    raw_probs = {}
                probs = normalize_probabilities(raw_probs)
                label, conf, ok = pick_label(probs, minimum_confidence=self.minimum_confidence)
                out.append(
                    FacialExpressionPrediction(
                        label=label,
                        probabilities=probs,
                        confidence=conf,
                        provider=self.provider_name,
                        inference_ms=(time.perf_counter() - t0) * 1000.0,
                        face_quality=0.5,
                        is_conclusive=ok,
                        raw_label=str(raw_label) if raw_label else None,
                    )
                )
            except Exception:
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
