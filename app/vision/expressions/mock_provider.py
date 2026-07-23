"""Mock determinístico para CI / spike sem deps."""

from __future__ import annotations

import time
from typing import List

import numpy as np

from app.vision.domain import FacialExpressionPrediction
from app.vision.expressions.normalization import normalize_probabilities, pick_label


class MockExpressionProvider:
    provider_name = "mock"
    model_name = "mock-deterministic"
    model_version = "v1"

    def __init__(self, minimum_confidence: float = 0.60):
        self.minimum_confidence = minimum_confidence

    def predict_batch(self, face_crops: List[np.ndarray]) -> List[FacialExpressionPrediction]:
        out: List[FacialExpressionPrediction] = []
        for crop in face_crops:
            t0 = time.perf_counter()
            # Determinístico: média de pixels → bucket
            mean = float(np.mean(crop)) if crop is not None and crop.size else 0.0
            if mean > 140:
                raw = {"happy": 0.7, "neutral": 0.2, "sad": 0.1}
            elif mean > 80:
                raw = {"neutral": 0.6, "happy": 0.2, "sad": 0.2}
            else:
                raw = {"sad": 0.55, "neutral": 0.3, "surprise": 0.15}
            probs = normalize_probabilities(raw)
            label, conf, ok = pick_label(probs, minimum_confidence=self.minimum_confidence)
            out.append(
                FacialExpressionPrediction(
                    label=label,
                    probabilities=probs,
                    confidence=conf,
                    provider=self.provider_name,
                    inference_ms=(time.perf_counter() - t0) * 1000.0,
                    face_quality=0.8,
                    is_conclusive=ok,
                    raw_label=max(raw, key=raw.get),
                )
            )
        return out
