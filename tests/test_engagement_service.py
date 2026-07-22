"""Testes do serviço de engajamento integrado."""

import numpy as np

from app.vision.engagement import calculate_engagement_state
from app.vision.engagement_service import get_engagement_calculator


def test_heuristic_engagement_on_face_roi():
    roi = np.random.randint(80, 200, (64, 64, 3), dtype=np.uint8)
    state = calculate_engagement_state(roi, (0, 0, 64, 64))
    assert state in ("attentive", "neutral", "distracted")


def test_get_engagement_calculator_returns_callable():
    fn, version = get_engagement_calculator()
    assert callable(fn)
    assert isinstance(version, str) and len(version) > 0
    roi = np.full((48, 48, 3), 128, dtype=np.uint8)
    state = fn(roi, (0, 0, 48, 48))
    assert state in ("attentive", "neutral", "distracted")
