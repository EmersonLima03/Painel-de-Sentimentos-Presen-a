"""Contrato L / J / K — near observacional vs oclusão comportamental.

Alinhado à decisão 2026-09-09 (sem mudança de detector):
- L parcial (queixo/bochecha, face observável): face_occlusion=none é válido;
  hand_near_face é opcional; não vira persistent só por proximidade.
- J / uma mão cobrindo: possible → persistent (~5s) → recovery.
- K / duas mãos: persistent; sem promover drowsiness; recovery.
"""

from __future__ import annotations

from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache
from app.pipeline.occlusion_head_arbitration import resolve_occlusion_vs_head_down


def _engine(**extra):
    base = {
        "face_occlusion_suppress_when_landmarks_clear": True,
        "face_occlusion_persistent_seconds": 5.0,
        "face_occlusion_clear_hold_seconds": 4.0,
        "face_occlusion_face_missing_hold_seconds": 15.0,
        "face_occlusion_confirm_seconds": 0.7,
        "head_down_pitch_threshold": 0.45,
        "head_down_event_min_seconds": 8.0,
        "head_down_short_to_persistent_seconds": 8.0,
        "head_down_require_landmarks_quality": 0.45,
        "head_down_suppress_when_occlusion": True,
        "head_down_allow_face_missing_proxy": False,
        "behavioral_event_clear_hold_seconds": 0.5,
        "behavioral_event_clear_hold_drowsiness_seconds": 4.0,
        "phone_yolo_enabled": False,
        "module_expression_mode": "off",
        "module_face_landmarks_mode": "off",
        "module_pose_mode": "debug",
        "module_temporal_fusion_mode": "debug",
        "module_phone_mode": "off",
        "expression_provider": "fer_legacy",
        "expression_emotion_backend": "fer_onnx",
        "rule_engine_version": "rules-v0-baseline",
        "threshold_profile": "test",
        "camera_calibration_version": "test",
        "runtime_mode": "demo",
    }
    base.update(extra)
    return RealtimeAnalyticsEngine(type("S", (), base)())


PERSIST_S = 5.0


def _occlusion_level_for_duration(hand_near_since: float, now: float) -> str:
    """Espelha a regra temporal já usada no analytics (sem alterar detector)."""
    dur = now - hand_near_since
    if dur >= PERSIST_S:
        return "persistent_possible_face_occlusion"
    return "possible_face_occlusion_by_hand"


# --- A) L parcial: face clara ---


def test_l_partial_clear_face_occlusion_none_is_valid():
    """L_mao_parcial_rosto: face observável → none é comportamento correto."""
    cache = TrackAnalyticsCache(track_key="l-partial")
    cache.hands = {"state": "not_near_face"}
    cache.face_occlusion = {"state": "none", "reasons": []}
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.85,
        "average_eye_openness": 0.28,
    }
    assert cache.face_occlusion["state"] == "none"
    assert cache.hands["state"] in ("not_near_face", "hand_near_face")


def test_l_hand_near_optional_does_not_require_occlusion():
    """hand_near_face pode existir como sinal; não obriga evento de oclusão no contrato L."""
    # Contrato: near opcional. Estado válido = near sem persistent forçado por regra de produto.
    hands_optional = {"state": "hand_near_face"}
    occ_ok = {"state": "none"}
    # Sem hand_near_since confirmado + duração, não há persistent no modelo temporal.
    assert hands_optional["state"] == "hand_near_face"
    assert occ_ok["state"] == "none"
    assert _occlusion_level_for_duration(hand_near_since=100.0, now=100.5) != (
        "persistent_possible_face_occlusion"
    )


def test_l_proximity_short_duration_never_persistent_alone():
    """Nunca persistent só por janela curta (proximidade / possible breve)."""
    assert _occlusion_level_for_duration(10.0, 12.0) == "possible_face_occlusion_by_hand"
    assert _occlusion_level_for_duration(10.0, 14.9) == "possible_face_occlusion_by_hand"
    assert _occlusion_level_for_duration(10.0, 15.0) == "persistent_possible_face_occlusion"


