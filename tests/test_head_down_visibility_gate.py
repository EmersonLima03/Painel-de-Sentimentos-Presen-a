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
