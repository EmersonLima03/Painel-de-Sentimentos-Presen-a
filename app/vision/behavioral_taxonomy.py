"""
Taxonomia observável — nomenclatura ética (sem rótulos punitivos).

Todos os resultados são estimativas / sinais observados / não conclusivos.
"""

from __future__ import annotations

from enum import Enum


DISCLAIMER_PT = (
    "Estimativa visual observável. Não constitui diagnóstico emocional, "
    "psicológico, médico ou comportamental definitivo."
)


class ObservableSignal(str, Enum):
    """Sinais observados (não diagnósticos)."""

    ORIENTATION_FORWARD = "orientation_forward"
    ORIENTATION_DOWN_SHORT = "orientation_down_short"
    ORIENTATION_AWAY = "orientation_away"
    EYES_CLOSED_PERSISTENT = "eyes_closed_persistent"
    POSSIBLE_YAWN = "possible_yawn"
    POSSIBLE_DROWSINESS = "possible_drowsiness"
    OUT_OF_FIELD = "out_of_field"
    FACE_NOT_VISIBLE = "face_not_visible"
    LOW_OBSERVATION_QUALITY = "low_observation_quality"
    ATTENTION_INCONCLUSIVE = "attention_inconclusive"
    PHONE_VISIBLE = "phone_visible"
    POSSIBLE_PHONE_INTERACTION = "possible_phone_interaction"


class ClimateBucket(str, Enum):
    """Clima/humor aparente agregado (turma)."""

    POSITIVE_APPARENT = "positive_apparent"
    NEUTRAL_APPARENT = "neutral_apparent"
    NEGATIVE_APPARENT = "negative_apparent"
    INCONCLUSIVE = "inconclusive"


# Mapeamento legado → taxonomia observável (UI / eventos)
LEGACY_STATE_TO_OBSERVABLE = {
    "attentive": ObservableSignal.ORIENTATION_FORWARD.value,
    "neutral": ObservableSignal.ATTENTION_INCONCLUSIVE.value,
    "distracted": ObservableSignal.ORIENTATION_AWAY.value,
}

LABEL_PT = {
    ObservableSignal.ORIENTATION_FORWARD.value: "Orientação para frente (aparente)",
    ObservableSignal.ORIENTATION_DOWN_SHORT.value: "Cabeça baixa (curto — possível leitura)",
    ObservableSignal.ORIENTATION_AWAY.value: "Orientação afastada da área da aula",
    ObservableSignal.EYES_CLOSED_PERSISTENT.value: "Olhos fechados de forma persistente",
    ObservableSignal.POSSIBLE_YAWN.value: "Possível bocejo",
    ObservableSignal.POSSIBLE_DROWSINESS.value: "Possível sonolência (requer revisão)",
    ObservableSignal.OUT_OF_FIELD.value: "Aluno temporariamente fora do campo",
    ObservableSignal.FACE_NOT_VISIBLE.value: "Rosto não visível",
    ObservableSignal.LOW_OBSERVATION_QUALITY.value: "Baixa qualidade de observação",
    ObservableSignal.ATTENTION_INCONCLUSIVE.value: "Atenção não conclusiva",
    ObservableSignal.PHONE_VISIBLE.value: "Dispositivo móvel detectado (visível)",
    ObservableSignal.POSSIBLE_PHONE_INTERACTION.value: "Possível interação com dispositivo",
    ClimateBucket.POSITIVE_APPARENT.value: "Clima aparente positivo",
    ClimateBucket.NEUTRAL_APPARENT.value: "Clima aparente neutro",
    ClimateBucket.NEGATIVE_APPARENT.value: "Clima aparente negativo",
    ClimateBucket.INCONCLUSIVE.value: "Clima não conclusivo",
}


def label_pt(code: str) -> str:
    return LABEL_PT.get(code, code)
