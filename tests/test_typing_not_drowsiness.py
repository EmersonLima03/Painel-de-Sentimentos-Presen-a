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
    """Olhos realmente fechados (EAR profundo) continuam gerando possible (G)."""
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
        "pitch": 0.14,
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
