"""Mapeamento emoção → engajamento (calibragem sala)."""

import numpy as np

from app.vision.emotion_engagement import _map_emotion_to_state, _smile_heuristic_score


def test_neutral_is_neutral():
    assert _map_emotion_to_state("neutral", 0.7) == "neutral"


def test_happy_is_attentive():
    assert _map_emotion_to_state("happy", 0.6) == "attentive"


def test_smile_boost_attentive():
    assert _map_emotion_to_state("neutral", 0.5, smile_boost=True) == "attentive"


def test_smile_heuristic_bright_mouth_region():
    face = np.zeros((80, 80, 3), dtype=np.uint8)
    face[50:72, 15:65] = 200  # boca clara e larga
    assert _smile_heuristic_score(face) >= 0.45


def test_sad_low_conf_neutral():
    assert _map_emotion_to_state("sad", 0.45) == "neutral"


def test_sad_high_conf_distracted():
    assert _map_emotion_to_state("sad", 0.65) == "distracted"


def test_angry_distracted():
    assert _map_emotion_to_state("angry", 0.5) == "distracted"
