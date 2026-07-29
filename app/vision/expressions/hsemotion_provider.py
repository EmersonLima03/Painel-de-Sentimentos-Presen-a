"""HSEmotion provider — import lazy; falha → inconclusive."""

from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from app.vision.domain import FacialExpressionPrediction
from app.vision.expressions.normalization import normalize_probabilities, pick_label


class HSEmotionProvider:
    provider_name = "hsemotion"
    model_name = "enet_b0_8_best_afew"
    model_version = "unset"

    def __init__(self, model_name: str = "enet_b0_8_best_afew", minimum_confidence: float = 0.55):
        self.model_name = model_name
        self.minimum_confidence = minimum_confidence
        self._model = None
        self._failed = False
        self._health_cache: Optional[dict] = None
        self._health_ts: float = 0.0

    def health(self, *, force: bool = False) -> dict:
        now = time.time()
        if not force and self._health_cache and now - self._health_ts < 30.0:
            return self._health_cache
        if self._failed:
            h = {"status": "unavailable", "provider": self.provider_name, "reason": "import_failed"}
        else:
            try:
                import importlib.util

                if importlib.util.find_spec("hsemotion") is None:
                    h = {
                        "status": "dependency_missing",
                        "provider": self.provider_name,
                        "reason": "hsemotion_not_installed",
                    }
                else:
                    h = {
                        "status": "available",
                        "provider": self.provider_name,
                        "model_name": self.model_name,
                    }
            except Exception as e:
                h = {"status": "unavailable", "provider": self.provider_name, "reason": str(e)}
        self._health_cache = h
        self._health_ts = now
        return h

    def _ensure(self) -> bool:
        if self._failed:
            return False
        if self._model is not None:
            return True
        try:
            from hsemotion.facial_emotions import HSEmotionRecognizer  # type: ignore

            self._model = HSEmotionRecognizer(model_name=self.model_name, device="cpu")
            self.model_version = getattr(self._model, "model_name", self.model_name)
            return True
        except Exception:
            self._failed = True
            return False

    def predict_batch(self, face_crops: List[np.ndarray]) -> List[FacialExpressionPrediction]:
        if not self._ensure():
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
        out: List[FacialExpressionPrediction] = []
        for crop in face_crops:
            t0 = time.perf_counter()
            try:
                emotion, scores = self._model.predict_emotions(crop, logits=False)
                if isinstance(scores, dict):
                    raw = {str(k): float(v) for k, v in scores.items()}
                else:
                    raw = {str(emotion): 0.7}
                probs = normalize_probabilities(raw)
                label, conf, ok = pick_label(probs, minimum_confidence=self.minimum_confidence)
                out.append(
                    FacialExpressionPrediction(
                        label=label,
                        probabilities=probs,
                        confidence=conf,
                        provider=self.provider_name,
                        inference_ms=(time.perf_counter() - t0) * 1000.0,
                        face_quality=0.6,
                        is_conclusive=ok,
                        raw_label=str(emotion),
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
