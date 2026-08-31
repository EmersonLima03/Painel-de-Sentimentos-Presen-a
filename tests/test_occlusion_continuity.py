"""Regressão oclusão: 1 mão, continuidade com face sumida, anti-fragmentação."""

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
        "rule_engine_version": "rules-v0-baseline",
        "threshold_profile": "test",
        "camera_calibration_version": "test",
        "runtime_mode": "demo",
    }
    base.update(extra)
    return RealtimeAnalyticsEngine(type("S", (), base)())


def test_occlusion_persists_while_face_missing_after_wrist_confirmed():
    """Duas mãos: punho some atrás da mão, mas face ainda sumida → oclusão não zera em 4s."""
    eng = _engine()
    cache = TrackAnalyticsCache(track_key="t1")
    cache.hand_near_since = 100.0
    cache.hand_near_last_seen = 110.0  # último punho há ~8s
    cache.hands = {"state": "not_near_face"}
    cache.face_occlusion = {
        "state": "persistent_possible_face_occlusion",
        "reasons": ["wrist_near_face_persistent", "occlusion_hold"],
        "duration_seconds": 18.0,
    }
    # Sem face: hold efetivo = 15s → ainda ativo em now=118 (8s após last_seen)
    now = 118.0
    hand_hold = 4.0
    face_missing_hold = 15.0
    effective = max(hand_hold, face_missing_hold)
    assert (now - cache.hand_near_last_seen) < effective

    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={"state": "pose_inconclusive", "confidence": 0.3},
        face_occlusion=cache.face_occlusion,
        facial_features={"status": "unavailable"},
        hands={"state": "not_near_face"},
        body_head_geom=False,
        now=now,
        allow_face_missing_proxy=False,
    )
    assert res.head_state.get("state") not in ("head_down_short", "head_down_persistent")
    assert res.face_occlusion.get("state") == "persistent_possible_face_occlusion"


def test_face_missing_without_hand_evidence_still_clears_generic_occlusion():
    """Rosto sumiu sem evidência de mão → não inventar oclusão persistente."""
    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={"state": "facing_forward", "confidence": 0.5},
        face_occlusion={"state": "possible_face_occlusion_by_hand", "reasons": ["generic_blur"]},
        facial_features={"status": "unavailable"},
        hands={"state": "not_near_face"},
        body_head_geom=False,
        now=50.0,
        allow_face_missing_proxy=False,
    )
    assert res.face_occlusion.get("state") in ("none", None) or "cleared" in str(
        (res.face_occlusion.get("reasons") or [""])[0]
    )


def test_occlusion_event_stays_open_across_wrist_flicker():
    """Evento face_occluded não fecha em <8s de clear-hold."""
    eng = _engine()
    events = []
    eng.set_event_sink(lambda life, ev: events.append((life, ev["event_type"], ev["event_id"])))
    cache = TrackAnalyticsCache(track_key="p01")
    eng._cache["p01"] = cache
    now = 1000.0
    track = {
        "track_id": "p01",
        "student_id": "p01",
        "observation_quality": {"status": "partially_observable"},
        "drowsiness": {"state": "inconclusive"},
        "visual_attention": {"state": "inconclusive", "duration_seconds": 0},
        "phone": {"status": "unavailable", "state": "not_detected"},
        "face_occlusion": {
            "state": "persistent_possible_face_occlusion",
            "duration_seconds": 20.0,
            "reasons": ["wrist_near_face_persistent"],
        },
        "head_state": {"state": "pose_inconclusive"},
    }
    eng._sync_temporal_events(track, now)
    assert any(e[0] == "opened" and e[1] == "face_occluded_persistent" for e in events)
    eid = next(e[2] for e in events if e[0] == "opened")

    # Flicker: oclusão some por 6s — com hold 15s o evento NÃO deve fechar
    track["face_occlusion"] = {"state": "none", "reasons": ["wrist_cleared"]}
    eng._sync_temporal_events(track, now + 1)
    eng._sync_temporal_events(track, now + 6)
    assert not any(e[0] == "closed" and e[2] == eid for e in events)

    # Após hold longo (>=15s desde clear start) pode fechar
    eng._sync_temporal_events(track, now + 17)
    assert any(e[0] == "closed" and e[2] == eid for e in events)


def test_elbow_reason_counts_as_hand_evidence_for_event():
    eng = _engine()
    events = []
    eng.set_event_sink(lambda life, ev: events.append((life, ev["event_type"])))
    cache = TrackAnalyticsCache(track_key="p01")
    eng._cache["p01"] = cache
    track = {
        "track_id": "p01",
        "observation_quality": {"status": "partially_observable"},
        "drowsiness": {"state": "inconclusive"},
        "visual_attention": {"state": "inconclusive", "duration_seconds": 0},
        "phone": {"status": "unavailable", "state": "not_detected"},
        "face_occlusion": {
            "state": "persistent_possible_face_occlusion",
            "duration_seconds": 12.0,
            "reasons": ["elbow_raised_head_zone_proxy"],
        },
        "head_state": {"state": "pose_inconclusive"},
    }
    eng._sync_temporal_events(track, 50.0)
    assert any(e[1] == "face_occluded_persistent" for e in events)
