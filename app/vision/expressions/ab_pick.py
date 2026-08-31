"""A/B de providers de expressão — escolha conservadora e testável."""

from __future__ import annotations

from typing import Any, Optional, Tuple

from app.vision.expressions.normalization import normalize_expression_label


def pick_expression_ab(
    primary: Any,
    secondary: Optional[Any] = None,
) -> Tuple[Any, str]:
    """
    Escolhe entre duas predições.
    - Concordam → primary
    - Um diz positive com conf alta e outro neutral → preferir positive (sorriso real)
    - Caso contrário → maior confiança; empate → primary
    Retorna (pred, reason).
    """
    if secondary is None:
        return primary, "primary_only"

    p_lab = normalize_expression_label(getattr(primary, "label", None) or getattr(primary, "raw_label", None))
    s_lab = normalize_expression_label(getattr(secondary, "label", None) or getattr(secondary, "raw_label", None))
    p_conf = float(getattr(primary, "confidence", 0.0) or 0.0)
    s_conf = float(getattr(secondary, "confidence", 0.0) or 0.0)

    if p_lab == s_lab:
        return (primary if p_conf >= s_conf else secondary), "agreement"

    # Sorriso: só preferir positive com evidência mais forte (evita “sempre positiva” no A/B DeepFace).
    # Perfil TRI (fer_onnx sem secondary) não usa este caminho.
    if p_lab == "positive" and s_lab == "neutral" and p_conf >= 0.65:
        return primary, "prefer_positive_primary"
    if s_lab == "positive" and p_lab == "neutral" and s_conf >= 0.65:
        return secondary, "prefer_positive_secondary"

    if s_conf > p_conf + 0.08:
        return secondary, "higher_confidence_secondary"
    return primary, "primary_default"
