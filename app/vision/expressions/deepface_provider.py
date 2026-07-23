"""DeepFace provider — somente actions=['emotion']; lazy; venv isolado recomendado."""

from __future__ import annotations

import time
from typing import List

import numpy as np

from app.vision.domain import FacialExpressionPrediction
from app.vision.expressions.normalization import normalize_probabilities, pick_label


class DeepFaceProvider:
    provider_name = "deepface"
    model_name = "deepface-emotion"
    model_version = "actions-emotion-only"

    def __init__(self, minimum_confidence: float = 0.60):
        self.minimum_confidence = minimum_confidence
        self._failed = False

    def predict_batch(self, face_crops: List[np.ndarray]) -> List[FacialExpressionPrediction]:
        if self._failed:
            return self._inconclusive(face_crops, 0.0)
        try:
            from deepface import DeepFace  # type: ignore
        except Exception:
            self._failed = True
            return self._inconclusive(face_crops, 0.0)

        out: List[FacialExpressionPrediction] = []
        for crop in face_crops:
            t0 = time.perf_counter()
            try:
                # Nunca race/gender/age
                results = DeepFace.analyze(
                    crop,
                    actions=["emotion"],
                    enforce_detection=False,
                    silent=True,
                )
                if isinstance(results, list):
                    results = results[0] if results else {}
                raw = (results or {}).get("emotion") or {}
                probs = normalize_probabilities({str(k): float(v) for k, v in raw.items()})
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
                        raw_label=(results or {}).get("dominant_emotion"),
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

    def _inconclusive(self, face_crops: List[np.ndarray], ms: float) -> List[FacialExpressionPrediction]:
        return [
            FacialExpressionPrediction(
                label="inconclusive",
                probabilities={"inconclusive": 1.0},
                confidence=0.0,
                provider=self.provider_name,
                inference_ms=ms,
                face_quality=0.0,
                is_conclusive=False,
            )
            for _ in face_crops
        ]
