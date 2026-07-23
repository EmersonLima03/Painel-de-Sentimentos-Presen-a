"""Normalização ética de expressões aparentes."""

from __future__ import annotations

from typing import Dict, Tuple

# Classes internas normalizadas
NORMALIZED = ("positive", "neutral", "negative", "surprise", "inconclusive")

# Mapeamentos comuns FER / DeepFace / HSEmotion → normalizado
_MAP = {
    "happy": "positive",
    "happiness": "positive",
    "joy": "positive",
    "positive": "positive",
    "neutral": "neutral",
    "calm": "neutral",
    "sad": "negative",
    "sadness": "negative",
    "angry": "negative",
    "anger": "negative",
    "fear": "negative",
    "disgust": "negative",
    "negative": "negative",
    "surprise": "surprise",
    "surprised": "surprise",
    "inconclusive": "inconclusive",
    "unknown": "inconclusive",
}


def normalize_expression_label(raw: str | None) -> str:
    if not raw:
        return "inconclusive"
    key = str(raw).strip().lower()
    return _MAP.get(key, "inconclusive")


def normalize_probabilities(raw_probs: Dict[str, float]) -> Dict[str, float]:
    out = {k: 0.0 for k in NORMALIZED if k != "inconclusive"}
    for raw, p in (raw_probs or {}).items():
        norm = normalize_expression_label(raw)
        if norm == "inconclusive":
            continue
        out[norm] = out.get(norm, 0.0) + float(p)
    total = sum(out.values())
    if total <= 0:
        return {"inconclusive": 1.0}
    return {k: v / total for k, v in out.items()}


def pick_label(
    probs: Dict[str, float],
    *,
    minimum_confidence: float = 0.60,
) -> Tuple[str, float, bool]:
    if not probs or "inconclusive" in probs and len(probs) == 1:
        return "inconclusive", 0.0, False
    best = max(probs.items(), key=lambda kv: kv[1])
    label, conf = best[0], float(best[1])
    if conf < minimum_confidence:
        return "inconclusive", conf, False
    return label, conf, True
