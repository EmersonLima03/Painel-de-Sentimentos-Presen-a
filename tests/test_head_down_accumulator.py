"""Regressão: cabeça baixa com face ausente não pode zerar o timer."""

from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache


class _S:
    head_down_short_to_persistent_seconds = 8.0
    head_down_event_min_seconds = 8.0
    head_down_inconclusive_hold_seconds = 12.0
    head_down_suppress_when_occlusion = True
    head_down_allow_face_missing_proxy = False
    head_down_require_landmarks_quality = 0.45
    face_occlusion_persistent_seconds = 5.0


def test_tick_promotes_short_to_persistent_after_8s():
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = _S()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {
        "state": "head_down_short",
        "confidence": 0.6,
        "reasons": ["shoulders_without_face_look_down", "ears_above_shoulders"],
    }
    cache.head_down_since = 100.0
    cache.facial_features = {"status": "inconclusive"}
    cache.eyes_unobservable_since = 100.0
    eng._tick_head_down_duration(cache, now=109.0)
    assert cache.head_state["state"] == "head_down_persistent"
    assert cache.head_down_accum_seconds >= 8.0


def test_head_down_event_started_at_anchors_to_since():
    """Banner deve mostrar ~tempo real, não só segundos desde o open."""
    from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache

    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = type(
        "S",
        (),
        {
            "head_down_event_min_seconds": 8.0,
            "head_down_suppress_when_occlusion": True,
            "behavioral_event_clear_hold_seconds": 0.5,
            "face_occlusion_clear_hold_seconds": 0.5,
            "runtime_mode": "rtsp",
            "is_simulated": False,
        },
    )()
    eng._open_events = {}
    eng._live_event_buffer = []
    eng._ws_events = []
    eng._cache = {}
    eng._event_sink = None
    eng.episode_counts = {}  # if needed
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_down_since = 100.0
    cache.head_down_accum_seconds = 25.0
    cache.episode_counts = {}
    cache.event_clear_since = {}
    cache.head_state = {
        "state": "head_down_persistent",
        "confidence": 0.7,
        "reasons": ["shoulders_without_face_look_down"],
        "duration_seconds": 25.0,
    }
    eng._cache["t1"] = cache
    track = {
        "track_id": "t1",
        "person_track_id": "t1",
        "observation_quality": {"status": "partially_observable"},
        "identity": {"identity_state": "body_continuity"},
        "head_state": dict(cache.head_state),
        "face_occlusion": {"state": "none", "reasons": []},
        "drowsiness": {},
        "visual_attention": {},
        "phone": {},
    }
    eng._sync_temporal_events(track, now=125.0)
    ev = eng._open_events.get("t1:head_down_persistent")
    assert ev is not None
    assert float(ev["started_at"]) == 100.0
    assert float(ev["duration_seconds"]) >= 24.0


def test_head_state_for_track_shows_persistent_during_flicker():
    from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache

    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = type(
        "S",
        (),
        {"head_down_short_to_persistent_seconds": 8.0, "head_down_event_min_seconds": 8.0},
    )()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {"state": "pose_inconclusive", "confidence": 0.2, "reasons": []}
    cache.head_down_since = 100.0
    cache.head_down_accum_seconds = 20.0
    cache.face_occlusion = {"state": "none", "reasons": []}
    out = eng._head_state_for_track(cache, now=120.0)
    assert out["state"] == "head_down_persistent"
    assert out["duration_seconds"] >= 20.0
