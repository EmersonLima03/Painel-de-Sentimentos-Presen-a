"""Frown geométrico — EX− quando FER+ marca pout como neutral."""

from app.vision.facial_signals import _frown_from_landmarks, _smile_from_landmarks


class _Lm:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _mesh(points: dict[int, tuple[float, float]], n: int = 478):
    out = [_Lm(0.5, 0.5) for _ in range(n)]
    for idx, (x, y) in points.items():
        out[idx] = _Lm(x, y)
    return out


def test_frown_high_when_mouth_corners_droop():
    # MediaPipe idxs: top=13, bottom=14, left=78, right=308, outer 61/291
    lm = _mesh(
        {
            13: (0.50, 0.40),
            14: (0.50, 0.44),
            78: (0.32, 0.50),
            308: (0.68, 0.50),
            61: (0.30, 0.52),
            291: (0.70, 0.52),
            107: (0.40, 0.28),
            336: (0.60, 0.28),
            159: (0.40, 0.32),
            386: (0.60, 0.32),
        }
    )
    frown = _frown_from_landmarks(lm, 100, 100, mouth_aspect=0.04)
    smile = _smile_from_landmarks(lm, 100, 100, mouth_aspect=0.04)
    assert frown >= 0.36
    assert frown > smile


def test_smile_high_when_corners_lift():
    lm = _mesh(
        {
            13: (0.50, 0.48),
            14: (0.50, 0.52),
            78: (0.28, 0.42),
            308: (0.72, 0.42),
            61: (0.26, 0.40),
            291: (0.74, 0.40),
            107: (0.40, 0.22),
            336: (0.60, 0.22),
            159: (0.40, 0.32),
            386: (0.60, 0.32),
        }
    )
    smile = _smile_from_landmarks(lm, 100, 100, mouth_aspect=0.20)
    frown = _frown_from_landmarks(lm, 100, 100, mouth_aspect=0.20)
    assert smile >= 0.45
    assert smile > frown


def test_resting_mouth_not_strong_frown():
    """Cara séria: MAR baixo mas sem droop/scrunch → frown abaixo do boost."""
    lm = _mesh(
        {
            13: (0.50, 0.45),
            14: (0.50, 0.48),
            78: (0.35, 0.465),
            308: (0.65, 0.465),
            61: (0.33, 0.47),
            291: (0.67, 0.47),
            107: (0.40, 0.22),
            336: (0.60, 0.22),
            159: (0.40, 0.32),
            386: (0.60, 0.32),
        }
    )
    frown = _frown_from_landmarks(lm, 100, 100, mouth_aspect=0.04)
    assert frown < 0.36
