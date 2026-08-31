"""Contrato EX− — expressão predominantemente negativa (TRI sem bucket surpresa)."""

from collections import deque

from app.pipeline.analytics_track import RealtimeAnalyticsEngine
from app.vision.expressions.normalization import (
    normalize_expression_label,
    normalize_probabilities,
    pick_label,
)


class _S:
    expression_minimum_samples = 3
    expression_minimum_negative_samples = 2
    expression_minimum_confidence_negative = 0.42


def test_sad_angry_map_to_negative():
    assert normalize_expression_label("sad") == "negative"
    assert normalize_expression_label("anger") == "negative"
    assert normalize_expression_label("fear") == "negative"
    assert normalize_expression_label("disgust") == "negative"
    assert normalize_expression_label("contempt") == "negative"


def test_surprise_dropped_not_mixed_bucket():
    """Surpresa fora do produto — massa descartada (não vira neutra nem mista)."""
    assert normalize_expression_label("surprise") == "inconclusive"
    probs = normalize_probabilities(
        {"surprise": 0.50, "sadness": 0.30, "neutral": 0.20}
    )
    assert "surprise" not in probs
    assert probs.get("negative", 0) >= probs.get("neutral", 0)
    label, conf, ok = pick_label(probs, minimum_confidence=0.42)
    assert label == "negative"
    assert ok


def test_weak_negative_does_not_beat_neutral_in_smooth():
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = _S()
    now = 100.0
    buf = deque(
        [
            (now - 3, "neutral", 0.70),
            (now - 2, "negative", 0.40),
            (now - 1, "neutral", 0.65),
            (now, "negative", 0.42),
        ]
    )
    smoothed, n = eng._smooth_expression(buf, now, provider_name="fer_onnx")
    assert smoothed in ("predominantly_neutral", "inconclusive")
    assert smoothed != "predominantly_negative"


def test_sustained_negative_becomes_predominantly_negative():
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = _S()
    now = 100.0
    buf = deque(
        [
            (now - 4, "negative", 0.70),
            (now - 3, "negative", 0.68),
            (now - 2, "negative", 0.72),
            (now - 1, "neutral", 0.40),
            (now, "negative", 0.75),
        ]
    )
    smoothed, n = eng._smooth_expression(buf, now, provider_name="fer_onnx")
    assert smoothed == "predominantly_negative"
    assert n >= 3


def test_two_strong_negatives_enough_with_tri_gates():
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = _S()
    now = 100.0
    buf = deque(
        [
            (now - 2, "negative", 0.55),
            (now - 1, "negative", 0.58),
            (now, "neutral", 0.35),
        ]
    )
    smoothed, n = eng._smooth_expression(buf, now, provider_name="fer_onnx")
    assert smoothed == "predominantly_negative"
