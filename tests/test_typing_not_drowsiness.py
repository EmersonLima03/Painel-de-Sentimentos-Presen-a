"""Digitação / cabeça baixa não deve alimentar sonolência via EAR falso (cenário F)."""

from types import SimpleNamespace

from app.analytics.attention_drowsiness import evaluate_apparent_drowsiness
from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache


def test_brief_closed_not_event():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=2.0,
        head_pitch=0.1,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state == "none"


def test_possible_at_6s_frontal():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=6.0,
        head_pitch=0.05,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state == "possible"


def test_probable_at_30s_frontal():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=30.0,
        head_pitch=0.05,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state == "probable"


def test_boundary_just_below_possible():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=5.99,
        head_pitch=0.0,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state in ("none", "inconclusive")


def test_head_down_pitch_alone_does_not_make_probable_without_eyes_duration():
    """Cabeça baixa sem duração de olhos fechados válidos ≠ sono."""
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=1.0,
        head_pitch=0.6,
        head_supported=True,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state == "none"


def _eng(**kw):
    base = dict(
        drowsiness_possible_after_seconds=6.0,
        drowsiness_probable_after_seconds=30.0,
        drowsiness_eye_closed_ear_threshold=0.18,
        drowsiness_minimum_observation_quality=0.60,
        visual_attention_minimum_observation_quality=0.55,
        head_down_pitch_threshold=0.45,
        head_down_require_landmarks_quality=0.45,
        face_occlusion_clear_hold_seconds=0.0,
        drowsiness_observation_gap_inconclusive_seconds=8.0,
        drowsiness_cooldown_seconds=20.0,
        experimental_perclos_enabled=False,
        phone_yolo_enabled=False,
        module_expression_mode="disabled",
        expression_emotion_backend="fer_onnx",
    )
    base.update(kw)
    return RealtimeAnalyticsEngine(SimpleNamespace(**base))


def test_typing_low_landmarks_pauses_accumulator_without_reset():
    """Digitação: landmarks ruins → pausa acumulador (não incrementa, não zera)."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.8,
        "overall_observability": 0.8,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.08,
        "yaw": 0.0,
        "pitch": 0.55,
        "landmarks_quality": 0.25,
    }
    cache.head_state = {"state": "head_down_short", "confidence": 0.7}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 4.0
    cache.eyes_last_tick = 100.0
    _, drow = eng._compute_attention_drowsiness(cache, now=105.0, face_visible=True)
    assert drow["state"] == "inconclusive"
    assert drow.get("observation_paused") is True
    assert cache.eyes_closed_accum_seconds == 4.0  # não resetou
    assert cache.eyes_last_tick is None  # não incrementou


def test_head_down_typing_angle_pauses_drowsiness_without_deep_ear():
    """Cenário F: cabeça baixa + palpebra semi-fechada por ângulo ≠ sono."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.85,
        "overall_observability": 0.85,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.12,
        "yaw": 0.0,
        "pitch": 0.52,
        "landmarks_quality": 0.80,
    }
    cache.head_state = {"state": "head_down_short", "confidence": 0.7, "pose_score": 0.7}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 10.0
    cache.eyes_last_tick = 200.0
    _, drow = eng._compute_attention_drowsiness(cache, now=205.0, face_visible=True)
    assert drow["state"] == "inconclusive"
    assert drow.get("observation_paused") is True


