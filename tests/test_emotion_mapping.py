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
    assert _smile_heuristic_score(face) >= 0.28


def test_smile_boost_overrides_neutral_probs():
    from app.vision.emotion_engagement import apply_smile_boost_to_fer_probs

    face = np.zeros((80, 80, 3), dtype=np.uint8)
    face[50:72, 15:65] = 200
    probs, label, source = apply_smile_boost_to_fer_probs(
        face, {"neutral": 0.7, "happy": 0.1}, raw_label="neutral"
    )
    assert source == "smile"
    assert label == "happy"
    assert probs["happy"] >= probs.get("neutral", 0.0)


def test_smile_from_landmarks_corners_up():
    from app.vision.facial_signals import _smile_from_landmarks, _MOUTH_TOP, _MOUTH_BOTTOM, _MOUTH_LEFT, _MOUTH_RIGHT

    class P:
        def __init__(self, x, y):
            self.x, self.y = x, y

    # face 100x100: cantos elevados (y menor), boca larga
    lm = [P(0.5, 0.5)] * 500
    lm[_MOUTH_TOP] = P(0.50, 0.62)
    lm[_MOUTH_BOTTOM] = P(0.50, 0.72)
    lm[_MOUTH_LEFT] = P(0.28, 0.64)   # corners above mid (0.67)
    lm[_MOUTH_RIGHT] = P(0.72, 0.64)
    score = _smile_from_landmarks(lm, 100, 100, mouth_aspect=0.25)
    assert score >= 0.32


def test_sad_low_conf_neutral():
    assert _map_emotion_to_state("sad", 0.45) == "neutral"


def test_sad_high_conf_distracted():
    assert _map_emotion_to_state("sad", 0.65) == "distracted"


def test_angry_distracted():
    assert _map_emotion_to_state("angry", 0.5) == "distracted"
