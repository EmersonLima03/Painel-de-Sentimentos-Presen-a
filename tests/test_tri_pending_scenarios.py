"""Cenários TRI pendentes — regressão A, I, L (pesquisa + calibração 2026-08)."""

from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache, is_displayable_track
from app.pipeline.occlusion_head_arbitration import resolve_occlusion_vs_head_down
from app.vision.phone_yolo import _context_reject_reason


def test_transparent_bottle_wide_handheld_rejected():
    """A — garrafa transparente larga na mão, sem punho."""
    person = (100.0, 50.0, 200.0, 400.0)
    bottle = (220, 160, 38, 42, 0.55)  # hw~1.1, wide, conf modesta
    assert _context_reject_reason(bottle, person, wrist_near=False) == "bottle_like_wide_handheld"


def test_transparent_bottle_does_not_reject_real_phone_vertical():
    """P2 — celular vertical real não pode cair na regra wide."""
    person = (100.0, 50.0, 220.0, 420.0)
    phone = (250, 120, 48, 100, 0.55)
    assert _context_reject_reason(phone, person) is None
    assert _context_reject_reason(phone, person, wrist_near=True) is None


def test_scenario_i_face_missing_lateral_not_body_geom():
    """I — rosto sumiu / virou: sem ears_above → não promove head_down."""
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {
        "state": "pose_inconclusive",
        "confidence": 0.28,
        "reasons": ["face_missing_lateral_or_out_of_frame"],
    }
    cache.pose = {"reasons": ["face_missing_lateral_or_out_of_frame"]}
    assert eng._body_head_geom_active(cache) is False

    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state=dict(cache.head_state),
        face_occlusion={"state": "none", "reasons": []},
        facial_features={"status": "unavailable"},
        body_head_geom=False,
        now=30.0,
        allow_face_missing_proxy=False,
    )
    assert res.head_state.get("state") not in ("head_down_short", "head_down_persistent")


def test_scenario_i_head_turned_is_valid_contract_state():
    """I — head_turned é semanticamente válido em perfil (não exige só pose_inconclusive)."""
    from pathlib import Path
    import json

    data = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "tri_validation_scenarios.json").read_text(
            encoding="utf-8"
        )
    )
    i = next(s for s in data["scenarios"] if s["id"] == "I")
    assert "head_turned" in i["allow_head"]
    assert "pose_inconclusive" in i["allow_head"]
    assert "head_down_persistent" in i["forbid"]
    assert "possible_drowsiness" in i["forbid"]
    assert "probable_drowsiness" in i["forbid"]

    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {
        "state": "head_turned",
        "confidence": 0.55,
        "reasons": ["lateral_nose_offset"],
    }
    cache.pose = {"reasons": ["lateral_nose_offset"]}
    assert eng._body_head_geom_active(cache) is False

    res = resolve_occlusion_vs_head_down(
        face_visible=True,
        head_state=dict(cache.head_state),
        face_occlusion={"state": "none", "reasons": []},
        facial_features={"status": "partial", "landmarks_quality": 0.3},
        body_head_geom=False,
        now=30.0,
        allow_face_missing_proxy=False,
    )
    assert res.head_state.get("state") not in ("head_down_short", "head_down_persistent")
    # Contrato: head_turned permanece válido; não forçar pose_inconclusive.
    assert cache.head_state["state"] == "head_turned"


def test_scenario_h_ears_above_still_body_geom():
    """H ✅ — look-down extremo com orelhas acima dos ombros."""
    eng = RealtimeAnalyticsEngine.__new__(RealtimeAnalyticsEngine)
    cache = TrackAnalyticsCache(track_key="t1")
    cache.head_state = {
        "state": "head_down_short",
        "confidence": 0.62,
        "reasons": ["shoulders_without_face_look_down", "ears_above_shoulders"],
    }
    cache.pose = {"reasons": ["shoulders_without_face_look_down", "ears_above_shoulders"]}
    assert eng._body_head_geom_active(cache) is True


def test_occlusion_keeps_displayable_while_temporarily_lost():
    """J/K: mão no rosto — YOLO pisca mas track não some em 2.5s."""
    track = {
        "tracking_state": "temporarily_lost",
        "seconds_since_person_detection": 2.0,
        "student_id": "s1",
        "identity": {"identity_state": "uncertain", "face_visible": False},
        "face_occlusion": {"state": "persistent_possible_face_occlusion"},
        "hands": {"state": "hand_near_face"},
    }
    assert is_displayable_track(track) is True


def test_active_with_face_bbox_always_displayable():
    """YuNet bbox sozinha sem landmarks/corpo = fantasma — não displayable."""
    ghost = {
        "tracking_state": "active",
        "track_confidence": 0.35,
        "face_bbox": [10, 10, 80, 90],
        "identity": {"face_visible": False, "identity_state": "unknown"},
        "observability": {"body_detected": False},
    }
    assert is_displayable_track(ghost) is False
    real = {
        "tracking_state": "active",
        "track_confidence": 0.55,
        "face_bbox": [10, 10, 80, 90],
        "identity": {"face_visible": True, "identity_state": "unknown"},
        "facial_features": {"landmarks_quality": 0.5},
        "observability": {"body_detected": False},
    }
    assert is_displayable_track(real) is True
    body = {
        "tracking_state": "active",
        "track_confidence": 0.5,
        "identity": {"face_visible": False, "identity_state": "unknown"},
        "observability": {"body_detected": True},
    }
    assert is_displayable_track(body) is True


def test_l_contract_near_is_optional_not_occlusion():
    """L — hand_near_face opcional; face_occlusion=none válido com face clara (sem cap inventado)."""
    from pathlib import Path
    import json

    data = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "tri_validation_scenarios.json").read_text(
            encoding="utf-8"
        )
    )
    l = next(s for s in data["scenarios"] if s["id"] == "L")
    assert l["hand_near_face"] == "optional"
    assert "none" in l.get("allow_occlusion", [])
    # Não existe regra near_face_without_head_zone_cap no produto.
    assert "near_face_without_head_zone_cap" not in json.dumps(data)