def test_pitch_alone_with_good_landmarks_does_not_hard_block():
    """Pitch alto com landmarks bons NÃO é bloqueio absoluto de sonolência."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.85,
        "overall_observability": 0.85,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.05,
        "yaw": 0.0,
        "pitch": 0.55,
        "landmarks_quality": 0.85,
    }
    cache.head_state = {"state": "facing_forward", "confidence": 0.8, "pose_score": 0.8}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 10.0
    cache.eyes_last_tick = 200.0
    cache.eyes_closed_since = 190.0
    _, drow = eng._compute_attention_drowsiness(cache, now=205.0, face_visible=True)
    assert drow["state"] == "possible"
    assert cache.eyes_closed_accum_seconds >= 10.0


def test_partial_ear_head_forward_pauses_like_typing_look_down():
    """Cenário F real: head_forward + EAR parcial (~0.12) por gaze ≠ sono."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.85,
        "overall_observability": 0.85,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.12,
        "yaw": 0.01,
        "pitch": 0.14,
        "landmarks_quality": 0.85,
    }
    cache.head_state = {"state": "head_forward", "confidence": 0.7, "pose_score": 0.7}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 10.0
    cache.eyes_last_tick = 200.0
    _, drow = eng._compute_attention_drowsiness(cache, now=205.0, face_visible=True)
    assert drow["state"] == "inconclusive"
    assert drow.get("observation_paused") is True
    assert cache.eyes_closed_accum_seconds == 10.0
    assert cache.eyes_last_tick is None


def test_deep_ear_still_allows_drowsiness_when_partial_band_skipped():
    """Olhos realmente fechados de frente (EAR profundo, pitch baixo) → possible (G)."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.85,
        "overall_observability": 0.85,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.05,
        "yaw": 0.0,
        "pitch": 0.05,
        "gaze_vertical": 0.05,
        "landmarks_quality": 0.85,
    }
    cache.head_state = {"state": "head_forward", "confidence": 0.8, "pose_score": 0.8}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 10.0
    cache.eyes_last_tick = 200.0
    cache.eyes_closed_since = 190.0
    _, drow = eng._compute_attention_drowsiness(cache, now=205.0, face_visible=True)
    assert drow["state"] == "possible"
    assert cache.eyes_closed_accum_seconds >= 10.0


def test_live_g_frontal_eyes_closed_pitch_near_012_still_accumulates():
    """G LIVE: olhos fechados de frente com pitch~0.12 NÃO deve pausar (≠ teclado)."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.85,
        "overall_observability": 0.85,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.055,
        "yaw": 0.0,
        "pitch": 0.122,
        "gaze_vertical": 0.122,
        "landmarks_quality": 0.85,
    }
    cache.head_state = {"state": "head_forward", "confidence": 0.8, "pose_score": 0.8}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 8.0
    cache.eyes_last_tick = 200.0
    cache.eyes_closed_since = 192.0
    _, drow = eng._compute_attention_drowsiness(cache, now=205.0, face_visible=True)
    assert drow["state"] == "possible"
    assert cache.eyes_closed_accum_seconds >= 8.0
    assert drow.get("observation_paused") is not True


def test_live_f_look_down_deep_ear_false_positive_pauses():
    """LIVE F 2026-09-14: head_forward + pitch~0.17 + EAR profundo falso ≠ sono."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.74,
        "overall_observability": 0.74,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.067,
        "yaw": -0.04,
        "pitch": 0.174,
        "gaze_vertical": 0.174,
        "landmarks_quality": 0.85,
    }
    cache.head_state = {"state": "head_forward", "confidence": 0.7, "pose_score": 0.7}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 120.0
    cache.eyes_last_tick = 200.0
    cache.eyes_closed_since = 80.0
    _, drow = eng._compute_attention_drowsiness(cache, now=205.0, face_visible=True)
    assert drow["state"] == "inconclusive"
    assert drow.get("observation_paused") is True
    assert cache.eyes_closed_accum_seconds == 120.0  # não incrementa
    assert cache.eyes_last_tick is None


def test_look_down_invalid_gap_clears_sticky_accum():
    """Pausa look-down sustentada zera debt sticky após gap (não vira probable na hora)."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.74,
        "overall_observability": 0.74,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.07,
        "yaw": 0.0,
        "pitch": 0.17,
        "gaze_vertical": 0.17,
        "landmarks_quality": 0.85,
    }
    cache.head_state = {"state": "head_forward", "confidence": 0.7, "pose_score": 0.7}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 120.0
    cache.eyes_invalid_since = 100.0
    _, drow = eng._compute_attention_drowsiness(cache, now=109.0, face_visible=True)
    assert drow["state"] == "inconclusive"
    assert cache.eyes_closed_accum_seconds == 0.0


