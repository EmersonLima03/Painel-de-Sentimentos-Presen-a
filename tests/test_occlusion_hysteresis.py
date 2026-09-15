"""Oclusão / cabeça baixa / recuperação rápida — calibração fundamentada."""

from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache
from app.pipeline.occlusion_head_arbitration import (
    pitch_may_promote_head_down,
    resolve_occlusion_vs_head_down,
)


def _engine(**extra):
    base = {
        "face_occlusion_suppress_when_landmarks_clear": True,
        "face_occlusion_persistent_seconds": 5.0,
        "face_occlusion_clear_hold_seconds": 4.0,
        "head_down_pitch_threshold": 0.45,
        "head_down_event_min_seconds": 8.0,
        "head_down_short_to_persistent_seconds": 8.0,
        "head_down_require_landmarks_quality": 0.45,
        "head_down_suppress_when_occlusion": True,
        "head_down_allow_face_missing_proxy": False,
        "behavioral_event_clear_hold_seconds": 0.5,
    }
    base.update(extra)
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    eng.settings = type("S", (), base)()
    return eng


def test_suppress_occlusion_when_landmarks_clear():
    """Só limpa oclusão genérica SEM wrist — landmarks sozinhos não anulam punho."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "duration_seconds": 12.0,
        "reasons": ["generic_blur"],
    }
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.85,
        "average_eye_openness": 0.28,
        "pitch": 0.3,
    }
    cache.hands = {"state": "not_near_face"}
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True, now=100.0)
    assert cache.face_occlusion["state"] == "none"


def test_suppress_does_not_clear_wrist_occlusion():
    """Mão na cara: landmarks 'ok' NÃO devem limpar oclusão por punho (bug do alerta sumindo)."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["wrist_near_face_persistent"],
        "duration_seconds": 20.0,
    }
    cache.hand_near_since = 80.0
    cache.hand_near_last_seen = 99.5
    cache.hands = {"state": "hand_near_face"}
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.9,
        "average_eye_openness": 0.25,
    }
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True, now=100.0)
    assert cache.face_occlusion["state"] == "persistent_possible_face_occlusion"
    assert cache.hand_near_since == 80.0


def test_pitch_promotes_head_down_when_pose_forward():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {"state": "head_forward", "confidence": 0.7, "reasons": []}
    cache.facial_features = {"status": "available", "pitch": 0.52, "landmarks_quality": 0.8}
    eng._apply_pitch_head_state(cache, face_visible=True, now=100.0)
    assert cache.head_state["state"] in ("head_down_short", "head_down_persistent")


def test_pitch_gated_when_landmarks_low():
    """Visibility gate: pitch alto com landmarks ruins NÃO promove head_down."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {"state": "head_forward", "confidence": 0.7, "reasons": []}
    cache.facial_features = {"status": "available", "pitch": 0.70, "landmarks_quality": 0.20}
    eng._apply_pitch_head_state(cache, face_visible=True, now=100.0)
    assert cache.head_state["state"] == "head_forward"


def test_face_missing_without_wrist_is_inconclusive_not_head_down():
    """Rosto sumiu sem punho → inconclusivo (não inventar cabeça baixa)."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.eyes_unobservable_since = 100.0
    cache.head_state = {"state": "pose_inconclusive", "confidence": 0.2, "reasons": []}
    eng._apply_face_not_observable_occlusion(cache, face_visible=False, now=106.0)
    assert cache.head_state["state"] == "pose_inconclusive"
    assert "face_missing_look_down_proxy" not in list(cache.head_state.get("reasons") or [])
    assert cache.face_occlusion.get("state", "none") in ("none", None) or cache.face_occlusion[
        "state"
    ] == "none"


def test_face_missing_with_body_geom_keeps_head_down():
    """Rosto sumiu + geometria corporal (nariz/ombros) → cabeça baixa válida."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.eyes_unobservable_since = 100.0
    cache.head_state = {
        "state": "head_down_short",
        "confidence": 0.7,
        "reasons": ["nose_shoulder_ratio=0.30"],
    }
    cache.pose = {"reasons": ["nose_shoulder_ratio=0.30"]}
    eng._apply_face_not_observable_occlusion(cache, face_visible=False, now=106.0)
    assert cache.head_state["state"] in ("head_down_short", "head_down_persistent")
    assert "body_geom_look_down" in cache.head_state["reasons"] or any(
        "nose_shoulder" in str(r) for r in cache.head_state["reasons"]
    )


def test_wrist_occlusion_suppresses_head_down():
    """Mão na cara: oclusão ganha — não cabeça baixa."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {
        "state": "head_down_persistent",
        "confidence": 0.8,
        "reasons": ["nose_shoulder_ratio=0.4"],
    }
    cache.face_occlusion = {
        "state": "possible_face_occlusion_by_hand",
        "reasons": ["wrist_near_face"],
        "duration_seconds": 2.0,
    }
    cache.hands = {"state": "hand_near_face"}
    cache.head_down_since = 90.0
    cache.head_down_accum_seconds = 15.0
    eng._apply_face_not_observable_occlusion(cache, face_visible=False, now=106.0)
    assert cache.head_state["state"] == "pose_inconclusive"
    assert "suppressed_by_face_occlusion" in cache.head_state["reasons"]
    assert cache.face_occlusion["state"] == "possible_face_occlusion_by_hand"
    assert cache.head_down_accum_seconds == 0.0


