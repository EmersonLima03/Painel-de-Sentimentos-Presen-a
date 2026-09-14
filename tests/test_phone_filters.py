"""Filtros anti-FP de celular (garrafa/térmico)."""

from app.pipeline.analytics_track import filter_displayable_tracks, is_displayable_track
from app.vision.person_phone import PersonPhoneAssociator, _phone_on_chest, _phone_raised_to_face
from app.vision.phone_yolo import _bbox_plausible, _chest_phone_roi, _raised_phone_roi


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
    s = assoc.update(now=5.0, person_tracks=people, phone_boxes=phones, wrists=wrists, head_looking_down={"p1": True})[0]
    assert s.interaction_level in (
        "possible_phone_interaction",
        "probable_phone_interaction",
        "phone_in_hand",
    )
    assert "confirmed" not in s.interaction_level


def test_in_hand_heuristic_phone_on_chest():
    """Peito + olhar à frente: visível/near, NÃO interação nem in_hand."""
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(30.0, 70.0, 40.0, 18.0, 0.75)]
    s = assoc.update(
        now=6.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists={},
        head_looking_down={"p1": False},
    )[0]
    assert s.phone_in_hand is False
    assert s.interaction_level in ("phone_near_person", "phone_visible")
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
    )
    assert any(
        r in s.reasons
        for r in (
            "phone_resting_on_chest",
            "phone_resting_on_torso_looking_forward",
            "phone_resting_blocks_interaction",
        )
    )


def test_chest_phone_looking_forward_not_probable_even_with_wrist():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(35.0, 75.0, 28.0, 42.0, 0.8)]
    wrists = {"p1": [(50.0, 80.0)]}
    s = assoc.update(
        now=20.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists=wrists,
        head_looking_down={"p1": False},
    )[0]
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
    )


def test_portrait_phone_on_chest_looking_forward_not_interaction():
    """Cenário real: celular vertical no peito, olhando a câmera."""
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
        clear_hold_seconds=0.2,
    )
    people = {"p1": (200.0, 80.0, 400.0, 500.0)}
    face = (320.0, 90.0, 140.0, 170.0)
    phones = [(350.0, 300.0, 70.0, 130.0, 0.85)]
    wrists = {"p1": [(380.0, 340.0)]}
    s = assoc.update(
        now=40.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists=wrists,
        face_bboxes={"p1": face},
        head_looking_down={"p1": False},
    )[0]
    assert s.interaction_level in ("phone_near_person", "phone_visible")
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
        "phone_in_hand",
    )
    assert s.phone_in_hand is False


def test_chest_phone_head_down_can_still_be_in_hand():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(35.0, 75.0, 28.0, 42.0, 0.8)]
    wrists = {"p1": [(50.0, 80.0)]}
    s = assoc.update(
        now=8.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists=wrists,
        head_looking_down={"p1": True},
    )[0]
    assert s.phone_in_hand is True
    assert s.interaction_level in (
        "phone_in_hand",
        "possible_phone_interaction",
        "probable_phone_interaction",
    )


def test_near_face_without_wrist_is_not_in_hand():
    """Fone/objeto perto do rosto sem punho NÃO vira phone_in_hand (evita FP)."""
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
    assert s.phone_in_hand is False
    assert "confirmed" not in s.interaction_level
    assert s.interaction_level in ("phone_near_person", "phone_visible", "not_detected")


def test_real_phone_near_face_with_wrist_still_in_hand():
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    face = (35.0, 10.0, 30.0, 40.0)
    phones = [(40.0, 30.0, 22.0, 40.0, 0.9)]
    wrists = {"p1": [(48.0, 45.0)]}
    s = assoc.update(
        now=6.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists=wrists,
        face_bboxes={"p1": face},
    )[0]
    assert s.phone_in_hand is True
    assert "phone_near_wrist" in s.reasons


def test_phone_raised_to_face_looking_forward_is_in_hand():
    """E3: celular na frente do rosto, olhando o aparelho — uso, não 'só perto'."""
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
    )
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    face = (35.0, 10.0, 30.0, 40.0)
    phones = [(38.0, 18.0, 24.0, 42.0, 0.9)]
    s = assoc.update(
        now=6.0,
        person_tracks=people,
        phone_boxes=phones,
        wrists={},
        face_bboxes={"p1": face},
        head_looking_down={"p1": False},
    )[0]
    assert s.phone_in_hand is True
    assert s.interaction_level in (
        "phone_in_hand",
        "possible_phone_interaction",
        "probable_phone_interaction",
    )
    assert "phone_raised_to_face" in s.reasons


def test_live_partial_yolo_on_face_is_e3_use_not_lateral():
    """YOLO só no bloco das câmeras, colado na cara → uso E3, não 'ao lado sem uso'."""
    from app.vision.person_phone import _phone_lateral_to_face, _phone_raised_to_face

    person = (540.0, 421.0, 868.0, 648.0)
    face = (950.0, 455.0, 149.0, 214.0)
    phone = (835.0, 472.0, 126.0, 164.0)
    assert _phone_lateral_to_face(phone, face, person) is False
    assert _phone_raised_to_face(phone, face, person) is True
    assoc = PersonPhoneAssociator(interaction_requires_in_hand=True, clear_hold_seconds=0.2)
    s = assoc.update(
        now=8.0,
        person_tracks={"p1": person},
        phone_boxes=[(*phone, 0.86)],
        wrists={"p1": [(820.0, 620.0)]},
        face_bboxes={"p1": face},
        head_looking_down={"p1": False},
    )[0]
    assert s.phone_in_hand is True
    assert "phone_lateral_visible_not_use" not in (s.reasons or [])
    assert s.interaction_level in (
        "phone_in_hand",
        "possible_phone_interaction",
        "probable_phone_interaction",
    )


