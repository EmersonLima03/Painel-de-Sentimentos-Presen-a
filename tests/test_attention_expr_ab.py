"""Baixa atenção derivada + A/B de expressão."""

from types import SimpleNamespace

from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache
from app.vision.expressions.ab_pick import pick_expression_ab


def _engine(**extra):
    base = {
        "face_occlusion_persistent_seconds": 5.0,
        "head_down_event_min_seconds": 8.0,
        "visual_attention_window_seconds": 10.0,
        "visual_attention_minimum_observation_quality": 0.55,
        "drowsiness_minimum_observation_quality": 0.60,
        "drowsiness_possible_after_seconds": 6.0,
        "drowsiness_probable_after_seconds": 30.0,
        "drowsiness_cooldown_seconds": 20.0,
        "drowsiness_eye_closed_ear_threshold": 0.18,
        "drowsiness_observation_gap_inconclusive_seconds": 8.0,
        "head_down_pitch_threshold": 0.45,
        "face_occlusion_clear_hold_seconds": 0.45,
        "expression_minimum_samples": 3,
    }
    base.update(extra)
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = type("S", (), base)()
    return eng


def test_low_attention_derived_from_phone():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.phone = {"state": "probable_phone_interaction"}
    cache.head_state = {"state": "head_forward"}
    reasons = eng._low_attention_derived_reasons(cache, drowsiness_state="none")
    assert "derived_from_phone" in reasons


def test_low_attention_derived_from_drowsiness_and_head_down():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.phone = {"state": "not_detected"}
    cache.head_state = {"state": "head_down_persistent"}
    cache.head_down_accum_seconds = 12.0
    reasons = eng._low_attention_derived_reasons(cache, drowsiness_state="probable")
    assert "derived_from_drowsiness" in reasons
    assert "derived_from_head_down" in reasons


def test_face_missing_attention_becomes_low_with_head_down():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.observation_quality = {"overall_observability": 0.7}
    cache.facial_features = {"status": "unavailable"}
    cache.face_occlusion = {"state": "none"}
    cache.head_state = {"state": "head_down_persistent", "duration_seconds": 20.0}
    cache.head_down_accum_seconds = 20.0
    cache.eyes_unobservable_since = 100.0
    cache.phone = {"state": "not_detected"}
    attn, drow = eng._compute_attention_drowsiness(cache, now=120.0, face_visible=False)
    assert attn["state"] == "low"
    assert "derived_from_head_down" in attn["reasons"]
    assert drow["state"] == "inconclusive"


def test_ab_pick_prefers_positive_when_secondary_sees_smile():
    primary = SimpleNamespace(label="neutral", confidence=0.7, raw_label="neutral")
    secondary = SimpleNamespace(label="happy", confidence=0.72, raw_label="happy")
    chosen, reason = pick_expression_ab(primary, secondary)
    assert normalize_ok(chosen) == "positive" or chosen.label in ("happy", "positive")
    assert "positive" in reason


def normalize_ok(pred):
    from app.vision.expressions.normalization import normalize_expression_label

    return normalize_expression_label(pred.label)
