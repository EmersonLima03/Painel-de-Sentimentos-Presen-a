"""Provider HSEmotion VGAF (`enet_b0_8_best_vgaf`) — backend default de emoção (2026-09-09).

Ativar/confirmar via:
  expression.emotion_backend: hsemotion_vgaf
  ou EXPRESSION_EMOTION_BACKEND=hsemotion_vgaf

Rollback para FER+:
  expression.emotion_backend: fer_onnx
  ou EXPRESSION_EMOTION_BACKEND=fer_onnx

Inferência deve rodar apenas no AsyncEmotionWorker (não no loop principal).

Mapping canônico (documentado):
  Happiness/Happy → happy → positive
  Neutral → neutral
  Sadness/Sad → sad → negative
  Anger/Angry → angry → negative
  Fear/Disgust/Contempt → negative (contrato atual)
  Surprise → inconclusive
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from app.vision.domain import FacialExpressionPrediction
from app.vision.expressions.normalization import normalize_probabilities, pick_label

logger = logging.getLogger(__name__)

# Mapping explícito raw HSEmotion → FER-like (antes da normalização de produto)
_RAW_TO_FER = {
    "anger": "angry",
    "angry": "angry",
    "contempt": "disgust",
    "disgust": "disgust",
    "fear": "fear",
    "happiness": "happy",
    "happy": "happy",
    "neutral": "neutral",
    "sadness": "sad",
    "sad": "sad",
    "surprise": "surprise",
}

HSEMOTION_VGAF_MAPPING_DOC = {
    "happy": "positive",
    "neutral": "neutral",
    "sad": "negative",
    "angry": "negative",
    "fear": "negative",
    "disgust": "negative",
    "surprise": "inconclusive",
}


class HSEmotionVgafProvider:
    """Inferência síncrona VGAF — usada pelo worker assíncrono, não pelo loop principal."""

    provider_name = "hsemotion_vgaf"
    model_name = "enet_b0_8_best_vgaf"
    model_version = "unset"

    def __init__(
        self,
        model_name: str = "enet_b0_8_best_vgaf",
        minimum_confidence: float = 0.45,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.minimum_confidence = minimum_confidence
        self.device = device
        self._model = None
        self._failed = False
        self._fail_reason: Optional[str] = None
        self._health_cache: Optional[dict] = None
        self._health_ts: float = 0.0

    def health(self, *, force: bool = False) -> dict:
        now = time.time()
        if not force and self._health_cache and now - self._health_ts < 30.0:
            return self._health_cache
        if self._failed:
            h = {
                "status": "unavailable",
                "provider": self.provider_name,
                "reason": self._fail_reason or "model_load_failed",
            }
        else:
            try:
                import importlib.util

                if importlib.util.find_spec("hsemotion") is None:
                    h = {
                        "status": "dependency_missing",
                        "provider": self.provider_name,
                        "reason": "hsemotion_not_installed",
                    }
                elif not self._ensure():
                    h = {
                        "status": "unavailable",
                        "provider": self.provider_name,
                        "reason": self._fail_reason or "model_load_failed",
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

    @property
    def is_available(self) -> bool:
        return self.health().get("status") == "available"

    def _ensure(self) -> bool:
        if self._failed:
            return False
        if self._model is not None:
            return True
        try:
            import torch
            from hsemotion.facial_emotions import HSEmotionRecognizer  # type: ignore

            # Prefer pesos do experiment se existirem
            local = (
                Path(__file__).resolve().parents[3]
                / "experiments"
                / "ex_emotion_model_benchmark"
                / "models"
                / f"{self.model_name}.pt"
            )
            cache = Path.home() / ".hsemotion" / f"{self.model_name}.pt"
            if local.is_file() and local.stat().st_size > 5_000_000:
                cache.parent.mkdir(parents=True, exist_ok=True)
                if (not cache.is_file()) or cache.stat().st_size < 5_000_000:
                    import shutil

                    shutil.copy2(local, cache)

            orig_load = torch.load

            def _load_trusted(*args, **kwargs):
                kwargs.setdefault("weights_only", False)
                return orig_load(*args, **kwargs)

            torch.load = _load_trusted  # type: ignore
            try:
                self._model = HSEmotionRecognizer(model_name=self.model_name, device=self.device)
            finally:
                torch.load = orig_load  # type: ignore

            self.model_version = getattr(self._model, "model_name", self.model_name)
            # warm-up
            dummy = np.zeros((224, 224, 3), dtype=np.uint8)
            self._model.predict_emotions(dummy, logits=False)
            return True
        except Exception as e:
            self._failed = True
            self._fail_reason = f"{type(e).__name__}:{e}"
            logger.warning("hsemotion_vgaf_model_load_failed: %s", e)
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
                    raw_label=None,
                )
                for _ in face_crops
            ]
        out: List[FacialExpressionPrediction] = []
        for crop in face_crops:
            t0 = time.perf_counter()
            try:
                if crop is None or getattr(crop, "size", 0) == 0:
                    raise ValueError("empty_crop")
                rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                emotion, scores = self._model.predict_emotions(rgb, logits=False)
                if isinstance(scores, dict):
                    raw = {str(k): float(v) for k, v in scores.items()}
                else:
                    arr = np.asarray(scores, dtype=np.float64).reshape(-1)
                    raw = {}
                    for i, name in self._model.idx_to_class.items():
                        raw[str(name)] = float(arr[i]) if i < len(arr) else 0.0
                fer_raw = {_RAW_TO_FER.get(k.lower(), k.lower()): float(v) for k, v in raw.items()}
                # merge duplicates after map
                merged: dict = {}
                for k, v in fer_raw.items():
                    merged[k] = merged.get(k, 0.0) + v
                probs = normalize_probabilities(merged)
                label, conf, ok = pick_label(probs, minimum_confidence=self.minimum_confidence)
                raw_fer = _RAW_TO_FER.get(str(emotion).lower(), str(emotion).lower())
                out.append(
                    FacialExpressionPrediction(
                        label=label,
                        probabilities=probs,
                        confidence=conf,
                        provider=self.provider_name,
                        inference_ms=(time.perf_counter() - t0) * 1000.0,
                        face_quality=0.6,
                        is_conclusive=ok,
                        raw_label=raw_fer,
                    )
                )
            except Exception as e:
                logger.warning("hsemotion_vgaf_predict_failed: %s", e)
                out.append(
                    FacialExpressionPrediction(
                        label="inconclusive",
                        probabilities={"inconclusive": 1.0},
                        confidence=0.0,
                        provider=self.provider_name,
                        inference_ms=(time.perf_counter() - t0) * 1000.0,
                        face_quality=0.0,
                        is_conclusive=False,
                        raw_label=None,
                    )
                )
        return out