def test_face_not_observable_does_not_override_wrist_occlusion():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.eyes_unobservable_since = 100.0
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["wrist_near_face_persistent"],
        "duration_seconds": 8.0,
    }
    cache.hands = {"state": "hand_near_face"}
    eng._apply_face_not_observable_occlusion(cache, face_visible=False, now=120.0)
    assert any("wrist" in str(r) for r in cache.face_occlusion["reasons"])


def test_head_down_duration_without_face():
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {"state": "head_down_persistent", "confidence": 0.8, "reasons": []}
    eng._tick_head_down_duration(cache, now=10.0)
    eng._tick_head_down_duration(cache, now=20.0)
    assert cache.head_down_since == 10.0
    assert cache.head_down_accum_seconds >= 10.0


def test_short_to_persistent_uses_config_not_2_5s():
    eng = _engine(head_down_short_to_persistent_seconds=8.0)
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {"state": "head_down_short", "confidence": 0.7, "reasons": []}
    eng._tick_head_down_duration(cache, now=10.0)
    eng._tick_head_down_duration(cache, now=14.0)  # 4s < 8s
    assert cache.head_state["state"] == "head_down_short"
    eng._tick_head_down_duration(cache, now=19.0)  # 9s >= 8s
    assert cache.head_state["state"] == "head_down_persistent"


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
    eng._suppress_false_occlusion_if_face_clear(cache, face_visible=True, now=60.0)
    assert cache.face_occlusion["state"] == "persistent_possible_face_occlusion"


def test_legacy_proxy_opt_in():
    eng = _engine(head_down_allow_face_missing_proxy=True)
    cache = TrackAnalyticsCache(track_key="t1")
    cache.eyes_unobservable_since = 100.0
    cache.head_state = {"state": "pose_inconclusive", "confidence": 0.2, "reasons": []}
    eng._apply_face_not_observable_occlusion(cache, face_visible=False, now=106.0)
    assert cache.head_state["state"] in ("head_down_short", "head_down_persistent")
    assert "face_missing_look_down_proxy" in cache.head_state["reasons"]


def test_arbitration_unit_occlusion_wins():
    r = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={"state": "head_down_short", "reasons": ["nose_shoulder_ratio=0.3"]},
        face_occlusion={
            "state": "possible_face_occlusion_by_hand",
            "reasons": ["wrist_near_face"],
        },
        hands={"state": "hand_near_face"},
        body_head_geom=True,
        now=10.0,
        head_down_since=1.0,
        short_to_persistent_seconds=8.0,
    )
    assert r.decision == "occlusion_wins"
    assert r.suppressed_head_down
    assert r.head_state["state"] == "pose_inconclusive"


def test_pitch_may_promote_requires_quality():
    assert not pitch_may_promote_head_down(
        {"status": "available", "pitch": 0.6, "landmarks_quality": 0.2},
        pitch_threshold=0.45,
        require_landmarks_quality=0.45,
    )
    assert pitch_may_promote_head_down(
        {"status": "available", "pitch": 0.6, "landmarks_quality": 0.7},
        pitch_threshold=0.45,
        require_landmarks_quality=0.45,
    )


def test_stale_wrist_occlusion_clears_when_face_visible_and_hand_gone():
    """Alerta J não pode ficar 1+ min com o rosto já na tela e punho longe."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["wrist_near_face", "occlusion_hold"],
        "duration_seconds": 90.0,
    }
    cache.hands = {"state": "not_near_face"}
    cache.hand_near_since = None
    cache.hand_near_last_seen = 10.0
    cache.head_state = {"state": "head_forward", "confidence": 0.7, "reasons": []}
    cache.facial_features = {
        "status": "available",
        "landmarks_quality": 0.85,
        "average_eye_openness": 0.2,
        "yaw": 0.0,
        "pitch": 0.1,
    }
    eng._arbitrate_occlusion_vs_head(cache, face_visible=True, now=30.0)
    assert cache.face_occlusion.get("state") == "none"
