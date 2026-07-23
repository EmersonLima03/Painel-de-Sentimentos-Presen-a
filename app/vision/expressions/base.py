"""Interface FacialExpressionProvider."""

from __future__ import annotations

from typing import List, Protocol

import numpy as np

from app.vision.domain import FacialExpressionPrediction


class FacialExpressionProvider(Protocol):
    @property
    def provider_name(self) -> str:
        ...

    @property
    def model_name(self) -> str:
        ...

    @property
    def model_version(self) -> str:
        ...

    def predict_batch(self, face_crops: List[np.ndarray]) -> List[FacialExpressionPrediction]:
        ...
