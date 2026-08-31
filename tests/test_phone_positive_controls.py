"""Controles positivos de celular (evitar falso negativo TRI)."""

from app.vision.person_phone import PersonPhoneAssociator
from app.vision.phone_yolo import _context_reject_reason, reset_ear_stability_for_tests


def setup_function():
    reset_ear_stability_for_tests()


def test_real_phone_at_ear_not_context_rejected():
    """Celular real encostado à orelha: tamanho/aspecto de telefone + conf → não rejeitar."""
    person = (100.0, 50.0, 200.0, 400.0)
    # ~0.037 area ratio, vertical, conf alta — típico smartphone na orelha
    phone = (270, 60, 40, 75, 0.72)
    assert _context_reject_reason(phone, person) is None
    assert _context_reject_reason(phone, person, wrist_near=True) is None


def test_earbud_small_still_rejected():
    person = (100.0, 50.0, 200.0, 400.0)
    phone = (280, 70, 28, 36, 0.6)
    assert _context_reject_reason(phone, person) == "ear_region_implausible"


def test_real_phone_at_ear_with_wrist_is_in_hand():
    assoc = PersonPhoneAssociator(interaction_requires_in_hand=True)
    people = {"p1": (0.0, 0.0, 200.0, 400.0)}
    face = (70.0, 40.0, 60.0, 70.0)
    phones = [(155.0, 50.0, 40.0, 72.0, 0.8)]
    wrists = {"p1": [(165.0, 85.0)]}
    s = assoc.update(
        now=10.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists=wrists,
        face_bboxes={"p1": face},
    )[0]
    assert s.phone_in_hand is True
    assert s.interaction_level in (
        "phone_in_hand",
        "possible_phone_interaction",
        "probable_phone_interaction",
    )


def test_real_phone_vertical_in_hand_with_wrist():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=5.0,
        probable_seconds=12.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 200.0, 400.0)}
    phones = [(90.0, 160.0, 28.0, 55.0, 0.85)]
    wrists = {"p1": [(100.0, 185.0)]}
    s = assoc.update(now=8.0, person_tracks=people, phone_boxes=phones, wrists=wrists)[0]
    assert s.phone_in_hand is True
    assert _context_reject_reason(phones[0], people["p1"]) is None


def test_real_phone_held_near_lap_with_wrist():
    assoc = PersonPhoneAssociator(interaction_requires_in_hand=True)
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    # colo / parte inferior — com punho
    phones = [(40.0, 150.0, 30.0, 45.0, 0.88)]
    wrists = {"p1": [(50.0, 160.0)]}
    s = assoc.update(now=6.0, person_tracks=people, phone_boxes=phones, wrists=wrists)[0]
    assert s.phone_in_hand is True
    assert s.interaction_level != "not_detected"


def test_phone_partially_covered_by_hand_still_associated():
    """Celular parcialmente coberto: punho perto ainda conta como in_hand."""
    assoc = PersonPhoneAssociator(interaction_requires_in_hand=True)
    people = {"p1": (0.0, 0.0, 200.0, 400.0)}
    phones = [(80.0, 180.0, 35.0, 50.0, 0.7)]
    wrists = {"p1": [(95.0, 200.0)]}
    s = assoc.update(now=7.0, person_tracks=people, phone_boxes=phones, wrists=wrists)[0]
    assert s.phone_visible or s.phone_near_person or s.phone_in_hand
    assert s.phone_in_hand is True


def test_phone_on_table_then_pickup():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=5.0,
        probable_seconds=12.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(40.0, 185.0, 30.0, 40.0, 0.85)]
    idle = assoc.update(now=5.0, person_tracks=people, phone_boxes=phones, wrists={})[0]
    assert idle.phone_in_hand is False
    assert idle.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
    )
    wrists = {"p1": [(50.0, 190.0)]}
    grabbed = assoc.update(now=12.0, person_tracks=people, phone_boxes=phones, wrists=wrists)[0]
    assert grabbed.phone_in_hand is True