def test_open_ear_resets_sticky_accum_even_when_observation_invalid():
    """Olhos abertos (EAR alto) zera debt mesmo com eyes_observable=False (anti-sticky G→UI)."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.50,  # abaixo do min_q_dr 0.60 → observable gate falha
        "overall_observability": 0.50,
        "status": "partially_observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.28,
        "yaw": 0.0,
        "pitch": 0.10,
        "gaze_vertical": 0.10,
        "landmarks_quality": 0.85,
    }
    cache.head_state = {"state": "head_forward", "confidence": 0.7, "pose_score": 0.7}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 90.0
    cache.eyes_closed_since = 100.0
    cache.eyes_last_tick = 200.0
    _, drow = eng._compute_attention_drowsiness(cache, now=205.0, face_visible=True)
    assert drow["state"] in ("none", "inconclusive")
    assert cache.eyes_closed_accum_seconds == 0.0


def test_frontal_deep_ear_still_probable_at_30s():
    """G: frente + EAR profundo 30s+ → probable (não afetado pelo gate F)."""
    eng = _eng()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {
        "overall_score": 0.9,
        "overall_observability": 0.9,
        "status": "observable",
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.04,
        "yaw": 0.0,
        "pitch": 0.03,
        "gaze_vertical": 0.03,
        "landmarks_quality": 0.9,
    }
    cache.head_state = {"state": "head_forward", "confidence": 0.9, "pose_score": 0.9}
    cache.face_occlusion = {"state": "none"}
    cache.eyes_closed_accum_seconds = 30.0
    cache.eyes_last_tick = 200.0
    cache.eyes_closed_since = 170.0
    _, drow = eng._compute_attention_drowsiness(cache, now=205.0, face_visible=True)
    assert drow["state"] == "probable"
    assert cache.eyes_closed_accum_seconds >= 30.0


def test_drowsiness_event_clears_fast_when_eyes_open():
    """Evento probable some em ~2s com EAR aberto + state none (não fica 1min+)."""
    eng = _eng(
        behavioral_event_clear_hold_seconds=0.5,
        behavioral_event_clear_hold_drowsiness_seconds=4.0,
        face_occlusion_clear_hold_seconds=0.5,
    )
    tid = "cam-web-person-001"
    eng._open_events[f"{tid}:probable_drowsiness"] = {
        "event_id": "e1",
        "event_type": "probable_drowsiness",
        "started_at": 100.0,
        "opened_at": 100.0,
        "duration_seconds": 60.0,
        "reasons": ["eyes_closed_duration"],
        "provenance": {},
    }
    cache = eng._get_cache(tid)
    track = {
        "track_id": tid,
        "person_track_id": tid,
        "drowsiness": {"state": "none", "duration_seconds": 0.0, "reasons": ["brief_blink_or_closed"]},
        "facial_features": {"average_eye_openness": 0.26, "status": "available"},
        "visual_attention": {"state": "high", "duration_seconds": 5.0},
        "phone": {"status": "available", "state": "not_detected"},
        "head_state": {"state": "head_forward"},
        "face_occlusion": {"state": "none"},
        "hands": {"state": "not_near_face"},
        "identity": {"identity_state": "face_confirmed", "student_id": "p01", "face_visible": True},
        "observation_quality": {"status": "observable"},
    }
    eng._sync_temporal_events(track, now=200.0)
    assert f"{tid}:probable_drowsiness" in eng._open_events  # hold iniciado
    eng._sync_temporal_events(track, now=202.1)
    assert f"{tid}:probable_drowsiness" not in eng._open_events

