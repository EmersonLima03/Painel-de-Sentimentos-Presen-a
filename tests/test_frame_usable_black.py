"""Contrato: frame quase preto não deve ser tratado como sinal válido."""

import numpy as np

from app.rtsp.video_capture import _frame_usable


def test_solid_black_frame_not_usable():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    assert _frame_usable(frame) is False


def test_near_black_noise_not_usable():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 12, size=(480, 640, 3), dtype=np.uint8)
    assert _frame_usable(frame) is False


def test_normal_indoor_frame_usable():
    rng = np.random.default_rng(1)
    frame = rng.integers(40, 180, size=(480, 640, 3), dtype=np.uint8)
    assert _frame_usable(frame) is True


def test_sudden_brightness_drop_rejected():
    rng = np.random.default_rng(2)
    dim = rng.integers(8, 25, size=(480, 640, 3), dtype=np.uint8)
    # Sozinho poderia passar limiar absoluto em alguns casos; com prev_mean alto, rejeita.
    assert _frame_usable(dim, prev_mean=90.0) is False
