"""Factory de providers de expressão."""

from __future__ import annotations

from app.vision.expressions.deepface_provider import DeepFaceProvider
from app.vision.expressions.fer_legacy_provider import FerLegacyProvider
from app.vision.expressions.fer_onnx_provider import FerOnnxProvider
from app.vision.expressions.hsemotion_provider import HSEmotionProvider
from app.vision.expressions.hsemotion_vgaf_provider import HSEmotionVgafProvider
from app.vision.expressions.mock_provider import MockExpressionProvider


def create_expression_provider(name: str, **kwargs):
    key = (name or "mock").strip().lower()
    if key in ("mock", "none"):
        return MockExpressionProvider(**kwargs)
    if key in ("fer_onnx", "ferplus", "emotion_ferplus"):
        return FerOnnxProvider(**kwargs)
    if key in ("fer_legacy", "fer", "mini_xception"):
        return FerLegacyProvider(**kwargs)
    if key in ("hsemotion_vgaf", "hsemotion_enet_b0_8_best_vgaf", "hs_vgaf"):
        return HSEmotionVgafProvider(**kwargs)
    if key in ("hsemotion", "hs"):
        return HSEmotionProvider(**kwargs)
    if key in ("deepface", "df"):
        return DeepFaceProvider(**kwargs)
    raise ValueError(f"Unknown expression provider: {name}")
