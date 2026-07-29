"""Filtros anti-FP de celular (garrafa/térmico)."""

from app.pipeline.analytics_track import filter_displayable_tracks, is_displayable_track
from app.vision.person_phone import PersonPhoneAssociator
from app.vision.phone_yolo import _bbox_plausible


def test_bbox_rejects_tall_thermos_shape():
    assert _bbox_plausible(40, 140, max_tall_ratio=2.7, max_wide_ratio=4.0) is False
    assert _bbox_plausible(35, 70, max_tall_ratio=2.7, max_wide_ratio=4.0) is True


def test_bbox_accepts_flat_phone_on_chest():
    assert _bbox_plausible(120, 45, max_tall_ratio=2.7, max_wide_ratio=4.0) is True
    assert _bbox_plausible(220, 50, max_tall_ratio=2.7, max_wide_ratio=4.0) is False


def test_probable_requires_in_hand_when_configured():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    # Celular alto no enquadramento (perto, mas fora da heurística de “na mão”).
    phones = [(45.0, 15.0, 20.0, 35.0, 0.9)]
    s = assoc.update(now=10.0, person_tracks=people, phone_boxes=phones, wrists={})[0]
    assert s.interaction_level == "phone_near_person"
    assert "interaction" not in s.interaction_level


def test_probable_with_wrist_near_phone():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(40.0, 80.0, 20.0, 40.0, 0.9)]
    wrists = {"p1": [(50.0, 100.0)]}
    s = assoc.update(now=5.0, person_tracks=people, phone_boxes=phones, wrists=wrists)[0]
    assert s.interaction_level in (
        "possible_phone_interaction",
        "probable_phone_interaction",
        "phone_in_hand",
    )
    assert "confirmed" not in s.interaction_level


def test_in_hand_heuristic_phone_on_chest():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(30.0, 70.0, 40.0, 18.0, 0.75)]
    s = assoc.update(now=6.0, person_tracks=people, phone_boxes=phones, wrists={})[0]
    assert s.phone_in_hand is True
    assert "phone_on_chest" in s.reasons


def test_in_hand_heuristic_without_wrist_near_face():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    face = (35.0, 10.0, 30.0, 40.0)
    phones = [(38.0, 22.0, 18.0, 32.0, 0.88)]
    s = assoc.update(
        now=6.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists={},
        face_bboxes={"p1": face},
    )[0]
    assert s.phone_in_hand is True
    assert "phone_in_hand_heuristic" in s.reasons
    assert s.interaction_level in (
        "possible_phone_interaction",
        "probable_phone_interaction",
        "phone_in_hand",
    )


def test_displayable_track_hides_temporarily_lost_ghost():
    ghost = {
        "tracking_state": "temporarily_lost",
        "track_confidence": 0.15,
        "identity": {"face_visible": False, "identity_state": "unknown"},
        "observability": {"body_detected": False},
    }
    active = {
        "tracking_state": "active",
        "track_confidence": 0.6,
        "identity": {"face_visible": True, "identity_state": "unknown"},
        "observability": {"body_detected": True},
    }
    assert is_displayable_track(ghost) is False
    assert is_displayable_track(active) is True
    assert len(filter_displayable_tracks([ghost, active])) == 1