def test_live_large_phone_beside_face_looking_forward_is_not_use():
    """Celular ao lado do rosto, olhando a câmera = visível, não alerta de uso."""
    from app.vision.person_phone import _phone_large_handheld_upper

    person = (200.0, 40.0, 1500.0, 1000.0)
    face = (820.0, 200.0, 280.0, 360.0)
    phone = (1180.0, 280.0, 250.0, 400.0)
    assert _phone_large_handheld_upper(phone, person, face) is False
    assoc = PersonPhoneAssociator(interaction_requires_in_hand=True, clear_hold_seconds=0.2)
    s = assoc.update(
        now=12.0,
        person_tracks={"p1": person},
        phone_boxes=[(*phone, 0.86)],
        wrists={"p1": [(1280.0, 620.0)]},
        face_bboxes={"p1": face},
        head_looking_down={"p1": False},
    )[0]
    assert s.phone_in_hand is False
    assert s.interaction_level in ("phone_near_person", "phone_visible")
    assert s.interaction_level not in (
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
        "seconds_since_person_detection": 1.8,
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


def test_displayable_hides_lost_uncertain_without_student():
    """uncertain + temporarily_lost sem sid = fantasma (não exibir)."""
    lost = {
        "tracking_state": "temporarily_lost",
        "track_confidence": 0.5,
        "identity": {"face_visible": False, "identity_state": "uncertain"},
        "seconds_since_person_detection": 3.0,
    }
    assert is_displayable_track(lost) is False


def test_displayable_keeps_lost_with_identity_briefly():
    kept = {
        "tracking_state": "temporarily_lost",
        "student_id": "p01",
        "track_confidence": 0.8,
        "identity": {"face_visible": False, "identity_state": "body_continuity", "student_id": "p01"},
        "seconds_since_person_detection": 1.0,
    }
    assert is_displayable_track(kept) is True
    kept["seconds_since_person_detection"] = 4.0
    assert is_displayable_track(kept) is False


def test_displayable_hides_stale_ghost_without_face():
    """Sem pessoa no frame: não manter bbox fantasma na cortina por oclusão antiga."""
    ghost = {
        "tracking_state": "temporarily_lost",
        "student_id": "p01",
        "track_confidence": 0.8,
        "identity": {"face_visible": False, "identity_state": "face_confirmed", "student_id": "p01"},
        "seconds_since_person_detection": 5.0,
        "face_occlusion": {"state": "persistent_possible_face_occlusion"},
        "hands": {"state": "hand_near_face"},
    }
    assert is_displayable_track(ghost) is False


def test_live_closeup_chest_not_raised_despite_huge_yunet_face():
    """YuNet close-up (face ~meio corpo) não pode promover E4 a E3."""
    person = (427.0, 151.0, 1218.0, 918.0)
    face = (955.0, 256.0, 357.0, 486.0)
    phone = (930.0, 720.0, 90.0, 70.0)
    assert _phone_raised_to_face(phone, face, person) is False
    assert _phone_on_chest(phone, person, face) is True
    assoc = PersonPhoneAssociator(
        minimum_interaction_seconds=1.0,
        probable_seconds=3.0,
        interaction_requires_in_hand=True,
        clear_hold_seconds=0.2,
    )
    s = assoc.update(
        now=30.0,
        person_tracks={"p1": person},
        phone_boxes=[(*phone, 0.8)],
        wrists={"p1": [(980.0, 760.0)]},
        face_bboxes={"p1": face},
        head_looking_down={"p1": False},
    )[0]
    assert s.phone_in_hand is False
    assert s.interaction_level in ("phone_near_person", "phone_visible")
    assert s.interaction_level not in (
        "possible_phone_interaction",
        "probable_phone_interaction",
        "phone_in_hand",
    )


def test_raised_roi_covers_live_handset_in_front_of_face():
    """D/E3 close-up: aparelho na cara cabe no crop estreito (não só no peito)."""
    person = (200.0, 40.0, 1500.0, 1000.0)
    rx, ry, rw, rh = _raised_phone_roi(person)
    pcx, pcy = 960.0, 430.0
    assert rx <= pcx <= rx + rw
    assert ry <= pcy <= ry + rh
    assert rw < person[2] * 0.60
    assert rh < person[3] * 0.62


def test_chest_roi_covers_live_sternum_phone():
    """Close-up LIVE (bbox quase full-frame): aparelho no peito cabe no crop estreito."""
    person = (427.0, 151.0, 1218.0, 918.0)
    rx, ry, rw, rh = _chest_phone_roi(person)
    pcx, pcy = 980.0, 760.0
    assert rx <= pcx <= rx + rw
    assert ry <= pcy <= ry + rh
    assert rw < person[2] * 0.55
    assert rh < person[3] * 0.50