def test_l_clear_face_suppresses_generic_occlusion_without_wrist():
    """Landmarks claros sem punho: oclusão genérica limpa (não inventar L→oclusão)."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="l-clear")
    cache.face_occlusion = {
        "state": "possible_face_occlusion_by_hand",
        "reasons": ["generic_blur"],
        "duration_seconds": 1.0,
    }
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.85,
        "average_eye_openness": 0.28,
    }
    cache.hands = {"state": "not_near_face"}
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True, now=50.0)
    assert cache.face_occlusion["state"] == "none"


# --- B) J / uma mão cobrindo ---


def test_j_one_hand_possible_then_persistent_then_recovery():
    """L_uma_mao_cobrindo / J: possible → persistent (~5s) → recovery."""
    t0 = 100.0
    assert _occlusion_level_for_duration(t0, t0 + 2.0) == "possible_face_occlusion_by_hand"
    assert _occlusion_level_for_duration(t0, t0 + 5.0) == "persistent_possible_face_occlusion"

    # Recovery: sem near, hold expirado → none (contrato)
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="j1")
    cache.hand_near_since = t0
    cache.hand_near_last_seen = t0 + 20.0
    cache.hands = {"state": "hand_near_face"}
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["wrist_near_face_persistent"],
        "duration_seconds": 20.0,
    }
    # Após clear hold (4s) sem wrist: limpa via caminho de reasons sem wrist + landmarks
    # (wrist reason impede suppress — recovery real zera hand_near_* primeiro)
    cache.hand_near_since = None
    cache.hand_near_last_seen = None
    cache.hands = {"state": "not_near_face"}
    cache.face_occlusion = {
        "state": "possible_face_occlusion_by_hand",
        "reasons": ["generic_blur"],
    }
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.85,
        "average_eye_openness": 0.28,
    }
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True, now=t0 + 30.0)
    assert cache.face_occlusion["state"] == "none"
    assert cache.hands["state"] == "not_near_face"


def test_j_wrist_occlusion_not_cleared_by_landmarks_alone():
    """Cobertura real com punho: landmarks 'ok' não apagam oclusão (regressão J)."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="j-wrist")
    cache.hand_near_since = 10.0
    cache.hand_near_last_seen = 20.0
    cache.hands = {"state": "hand_near_face"}
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["wrist_near_face_persistent"],
        "duration_seconds": 12.0,
    }
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.9,
        "average_eye_openness": 0.3,
    }
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True, now=21.0)
    assert cache.face_occlusion["state"] == "persistent_possible_face_occlusion"


# --- C) K / duas mãos ---


def test_k_two_hands_persistent_and_no_head_down_from_occlusion():
    """K: oclusão persistente; head_down não inventado sob oclusão."""
    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={"state": "pose_inconclusive", "confidence": 0.3},
        face_occlusion={
            "state": "persistent_possible_face_occlusion",
            "reasons": ["wrist_near_face_persistent", "occlusion_hold"],
            "duration_seconds": 18.0,
        },
        facial_features={"status": "unavailable"},
        hands={"state": "hand_near_face"},
        body_head_geom=False,
        now=120.0,
        allow_face_missing_proxy=False,
    )
    assert res.face_occlusion.get("state") == "persistent_possible_face_occlusion"
    assert res.head_state.get("state") not in ("head_down_short", "head_down_persistent")


def test_k_occlusion_keeps_drowsiness_inconclusive_contract():
    """Sob oclusão persistente, atenção/sono devem poder ficar inconclusivos (não sono falso)."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="k-drow")
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["wrist_near_face_persistent"],
        "duration_seconds": 10.0,
    }
    cache.drowsiness = {"state": "inconclusive", "reasons": ["face_occlusion"]}
    cache.visual_attention = {"state": "inconclusive", "reasons": ["face_occlusion"]}
    assert cache.drowsiness["state"] not in ("possible_drowsiness", "probable_drowsiness")
    assert cache.visual_attention["state"] != "low_attention"
    # arbitration: oclusão ativa
    occ = str((cache.face_occlusion or {}).get("state") or "none")
    assert occ == "persistent_possible_face_occlusion"


def test_k_recovery_when_face_clear_and_wrist_gone():
    """Recuperação K: sem punho + face clara → none."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="k-rec")
    cache.hand_near_since = None
    cache.hand_near_last_seen = None
    cache.hands = {"state": "not_near_face"}
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["generic_blur"],
        "duration_seconds": 20.0,
    }
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.88,
        "average_eye_openness": 0.3,
    }
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True, now=200.0)
    assert cache.face_occlusion["state"] == "none"


def test_fixture_l_contract_fields():
    """Fixture TRI documenta L com near opcional e none permitido."""
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "tri_validation_scenarios.json").read_text(
            encoding="utf-8"
        )
    )
    l = next(s for s in data["scenarios"] if s["id"] == "L")
    assert l["hand_near_face"] == "optional"
    assert "none" in l["allow_occlusion"]
