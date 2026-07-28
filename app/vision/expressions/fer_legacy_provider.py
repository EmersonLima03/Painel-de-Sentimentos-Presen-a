"""FER legado (Mini-XCEPTION) como provider — lazy import + health check real."""

from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from app.vision.domain import FacialExpressionPrediction
from app.vision.expressions.normalization import normalize_probabilities, pick_label


class FerLegacyProvider:
    provider_name = "fer_legacy"
    model_name = "mini_xception_fer2013"
    model_version = "106-0.65"

    def __init__(self, minimum_confidence: float = 0.60):
        self.minimum_confidence = minimum_confidence
        self._health_cache: Optional[dict] = None
        self._health_ts: float = 0.0

    def health(self, *, force: bool = False) -> dict:
        now = time.time()
        if not force and self._health_cache and now - self._health_ts < 30.0:
            return self._health_cache
        try:
            from app.vision.emotion_engagement import emotion_backend_health

            h = emotion_backend_health()
        except Exception as e:
            h = {
                "status": "dependency_missing",
                "provider": self.provider_name,
                "reason": str(e),
            }
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

        from app.vision.emotion_engagement import (
            apply_smile_boost_to_fer_probs,
            emotion_backend_health,
            predict_emotion_detail,
        )

        health = self.health()
        use_onnx = health.get("provider") == "fer_onnx" or health.get("model_name") == "emotion-ferplus-8"

        for crop in face_crops:
            t0 = time.perf_counter()
            try:
                if use_onnx:
                    from app.vision.fer_onnx import predict_emotion_onnx
                    from app.vision.fer_onnx import FERPLUS_LABELS, _TO_FER2013

                    label, conf_raw, probs_arr = predict_emotion_onnx(crop)
                    raw_probs = {}
                    for i, name in enumerate(FERPLUS_LABELS):
                        if i < len(probs_arr):
                            fer = _TO_FER2013.get(name, name)
                            raw_probs[fer] = raw_probs.get(fer, 0.0) + float(probs_arr[i])
                    raw_probs, label, smile_src = apply_smile_boost_to_fer_probs(
                        crop, raw_probs, raw_label=str(label)
                    )
                    probs = normalize_probabilities(raw_probs)
                    label_n, conf, ok = pick_label(probs, minimum_confidence=self.minimum_confidence)
                    if smile_src == "smile":
                        label_n = "positive"
                        conf = max(conf, float(raw_probs.get("happy", conf)))
                        ok = True
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
                    continue

                detail = predict_emotion_detail(crop)
                if isinstance(detail, (tuple, list)) and len(detail) >= 2:
                    raw_label = detail[0]
                    conf_raw = float(detail[1])
                    source = detail[4] if len(detail) >= 5 else "model"
                    raw_probs = {str(raw_label): conf_raw}
                    if source == "smile" or str(raw_label).lower() == "happy":
                        raw_probs = {"happy": max(conf_raw, 0.5), "neutral": 0.2}
                else:
                    raw_label = None
                    raw_probs = {}
                    source = "model"
                probs = normalize_probabilities(raw_probs)
                label, conf, ok = pick_label(probs, minimum_confidence=self.minimum_confidence)
                if source == "smile" or str(raw_label).lower() == "happy":
                    label = "positive"
                    conf = max(conf, conf_raw if isinstance(detail, (tuple, list)) else conf)
                    ok = True
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
                # invalidate health so next call re-probes
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
