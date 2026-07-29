"""Regressão FP celular: garrafa/térmico/fone (cenários A–C TRI)."""

from app.vision.person_phone import PersonPhoneAssociator
from app.vision.phone_yolo import _bbox_plausible, _context_reject_reason


def test_tall_thermos_aspect_still_rejected():
    assert _bbox_plausible(40, 140, max_tall_ratio=2.7, max_wide_ratio=4.0) is False


def test_thermos_relative_height_rejected_even_if_aspect_borderline():
    person = (100.0, 50.0, 200.0, 400.0)
    # bbox ~1.8 ratio, altura 22% da pessoa — típico térmico
    phone = (250, 180, 50, 90, 0.55)
    assert _context_reject_reason(phone, person) == "bottle_like_relative_height"


def test_ear_region_small_box_rejected():
    person = (100.0, 50.0, 200.0, 400.0)
    # pequena bbox no canto superior direito (orelha/fone)
    phone = (280, 70, 28, 36, 0.6)
    assert _context_reject_reason(phone, person) == "ear_region_implausible"


def test_real_phone_chest_not_context_rejected():
    person = (100.0, 50.0, 200.0, 400.0)
    phone = (160, 200, 70, 30, 0.8)  # deitado no peito
    assert _context_reject_reason(phone, person) is None


def test_headphones_do_not_become_in_hand():
    assoc = PersonPhoneAssociator(interaction_requires_in_hand=True)
    people = {"p1": (0.0, 0.0, 200.0, 400.0)}
    face = (70.0, 40.0, 60.0, 70.0)
    # bbox lateral superior (fone)
    phones = [(155.0, 55.0, 24.0, 30.0, 0.7)]
    s = assoc.update(
        now=10.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists={},
        face_bboxes={"p1": face},
    )[0]
    assert s.phone_in_hand is False
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
        "phone_in_hand",
    )


def test_thermos_in_hand_not_promoted_without_wrist():
    assoc = PersonPhoneAssociator(interaction_requires_in_hand=True)
    people = {"p1": (0.0, 0.0, 200.0, 400.0)}
    # objeto alto lateral (térmico) — se passar YOLO, não deve virar interaction sem punho
    phones = [(160.0, 150.0, 35.0, 95.0, 0.5)]
    s = assoc.update(now=12.0, person_tracks=people, phone_boxes=phones, wrists={})[0]
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
    )
