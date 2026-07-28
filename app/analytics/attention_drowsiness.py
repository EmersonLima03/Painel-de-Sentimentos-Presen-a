"""Regras explicáveis: sonolência aparente e atenção visual estimada."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class DrowsinessState:
    state: str  # none | possible | probable | inconclusive
    confidence: float
    reasons: List[str] = field(default_factory=list)
    contributing_signals: Dict[str, float] = field(default_factory=dict)


@dataclass
class AttentionState:
    state: str  # high | moderate | low | inconclusive
    score: Optional[float]
    reasons: List[str] = field(default_factory=list)


def evaluate_apparent_drowsiness(
    *,
    eyes_closed_seconds: float,
    head_pitch: float,
    head_supported: bool = False,
    low_motion: bool = False,
    sample_count: int = 0,
    observation_quality: float = 1.0,
    min_duration_seconds: float = 30.0,
    possible_after_seconds: float = 6.0,
    min_samples: int = 5,
    min_quality: float = 0.55,
    cooldown_active: bool = False,
) -> DrowsinessState:
    """
    Dois segundos de olhos fechados NÃO geram evento persistente.
    Baixa qualidade → inconclusivo. Nunca diagnóstico clínico.
    Thresholds alinhados ao runtime: possible ≥ possible_after (6s), probable ≥ min_duration (30s).
    """
    reasons: List[str] = []
    signals = {
        "eyes_closed_seconds": eyes_closed_seconds,
        "head_pitch": head_pitch,
        "observation_quality": observation_quality,
        "sample_count": float(sample_count),
    }
    if cooldown_active:
        return DrowsinessState("none", 0.0, ["cooldown"], signals)
    if observation_quality < min_quality:
        return DrowsinessState("inconclusive", 0.2, ["insufficient_observation_quality"], signals)
    if sample_count < min_samples:
        return DrowsinessState("inconclusive", 0.25, ["insufficient_samples"], signals)
    if eyes_closed_seconds < 2.5:
        return DrowsinessState("none", 0.1, ["brief_blink_or_closed"], signals)

    score = 0.0
    # Olhos fechados sustentados sozinhos bastam para probable
    if eyes_closed_seconds >= min_duration_seconds:
        score += 0.75
        reasons.append("eyes_closed_duration")
    elif eyes_closed_seconds >= possible_after_seconds:
        score += 0.35
        reasons.append("eyes_partially_prolonged")
    if head_pitch > 0.25:
        score += 0.15
        reasons.append("head_down")
    if head_supported:
        score += 0.1
        reasons.append("head_supported")
    if low_motion:
        score += 0.05
        reasons.append("low_motion")

    if score >= 0.7 and eyes_closed_seconds >= min_duration_seconds:
        return DrowsinessState("probable", min(0.95, score), reasons, signals)
    if score >= 0.35 and eyes_closed_seconds >= possible_after_seconds:
        return DrowsinessState("possible", min(0.95, score), reasons, signals)
    return DrowsinessState("none", score, reasons or ["below_threshold"], signals)


def evaluate_visual_attention(
    *,
    head_yaw: float = 0.0,
    head_pitch: float = 0.0,
    gaze_reliable: bool = False,
    gaze_toward_front: Optional[float] = None,
    coverage: float = 1.0,
    probable_phone: bool = False,
    drowsiness_state: str = "none",
    observation_quality: float = 1.0,
    duration_factor: float = 1.0,
    recurrence_low: bool = False,
    min_quality: float = 0.55,
) -> AttentionState:
    """
    Índice explicável. Expressão negativa NÃO reduz atenção.
    """
    if observation_quality < min_quality:
        return AttentionState("inconclusive", None, ["insufficient_observation_quality"])

    score = 0.85
    reasons: List[str] = []
    if abs(head_yaw) > 0.45 or head_pitch > 0.35:
        score -= 0.25
        reasons.append("head_away")
    if gaze_reliable and gaze_toward_front is not None:
        score = 0.6 * score + 0.4 * float(gaze_toward_front)
        reasons.append("gaze_used")
    if coverage < 0.5:
        score -= 0.15
        reasons.append("low_coverage")
    if probable_phone:
        score -= 0.2
        reasons.append("probable_phone")
    if drowsiness_state in ("possible", "probable"):
        score -= 0.25
        reasons.append("apparent_drowsiness")
    if recurrence_low:
        score -= 0.1
        reasons.append("recurrent_low")
    score *= max(0.5, min(1.0, duration_factor))
    score = max(0.0, min(1.0, score))

    if score >= 0.7:
        return AttentionState("high", round(score, 3), reasons or ["oriented"])
    if score >= 0.45:
        return AttentionState("moderate", round(score, 3), reasons or ["partial"])
    return AttentionState("low", round(score, 3), reasons or ["low_score"])
