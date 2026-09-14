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


def test_live_midhand_phone_conf036_not_bottle_rejected():
    """LIVE ByteTrack: handset mid-hand conf~0.36 sem wrist ≠ bottle_like (FN D)."""
    # person ~ full-frame USB; phone vertical ao lado do tronco/rosto
    person = (14.0, 24.0, 1390.0, 1044.0)
    phone = (420, 380, 138, 218, 0.36)
    assert _context_reject_reason(phone, person) is None


def test_headset_earcup_lateral_small_rejected():
    """C: earcup lateral-superior miúdo sem punho → headset_earcup / ear_region."""
    person = (14.0, 24.0, 1390.0, 1044.0)
    phone = (1200, 120, 70, 90, 0.45)
    assert _context_reject_reason(phone, person) in (
        "headset_earcup",
        "ear_region_implausible",
    )


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


def test_live_closeup_full_handset_not_bottle_rejected():
    """LIVE close-up: YOLO no aparelho INTEIRO (~0.66 da pessoa) ≠ garrafa.
    Sem isso a magenta fica só no bloco das câmeras (recorte curto passa, o cheio não)."""
    person = (199.0, 215.0, 1303.0, 853.0)
    full = (266, 218, 298, 564, 0.40)
    partial_top = (277, 215, 291, 220, 0.45)
    assert _context_reject_reason(full, person) is None
    assert _context_reject_reason(full, person, wrist_near=True) is None
    assert _context_reject_reason(partial_top, person) is None

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
    assert _context_reject_reason(phone, person) in (
        "ear_region_implausible",
        "headset_earcup",
    )


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


def test_large_overear_headphones_lateral_not_raised_in_hand():
    """Cenário C real: fone over-ear grande lateral ao rosto, sem punho ≠ phone_raised_to_face."""
    from app.vision.person_phone import _phone_raised_to_face, _phone_in_hand_heuristic

    person = (650.0, 360.0, 520.0, 720.0)
    face = (782.0, 481.0, 217.0, 301.0)
    # geometria observada em FoneGrande ~30.5s
    phone = (677.0, 574.0, 113.0, 171.0)
    assert _phone_raised_to_face(phone, face, person) is False
    assert _phone_in_hand_heuristic(phone, person, face) is False
    assoc = PersonPhoneAssociator(interaction_requires_in_hand=True)
    s = assoc.update(
        now=12.0,
        person_tracks={"p1": person},
        phone_boxes=[(*phone, 0.55)],
        wrists={},
        face_bboxes={"p1": face},
    )[0]
    assert s.phone_in_hand is False
    assert s.interaction_level not in (
        "phone_in_hand",
        "possible_phone_interaction",
        "probable_phone_interaction",
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


def test_c_rep2_borderline_tall_earcup_fragment_rejected():
    """C: fragmento tall MIÚDO rejeitado; handset largo (D) não é earcup."""
    from app.vision.phone_yolo import _earcup_fragment_reject_reason

    phone_small = (1204, 255, 42, 100, 0.59)  # hw ≈ 2.38, estreito
    assert _earcup_fragment_reject_reason(phone_small, []) == "aspect_tall_borderline_phone"
    # Handset real alto (ex. C_rep2 bbox larga) NÃO pode ser morto aqui (FN D).
    phone_handset = (1204, 255, 113, 254, 0.59)
    assert _earcup_fragment_reject_reason(phone_handset, []) is None


def test_c_rep2_sibling_of_aspect_rejected_also_dropped():
    """Mesmo objeto: YOLO rejeita tall>2.7 e aceita fragmento — sibling fecha o buraco."""
    from app.vision.phone_yolo import _earcup_fragment_reject_reason

    # hw < 2.15 mas overlap com AR reject
    phone = (1200, 250, 100, 200, 0.55)  # hw = 2.0
    rejected = [
        {
            "bbox": [1191, 253, 124, 346],
            "reject_reason": "aspect_ratio_unlikely_phone",
            "confidence": 0.67,
        }
    ]
    assert (
        _earcup_fragment_reject_reason(phone, rejected)
        == "sibling_aspect_ratio_unlikely_phone"
    )


def test_real_phone_aspect_under_borderline_not_earcup_filtered():
    """Celular real vertical típico (hw~1.5–2.08) não cai no filtro earcup."""
    from app.vision.phone_yolo import _earcup_fragment_reject_reason

    phone = (250, 120, 48, 100, 0.72)  # hw ≈ 2.08
    assert _earcup_fragment_reject_reason(phone, []) is None
