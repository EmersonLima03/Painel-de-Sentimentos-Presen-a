"""Regressão FP celular: garrafa/térmico/fone (cenários A–C TRI)."""

from app.vision.person_phone import PersonPhoneAssociator
from app.vision.phone_yolo import _bbox_plausible, _context_reject_reason


def test_tall_thermos_aspect_still_rejected():
    assert _bbox_plausible(40, 140, max_tall_ratio=2.7, max_wide_ratio=4.0) is False


def test_thermos_relative_height_rejected_even_if_aspect_borderline():
    person = (100.0, 50.0, 200.0, 400.0)
    # térmico fino / conf modest — não smartphone
    phone = (250, 180, 32, 95, 0.52)
    assert _context_reject_reason(phone, person) == "bottle_like_relative_height"
    # largo mas conf abaixo do keep vertical
    phone2 = (250, 180, 50, 90, 0.48)
    assert _context_reject_reason(phone2, person) == "bottle_like_relative_height"


def test_real_phone_vertical_keep_path_restored():
    """Regressão: filtro 'bottle_column' não pode matar celular real (fase estável D/eventos)."""
    person = (100.0, 50.0, 220.0, 420.0)
    phone = (250, 120, 48, 100, 0.55)  # vertical close-up, conf da fase estável
    assert _context_reject_reason(phone, person) is None
    assert _context_reject_reason(phone, person, wrist_near=True) is None


def test_thermos_thin_still_rejected_without_killing_phone_path():
    """Contrato TROUBLESHOOTING: térmico fino rejeitado; smartphone keep_vertical intacto."""
    person = (100.0, 50.0, 200.0, 400.0)
    thermos = (250, 180, 28, 100, 0.58)  # thin_tall
    assert _context_reject_reason(thermos, person) == "bottle_like_relative_height"
    phone = (160, 160, 45, 80, 0.62)
    assert _context_reject_reason(phone, person) is None


def test_thermos_in_hand_not_promoted_to_interaction_event():
    """Garrafa pode aparecer near/in_hand no pior caso; NÃO vira possible/probable (P0 docs)."""
    from app.vision.person_phone import PersonPhoneAssociator

    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=5.0,
        probable_seconds=12.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 200.0, 400.0)}
    # objeto alto lateral — se YOLO deixar passar sem punho, sem interação
    phones = [(160.0, 150.0, 35.0, 95.0, 0.5)]
    s = assoc.update(now=20.0, person_tracks=people, phone_boxes=phones, wrists={})[0]
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
    )


def test_real_vertical_phone_closeup_not_bottle_rejected():
    """Close-up webcam: celular vertical pode ter h>~18% da pessoa — não é garrafa."""
    person = (100.0, 50.0, 220.0, 420.0)
    phone = (250, 120, 48, 100, 0.72)  # hw~2.08, h/ph~0.24, conf alta
    assert _context_reject_reason(phone, person) is None
    assert _context_reject_reason(phone, person, wrist_near=True) is None


def test_vertical_phone_with_wrist_kept_even_if_conf_borderline():
    person = (100.0, 50.0, 200.0, 400.0)
    phone = (240, 140, 42, 85, 0.53)
    assert _context_reject_reason(phone, person, wrist_near=True) is None


def test_ear_region_small_box_rejected():
    person = (100.0, 50.0, 200.0, 400.0)
    # pequena bbox no canto superior direito (orelha/fone) — combinação implausível
    phone = (280, 70, 28, 36, 0.6)
    assert _context_reject_reason(phone, person) == "ear_region_implausible"


def test_real_phone_at_ear_not_rejected():
    person = (100.0, 50.0, 200.0, 400.0)
    phone = (270, 60, 40, 75, 0.72)
    assert _context_reject_reason(phone, person) is None


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
