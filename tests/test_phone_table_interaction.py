"""Celular na mesa ≠ interação (cenário E TRI)."""

from app.vision.person_phone import PersonPhoneAssociator


def test_phone_on_table_near_not_interaction():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=5.0,
        probable_seconds=12.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    # celular na mesa à frente / abaixo do torso (sem punho)
    phones = [(40.0, 185.0, 30.0, 40.0, 0.85)]
    s = assoc.update(now=20.0, person_tracks=people, phone_boxes=phones, wrists={})[0]
    assert s.interaction_level in ("phone_near_person", "phone_visible", "not_detected")
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
    )
    assert s.phone_in_hand is False


def test_hand_near_phone_on_table_without_grasp_not_probable():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=5.0,
        probable_seconds=12.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(40.0, 160.0, 30.0, 50.0, 0.85)]
    # punho longe do telefone
    wrists = {"p1": [(10.0, 80.0)]}
    s = assoc.update(
        now=20.0, person_tracks=people, phone_boxes=phones, wrists=wrists
    )[0]
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
    )


def test_pickup_with_wrist_can_progress():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=5.0,
        probable_seconds=12.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(40.0, 100.0, 25.0, 45.0, 0.9)]
    wrists = {"p1": [(50.0, 120.0)]}
    s5 = assoc.update(now=5.0, person_tracks=people, phone_boxes=phones, wrists=wrists)[0]
    s12 = assoc.update(now=17.0, person_tracks=people, phone_boxes=phones, wrists=wrists)[0]
    assert s5.phone_in_hand is True
    assert s12.interaction_level in (
        "possible_phone_interaction",
        "probable_phone_interaction",
        "phone_in_hand",
    )
    assert "confirmed" not in s12.interaction_level
