"""Normalização ética de expressões aparentes."""

from __future__ import annotations

from typing import Dict, Tuple

# Classes internas normalizadas (TRI: sem bucket surpresa na UI/relatório)
NORMALIZED = ("positive", "neutral", "negative", "inconclusive")

# Mapeamentos comuns FER / DeepFace / HSEmotion → normalizado
_MAP = {
    "happy": "positive",
    "happiness": "positive",
    "joy": "positive",
    "positive": "positive",
    "neutral": "neutral",
    "calm": "neutral",
    # Surpresa fora do produto TRI: massa descartada (não vira neutra nem “mista”)
    # — senão choro/boca aberta no FER+ infla neutra e bloqueia negativa.
    "surprise": "inconclusive",
    "surprised": "inconclusive",
    "sad": "negative",
    "sadness": "negative",
    "angry": "negative",
    "anger": "negative",
    "fear": "negative",
    "disgust": "negative",
    "contempt": "negative",
    "negative": "negative",
    "inconclusive": "inconclusive",
    "unknown": "inconclusive",
}


def normalize_expression_label(raw: str | None) -> str:
    if not raw:
        return "inconclusive"
    key = str(raw).strip().lower()
    return _MAP.get(key, "inconclusive")


def display_expression_pt(raw_or_normalized: str | None) -> str:
    """Texto seguro para UI — nunca diagnóstico emocional."""
    key = str(raw_or_normalized or "").strip().lower()
    direct = {
        "predominantly_positive": "expressão predominantemente positiva",
        "predominantly_neutral": "expressão predominantemente neutra",
        "predominantly_negative": "expressão predominantemente negativa",
        "surprise": "expressão predominantemente neutra",  # legado → neutra (TRI)
        "inconclusive": "inconclusivo",
    }
    if key in direct:
        return direct[key]
    n = normalize_expression_label(raw_or_normalized)
    return {
        "positive": "expressão predominantemente positiva",
        "neutral": "expressão predominantemente neutra",
        "negative": "expressão predominantemente negativa",
        "surprise": "expressão predominantemente neutra",
        "inconclusive": "inconclusivo",
    }.get(n, "inconclusivo")


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
    if not probs or ("inconclusive" in probs and len(probs) == 1):
        return "inconclusive", 0.0, False
    # Ignora residual surprise se ainda vier no dict
    usable = {k: float(v) for k, v in probs.items() if k not in ("inconclusive", "surprise")}
    if not usable:
        return "inconclusive", 0.0, False
    # Massa negativa agregada (sad+angry+fear+disgust já somados em "negative")
    neg_mass = float(usable.get("negative", 0.0))
    neu_mass = float(usable.get("neutral", 0.0))
    pos_mass = float(usable.get("positive", 0.0))
    best = max(usable.items(), key=lambda kv: kv[1])
    label, conf = best[0], float(best[1])
    # Se neutra ganha por pouco mas há massa negativa clara → negativa (raiva/choro no FER+)
    if label == "neutral" and neg_mass >= 0.28 and neg_mass >= neu_mass * 0.75 and neg_mass >= pos_mass:
        label, conf = "negative", neg_mass
    if conf < minimum_confidence:
        # Ainda aceita negativa com barra um pouco menor (massa agregada)
        if label == "negative" and neg_mass >= max(0.32, minimum_confidence * 0.75):
            return "negative", neg_mass, True
        return "inconclusive", conf, False
    return label, conf, True
