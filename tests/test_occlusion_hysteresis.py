"""Oclusão / cabeça baixa / recuperação rápida."""

from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache


def _engine(**extra):
    base = {
        "face_occlusion_suppress_when_landmarks_clear": True,
        "face_occlusion_persistent_seconds": 5.0,
        "face_occlusion_clear_hold_seconds": 0.5,
        "head_down_pitch_threshold": 0.45,
        "behavioral_event_clear_hold_seconds": 0.5,
    }
    base.update(extra)
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = type("S", (), base)()
    return eng


def test_suppress_occlusion_when_landmarks_clear():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.face_occlusion = {"state": "persistent_possible_face_occlusion", "duration_seconds": 12.0}
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.85,
        "average_eye_openness": 0.28,
        "pitch": 0.3,
    }
    cache.hands = {"state": "hand_near_face"}
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True)
    assert cache.face_occlusion["state"] == "none"
    assert cache.hands["state"] == "not_near_face"
    assert cache.hand_near_since is None


def test_pitch_promotes_head_down_when_pose_forward():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {"state": "head_forward", "confidence": 0.7, "reasons": []}
    cache.facial_features = {"status": "available", "pitch": 0.52}
    eng._apply_pitch_head_state(cache, face_visible=True, now=100.0)
    assert cache.head_state["state"] in ("head_down_short", "head_down_persistent")


def test_face_not_observable_promotes_head_down_not_occlusion():
    """Rosto sumiu sem punho → cabeça baixa (não 'rosto coberto')."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.eyes_unobservable_since = 100.0
    cache.head_state = {"state": "pose_inconclusive", "confidence": 0.2, "reasons": []}
    eng._apply_face_not_observable_occlusion(cache, face_visible=False, now=106.0)
    assert cache.face_occlusion.get("state", "none") in ("none", None) or cache.face_occlusion["state"] == "none"
    assert cache.head_state["state"] in ("head_down_short", "head_down_persistent")
    assert "face_missing_look_down_proxy" in cache.head_state["reasons"]
    assert cache.head_down_accum_seconds >= 5.0


def test_face_not_observable_does_not_override_wrist_occlusion():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.eyes_unobservable_since = 100.0
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["wrist_near_face_persistent"],
        "duration_seconds": 8.0,
    }
    eng._apply_face_not_observable_occlusion(cache, face_visible=False, now=120.0)
    assert cache.face_occlusion["reasons"] == ["wrist_near_face_persistent"]


def test_head_down_duration_without_face():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {"state": "head_down_persistent", "confidence": 0.8, "reasons": []}
    eng._tick_head_down_duration(cache, now=10.0)
    eng._tick_head_down_duration(cache, now=20.0)
    assert cache.head_down_since == 10.0
    assert cache.head_down_accum_seconds >= 10.0


def test_suppress_does_not_clear_while_unobservable():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.eyes_unobservable_since = 50.0
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["face_not_observable_persistent"],
        "duration_seconds": 12.0,
    }
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.9,
        "average_eye_openness": 0.3,
    }
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True)
    assert cache.face_occlusion["state"] == "persistent_possible_face_occlusion"
