"""Traduções PT centralizadas — fonte única para dashboard e API."""

from __future__ import annotations

from typing import Optional

SIGNAL_LABELS: dict[str, str] = {
    "possible_drowsiness": "Olhos parcialmente fechados",
    "probable_drowsiness": "Olhos fechados por período prolongado",
    "face_occluded_persistent": "Rosto parcialmente coberto",
    "possible_phone_interaction": "Possível uso de celular",
    "probable_phone_interaction": "Uso provável de celular",
    "head_down_persistent": "Cabeça baixa prolongada",
    "low_visual_attention": "Baixa atenção visual observada",
}

# Agrupa tipos de evento em categorias pedagógicas (tempo total na sessão).
# Cobre TODOS os event_type emitidos por analytics_track._sync_temporal_events.
SIGNAL_CATEGORIES: dict[str, dict[str, object]] = {
    "phone": {
        "label_pt": "Celular (possível / provável uso)",
        "keys": ("possible_phone_interaction", "probable_phone_interaction"),
    },
    "eyes": {
        "label_pt": "Olhos fechados / parcialmente fechados",
        "keys": ("possible_drowsiness", "probable_drowsiness"),
    },
    "head_down": {
        "label_pt": "Cabeça baixa / apoiada",
        "keys": ("head_down_persistent",),
    },
    "face_covered": {
        "label_pt": "Rosto coberto / não observável",
        "keys": ("face_occluded_persistent",),
    },
    "low_attention": {
        "label_pt": "Baixa atenção visual persistente",
        "keys": ("low_visual_attention",),
    },
}

SIGNAL_DISCLAIMERS: dict[str, str] = {
    "possible_drowsiness": "Estimativa visual — não confirma sono real nem avalia o aluno.",
    "probable_drowsiness": "Estimativa visual — não confirma sono real nem avalia o aluno.",
    "face_occluded_persistent": "Estimativa visual — mão, objeto, microfone ou rosto fora do enquadramento; não confirma intenção.",
    "possible_phone_interaction": "Detecção visual — não confirma uso ativo do celular.",
    "probable_phone_interaction": "Detecção visual — não confirma uso ativo do celular.",
    "head_down_persistent": "Postura observada — não indica desatenção ou sonolência automaticamente.",
    "low_visual_attention": "Estimativa do olhar — não substitui observação pedagógica.",
}

ATTENTION_LABELS: dict[str, str] = {
    "high": "Atenção predominante: alta",
    "moderate": "Atenção predominante: moderada",
    "low": "Atenção predominante: baixa",
    "inconclusive": "Atenção inconclusiva",
}

EXPRESSION_LABELS: dict[str, str] = {
    "predominantly_positive": "Expressão predominantemente positiva",
    "positive": "Expressão predominantemente positiva",
    "predominantly_neutral": "Expressão predominantemente neutra",
    "neutral": "Expressão predominantemente neutra",
    "predominantly_negative": "Expressão predominantemente negativa",
    "negative": "Expressão predominantemente negativa",
    "mixed": "Expressão mista",
    "surprise": "Expressão de surpresa aparente",
    "inconclusive": "Inconclusivo",
}

CLIMATE_LABELS: dict[str, str] = {
    "predominantly_positive": "Expressão predominantemente positiva",
    "positive": "Expressão predominantemente positiva",
    "predominantly_neutral": "Expressão predominantemente neutra",
    "neutral": "Expressão predominantemente neutra",
    "predominantly_negative": "Expressão predominantemente negativa",
    "negative": "Expressão predominantemente negativa",
    "mixed": "Expressão mista",
    "surprise": "Expressão de surpresa aparente",
    "inconclusive": "Sem dado suficiente",
}

INSUFFICIENT_DATA_LABEL = "Sem dado suficiente para esse aluno"

LOW_OBSERVABILITY_NOTE = (
    "Baixa observabilidade durante toda a sessão — possível problema de câmera, ângulo ou iluminação."
)

CONCLUSIVE_ATTENTION = frozenset({"high", "moderate", "low"})
CONCLUSIVE_EXPRESSION = frozenset(
    {
        "predominantly_positive",
        "positive",
        "predominantly_neutral",
        "neutral",
        "predominantly_negative",
        "negative",
        "mixed",
        "surprise",
    }
)

