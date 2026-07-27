"""Catálogo de cenários de validação controlada (somente leitura / UI)."""

from __future__ import annotations

from typing import Any, Dict, List

# Duração esperada em segundos (None = livre / observação)
SCENARIOS: List[Dict[str, Any]] = [
    {
        "key": "neutral_15s",
        "name": "Estado neutro — 15s",
        "instruction": "Olhe para a câmera de frente, expressão neutra, sem celular.",
        "duration_seconds": 15,
        "expected": {
            "quality_status": ["observable"],
            "facial_features_status": ["available"],
            "attention_state": ["high", "moderate"],
            "drowsiness_state": ["none"],
            "phone_state": ["not_detected"],
            "presence_intact": True,
        },
    },
    {
        "key": "head_left_5s",
        "name": "Cabeça para esquerda — 5s",
        "instruction": "Vire a cabeça claramente para a esquerda e mantenha.",
        "duration_seconds": 5,
        "expected": {
            "yaw_direction": "left",
            "attention_not_persistently_low": True,
            "presence_intact": True,
        },
    },
    {
        "key": "head_right_5s",
        "name": "Cabeça para direita — 5s",
        "instruction": "Vire a cabeça claramente para a direita e mantenha.",
        "duration_seconds": 5,
        "expected": {
            "yaw_direction": "right",
            "attention_not_persistently_low": True,
            "presence_intact": True,
        },
    },
    {
        "key": "look_down_2s",
        "name": "Olhar para baixo — 2s",
        "instruction": "Olhe para baixo por cerca de 2 segundos e volte.",
        "duration_seconds": 2,
        "expected": {
            "pitch_up": True,
            "attention_not_persistently_low": True,
            "presence_intact": True,
        },
    },
    {
        "key": "look_down_10s",
        "name": "Olhar para baixo — 10s",
        "instruction": "Mantenha o olhar para baixo por ~10 segundos.",
        "duration_seconds": 10,
        "expected": {
            "pitch_up": True,
            "attention_may_change": True,
            "presence_intact": True,
        },
    },
    {
        "key": "normal_blinks",
        "name": "Piscadas normais",
        "instruction": "Pisque normalmente várias vezes (sem fechar os olhos por muito tempo).",
        "duration_seconds": 8,
        "expected": {
            "drowsiness_state": ["none", "inconclusive"],
            "no_drowsiness_event": True,
            "presence_intact": True,
        },
    },
    {
        "key": "eyes_closed_2s",
        "name": "Olhos fechados — 2s",
        "instruction": "Feche os olhos por ~2 segundos e abra.",
        "duration_seconds": 2,
        "expected": {
            "drowsiness_not_persistent": True,
            "presence_intact": True,
        },
    },
    {
        "key": "eyes_closed_8s",
        "name": "Olhos fechados — 8s",
        "instruction": "Mantenha os olhos fechados por ~8 segundos.",
        "duration_seconds": 8,
        "expected": {
            "drowsiness_may_be": ["possible", "probable", "none", "inconclusive"],
            "presence_intact": True,
        },
    },
    {
        "key": "eyes_closed_tilt_12s",
        "name": "Olhos fechados + cabeça inclinada — 12s",
        "instruction": "Feche os olhos e incline a cabeça para baixo ~12 segundos.",
        "duration_seconds": 12,
        "expected": {
            "drowsiness_may_be": ["possible", "probable", "inconclusive"],
            "presence_intact": True,
        },
    },
    {
        "key": "expr_neutral_10s",
        "name": "Expressão neutra — 10s",
        "instruction": "Mantenha expressão neutra olhando para a câmera.",
        "duration_seconds": 10,
        "expected": {
            "expression_sample_count_increases": True,
            "attention_not_only_from_expression": True,
            "presence_intact": True,
        },
    },
    {
        "key": "expr_smile_10s",
        "name": "Sorriso — 10s",
        "instruction": "Sorria de forma natural por ~10 segundos.",
        "duration_seconds": 10,
        "expected": {
            "expression_sample_count_increases": True,
            "smoothed_may_change": True,
            "presence_intact": True,
        },
    },
    {
        "key": "expr_back_neutral_10s",
        "name": "Retorno ao neutro — 10s",
        "instruction": "Volte à expressão neutra e mantenha.",
        "duration_seconds": 10,
        "expected": {
            "expression_sample_count_increases": True,
            "presence_intact": True,
        },
    },
    {
        "key": "phone_none",
        "name": "Sem celular",
        "instruction": "Não mostre celular; mãos livres.",
        "duration_seconds": 8,
        "expected": {
            "phone_state": ["not_detected"],
            "phone_never_confirmed": True,
            "presence_intact": True,
        },
    },
    {
        "key": "phone_on_table",
        "name": "Celular sobre a mesa",
        "instruction": "Coloque o celular visível sobre a mesa (sem uso contínuo).",
        "duration_seconds": 10,
        "expected": {
            "phone_allowed": ["not_detected", "phone_visible", "phone_near_person"],
            "phone_never_confirmed": True,
            "presence_intact": True,
        },
    },
    {
        "key": "phone_hand_no_look",
        "name": "Celular na mão sem olhar",
        "instruction": "Segure o celular na mão sem olhar para a tela.",
        "duration_seconds": 10,
        "expected": {
            "phone_allowed": [
                "not_detected",
                "phone_visible",
                "phone_near_person",
                "possible_phone_interaction",
            ],
            "phone_never_confirmed": True,
            "presence_intact": True,
        },
    },
    {
        "key": "phone_hand_brief_look",
        "name": "Celular na mão olhando brevemente",
        "instruction": "Olhe brevemente para o celular na mão e desvie.",
        "duration_seconds": 8,
        "expected": {
            "phone_allowed": [
                "not_detected",
                "phone_visible",
                "phone_near_person",
                "possible_phone_interaction",
                "probable_phone_interaction",
            ],
            "phone_never_confirmed": True,
            "presence_intact": True,
        },
    },
    {
        "key": "phone_hand_prolonged",
        "name": "Celular na mão por tempo prolongado",
        "instruction": "Mantenha o celular na mão/perto do rosto por ~15 segundos.",
        "duration_seconds": 15,
        "expected": {
            "phone_allowed": [
                "phone_near_person",
                "possible_phone_interaction",
                "probable_phone_interaction",
                "phone_visible",
                "not_detected",
            ],
            "phone_never_confirmed": True,
            "presence_intact": True,
        },
    },
    {
        "key": "face_distant",
        "name": "Rosto distante",
        "instruction": "Afaste-se da câmera até o rosto ficar pequeno no frame.",
        "duration_seconds": 8,
        "expected": {
            "quality_may_be": ["observable", "low_quality", "inconclusive"],
            "presence_intact": True,
        },
    },
    {
        "key": "low_light",
        "name": "Pouca iluminação",
        "instruction": "Reduza a luz do ambiente (sem desligar a câmera).",
        "duration_seconds": 8,
        "expected": {
            "quality_may_be": ["observable", "low_quality", "inconclusive"],
            "attention_inconclusive_if_bad_quality": True,
            "presence_intact": True,
        },
    },
    {
        "key": "partial_occlusion",
        "name": "Rosto parcialmente coberto",
        "instruction": "Cubra parcialmente o rosto com a mão (sem sair do frame).",
        "duration_seconds": 8,
        "expected": {
            "quality_may_be": ["observable", "low_quality", "inconclusive"],
            "presence_intact": True,
        },
    },
    {
        "key": "leave_frame",
        "name": "Sair do campo",
        "instruction": "Saia completamente do campo de visão da câmera.",
        "duration_seconds": 5,
        "expected": {
            "may_lose_track": True,
            "presence_intact": True,
        },
    },
    {
        "key": "return_frame",
        "name": "Retornar ao campo",
        "instruction": "Volte ao enquadramento e olhe para a câmera.",
        "duration_seconds": 8,
        "expected": {
            "track_may_return": True,
            "presence_intact": True,
        },
    },
    {
        "key": "occlusion_identity_ttl",
        "name": "Oclusão com identidade no TTL",
        "instruction": "Cubra o rosto ~5s sem sair do enquadramento (corpo visível).",
        "duration_seconds": 8,
        "expected": {
            "identity_may_be_cached": True,
            "attention_state": ["inconclusive"],
            "drowsiness_state": ["inconclusive", "none"],
            "presence_intact": True,
        },
    },
    {
        "key": "identity_swap_should_block",
        "name": "Troca de identidade fraca (bloquear)",
        "instruction": "Outra pessoa passa brevemente na frente; identidade não deve trocar por 1 amostra.",
        "duration_seconds": 10,
        "expected": {
            "no_weak_identity_swap": True,
            "presence_intact": True,
        },
    },
    {
        "key": "head_down_not_drowsy",
        "name": "Cabeça baixa ≠ sonolência",
        "instruction": "Olhe para baixo (ler/escrever) com olhos abertos ~8s.",
        "duration_seconds": 8,
        "expected": {
            "drowsiness_state": ["none", "inconclusive"],
            "no_auto_drowsiness_from_head_down": True,
            "presence_intact": True,
        },
    },
    {
        "key": "phone_on_desk",
        "name": "Celular na mesa (visível ≠ uso)",
        "instruction": "Deixe o celular visível na mesa, longe das mãos, sem olhar para ele.",
        "duration_seconds": 8,
        "expected": {
            "phone_allowed": ["not_detected", "phone_visible", "phone_near_person"],
            "phone_never_confirmed": True,
            "presence_intact": True,
        },
    },
    {
        "key": "two_people_cross",
        "name": "Duas pessoas cruzando",
        "instruction": "Duas pessoas trocam de lado no frame sem cobrir totalmente o outro.",
        "duration_seconds": 12,
        "expected": {
            "no_weak_identity_swap": True,
            "presence_intact": True,
        },
    },
]


def list_scenarios() -> List[Dict[str, Any]]:
    return [dict(s) for s in SCENARIOS]


def get_scenario(key: str) -> Dict[str, Any] | None:
    for s in SCENARIOS:
        if s["key"] == key:
            return dict(s)
    return None
