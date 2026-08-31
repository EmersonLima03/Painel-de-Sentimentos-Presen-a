"""Cabeça baixa vs face não observável — gates de visibilidade."""

from app.pipeline.occlusion_head_arbitration import resolve_occlusion_vs_head_down


def test_face_missing_without_body_geom_clears_invented_head_down():
    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={"state": "head_down_short", "confidence": 0.5},
        face_occlusion={"state": "none", "reasons": []},
        facial_features={"status": "unavailable", "landmarks_quality": 0.1},
        body_head_geom=False,
        now=10.0,
        allow_face_missing_proxy=False,
        require_landmarks_quality=0.45,
    )
    assert res.head_state.get("state") in ("pose_inconclusive", "face_not_observable", "none") or (
        res.decision in ("face_missing_inconclusive", "clear_head_down", "inconclusive")
    )
    assert res.head_state.get("state") not in ("head_down_short", "head_down_persistent")


def test_reliable_pose_keeps_head_down_short_or_persistent():
    res = resolve_occlusion_vs_head_down(
        face_visible=True,
        head_state={
            "state": "head_down_short",
            "confidence": 0.8,
            "reasons": ["nose_shoulder_ratio=0.25"],
        },
        face_occlusion={"state": "none", "reasons": []},
        facial_features={
            "status": "available",
            "landmarks_quality": 0.8,
            "pitch": 0.55,
        },
        body_head_geom=True,
        now=20.0,
        head_down_since=12.0,
        head_down_accum_seconds=9.0,
        short_to_persistent_seconds=8.0,
        allow_face_missing_proxy=False,
        require_landmarks_quality=0.45,
    )
    assert res.head_state.get("state") in ("head_down_short", "head_down_persistent")


def test_unobservable_pose_accepts_inconclusive_or_face_not_observable():
    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={"state": "facing_forward", "confidence": 0.2},
        face_occlusion={"state": "none", "reasons": []},
        facial_features={"status": "unavailable"},
        body_head_geom=False,
        now=15.0,
        allow_face_missing_proxy=False,
    )
    assert res.head_state.get("state") in ("pose_inconclusive", "face_not_observable")
    assert res.head_state.get("state") not in ("head_down_short", "head_down_persistent")


def test_never_promote_head_down_only_from_face_disappearance():
    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={"state": "facing_forward", "confidence": 0.6, "reasons": []},
        face_occlusion={"state": "none", "reasons": []},
        facial_features={"status": "unavailable"},
        body_head_geom=False,
        now=30.0,
        allow_face_missing_proxy=False,
    )
    assert res.head_state.get("state") not in (
        "head_down_short",
        "head_down_persistent",
        "head_supported",
    )


def test_body_geom_keeps_head_down_when_face_missing():
    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={"state": "pose_inconclusive", "confidence": 0.3},
        face_occlusion={"state": "none", "reasons": []},
        facial_features={"status": "unavailable"},
        body_head_geom=True,
        now=20.0,
        head_down_since=12.0,
        head_down_accum_seconds=8.0,
        allow_face_missing_proxy=False,
        short_to_persistent_seconds=8.0,
    )
    assert res.head_state.get("state") in ("head_down_short", "head_down_persistent")


def test_shoulders_without_face_reason_counts_as_body_geom():
    """Ângulo extremo (só coroa): reason shoulders_without_face deve promover via body_geom."""
    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={
            "state": "head_down_short",
            "confidence": 0.55,
            "reasons": ["shoulders_without_face_look_down"],
        },
        face_occlusion={"state": "none", "reasons": []},
        facial_features={"status": "inconclusive"},
        body_head_geom=True,
        now=30.0,
        head_down_since=20.0,
        head_down_accum_seconds=10.0,
        short_to_persistent_seconds=8.0,
        allow_face_missing_proxy=False,
    )
    assert res.head_state.get("state") == "head_down_persistent"
    assert res.decision == "head_down_body_geom"


def test_occlusion_suppresses_head_down():
    res = resolve_occlusion_vs_head_down(
        face_visible=True,
        head_state={"state": "head_down_short", "confidence": 0.6},
        face_occlusion={
            "state": "persistent_possible_face_occlusion",
            "reasons": ["wrist_near_face"],
        },
        facial_features={"status": "available", "landmarks_quality": 0.2},
        body_head_geom=False,
        now=20.0,
        allow_face_missing_proxy=False,
        suppress_when_occlusion=True,
    )
    assert res.suppressed_head_down is True


def test_weak_chest_near_does_not_suppress_head_down_when_face_missing():
    """Punho no peito / near inventado NÃO pode zerar cabeça baixa (regressão H)."""
    res = resolve_occlusion_vs_head_down(
        face_visible=False,
        head_state={
            "state": "head_down_short",
            "confidence": 0.6,
            "reasons": ["shoulders_without_face_look_down", "wrist_near_chest_keep_head_down"],
        },
        face_occlusion={
            "state": "possible_face_occlusion_by_hand",
            "reasons": ["wrist_near_while_face_missing"],
        },
        hands={"state": "hand_near_face"},
        facial_features={"status": "inconclusive"},
        body_head_geom=True,
        now=30.0,
        head_down_since=10.0,
        head_down_accum_seconds=20.0,
        short_to_persistent_seconds=8.0,
        allow_face_missing_proxy=False,
        suppress_when_occlusion=True,
    )
    assert res.suppressed_head_down is False
    assert res.head_state.get("state") in ("head_down_short", "head_down_persistent")