INCONCLUSIVE_THRESHOLD = 0.70
MIN_PRESENCE_EXCLUDE_SECONDS = 30.0
EVENT_MERGE_GAP_SECONDS = 45.0  # episódios do mesmo sinal com gap ≤45s = 1 ocorrência pedagógica

# Famílias: possible+probable contam juntos no relatório
SIGNAL_FAMILIES: dict[str, str] = {
    "possible_drowsiness": "eyes",
    "probable_drowsiness": "eyes",
    "possible_phone_interaction": "phone",
    "probable_phone_interaction": "phone",
    "head_down_persistent": "head_down",
    "face_occluded_persistent": "face_covered",
    "low_visual_attention": "low_attention",
}


def signal_label_pt(key: str) -> str:
    return SIGNAL_LABELS.get(key, key.replace("_", " ").capitalize())


def signal_disclaimer_pt(key: str) -> str:
    return SIGNAL_DISCLAIMERS.get(
        key,
        "Indicador visual estimado — não constitui diagnóstico ou avaliação do aluno.",
    )


def attention_label_pt(level: str, *, insufficient: bool = False) -> str:
    if insufficient:
        return INSUFFICIENT_DATA_LABEL
    return ATTENTION_LABELS.get(level, ATTENTION_LABELS["inconclusive"])


def expression_label_pt(state: str, *, insufficient: bool = False) -> str:
    if insufficient:
        return INSUFFICIENT_DATA_LABEL
    return EXPRESSION_LABELS.get(state, state or "Sem dado")


def climate_label_pt(state: str | None) -> str:
    if not state:
        return "Sem dado"
    return CLIMATE_LABELS.get(state, state)


def attention_level_from_index(index: Optional[float]) -> str:
    if index is None:
        return "inconclusive"
    v = float(index)
    if v >= 0.65:
        return "high"
    if v >= 0.45:
        return "moderate"
    if v >= 0.25:
        return "low"
    return "inconclusive"


def labels_catalog() -> dict:
    return {
        "signals": {k: {"label_pt": signal_label_pt(k), "disclaimer_pt": signal_disclaimer_pt(k)} for k in SIGNAL_LABELS},
        "categories": {
            cid: {"label_pt": meta["label_pt"], "keys": list(meta["keys"])}
            for cid, meta in SIGNAL_CATEGORIES.items()
        },
        "attention": ATTENTION_LABELS,
        "expression": EXPRESSION_LABELS,
        "climate": CLIMATE_LABELS,
        "insufficient_data_label": INSUFFICIENT_DATA_LABEL,
        "low_observability_note": LOW_OBSERVABILITY_NOTE,
    }


def category_totals_from_signals(signals: list[dict] | dict, *, include_zero: bool = False) -> list[dict]:
    """Soma tempo por categoria pedagógica a partir de signals[] ou dict SignalRollup."""
    by_key: dict[str, float] = {}
    occ_by_key: dict[str, int] = {}

    def _add(key: str, seconds: float, occ: int) -> None:
        by_key[key] = by_key.get(key, 0.0) + float(seconds or 0)
        occ_by_key[key] = occ_by_key.get(key, 0) + int(occ or 0)

    if isinstance(signals, dict):
        for s in signals.values():
            if hasattr(s, "signal_key"):
                _add(s.signal_key, s.total_seconds, s.occurrence_count)
            elif isinstance(s, dict) and s.get("signal_key"):
                _add(s["signal_key"], s.get("total_seconds") or 0, s.get("occurrence_count") or 0)
    else:
        for s in signals:
            if s.get("signal_key"):
                _add(s["signal_key"], s.get("total_seconds") or 0, s.get("occurrence_count") or 0)

    out = []
    for cid, meta in SIGNAL_CATEGORIES.items():
        keys = list(meta["keys"])  # type: ignore[arg-type]
        total = sum(by_key.get(k, 0.0) for k in keys)
        occ = sum(occ_by_key.get(k, 0) for k in keys)
        if total <= 0 and not include_zero:
            continue
        top_key = max(keys, key=lambda k: by_key.get(k, 0.0)) if keys else cid
        out.append(
            {
                "category_id": cid,
                "label_pt": meta["label_pt"],
                "total_seconds": round(total, 1),
                "occurrence_count": occ,
                "disclaimer_pt": signal_disclaimer_pt(str(top_key)),
            }
        )
    out.sort(key=lambda x: x["total_seconds"], reverse=True)
    return out


def empty_category_totals() -> list[dict]:
    return category_totals_from_signals([], include_zero=True)

