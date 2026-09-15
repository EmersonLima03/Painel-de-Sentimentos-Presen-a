"""I — perfil: yaw na caixa do rosto; punho no ombro ≠ oclusão J."""

from app.vision.body_pose import (
    crown_look_down_face,
    ears_stacked_profile,
    face_crop_skin_ratio,
    nose_ear_distance_profile,
    nose_in_profile_face,
    nose_inside_face_bbox,
    unilateral_ear_profile,
    wrist_in_true_head_zone,
)


def test_live_i_take_nose_in_left_third_is_profile():
    # Captura LIVE 2026-09-14 i2.json (perfil olhando à esquerda).
    nose = (1390.086, 479.787, 0.999)
    face = (1305.0, 257.0, 296.0, 455.0)
    assert nose_in_profile_face(nose, face) is True


def test_junk_face_extreme_rel_is_not_profile():
    # H look-down 2026-09-14 h6a: YuNet na cortina, rel 0.79.
    nose = (1299.0, 491.5, 0.99)
    face = (1120.0, 291.0, 227.0, 336.0)
    assert nose_in_profile_face(nose, face) is False
    nose = (400.0, 200.0, 0.99)
    face = (300.0, 80.0, 200.0, 240.0)
    assert nose_in_profile_face(nose, face) is False


def test_fan_false_face_without_nose_inside_is_not_profile():
    nose = (200.0, 180.0, 0.99)
    fan = (900.0, 200.0, 280.0, 280.0)
    assert nose_in_profile_face(nose, fan) is False


def test_stacked_ears_are_profile_span():
    assert ears_stacked_profile((100.0, 80.0, 0.9), (108.0, 82.0, 0.9), 560.0) is True
    assert ears_stacked_profile((80.0, 80.0, 0.9), (220.0, 82.0, 0.9), 560.0) is False


def test_exactly_one_ear_is_profile():
    assert unilateral_ear_profile(None, (1400.0, 400.0, 0.9)) is True
    assert unilateral_ear_profile((1400.0, 400.0, 0.9), None) is True
    assert unilateral_ear_profile(None, None) is False
    assert unilateral_ear_profile((100.0, 80.0, 0.9), (220.0, 82.0, 0.9)) is False


def test_live_i_three_quarter_ear_near_nose_is_profile():
    nose = (1237.4, 488.3, 0.99)
    lear = (1406.7, 465.2, 0.99)
    rear = (1209.0, 445.3, 0.99)
    assert nose_ear_distance_profile(nose, lear, rear, 556.6) is True


def test_frontal_similar_ear_distances_not_profile():
    nose = (400.0, 200.0, 0.99)
    lear = (310.0, 195.0, 0.99)
    rear = (490.0, 195.0, 0.99)
    assert nose_ear_distance_profile(nose, lear, rear, 400.0) is False


def test_live_i_wrist_at_shoulder_is_not_head_zone():
    wrist = (1152.029, 728.953, 0.969)
    nose = (1390.086, 479.787, 0.999)
    ls = (1779.368, 917.547, 0.998)
    rs = (1218.650, 735.666, 0.999)
    face = (1305.0, 257.0, 296.0, 455.0)
    assert (
        wrist_in_true_head_zone(
            wrist, nose=nose, left_shoulder=ls, right_shoulder=rs, face_bbox=face
        )
        is False
    )


def test_facepalm_wrist_on_face_is_head_zone():
    nose = (400.0, 180.0, 0.99)
    ls = (280.0, 360.0, 0.99)
    rs = (520.0, 360.0, 0.99)
    face = (320.0, 80.0, 160.0, 200.0)
    wrist = (400.0, 160.0, 0.9)
    assert (
        wrist_in_true_head_zone(
            wrist, nose=nose, left_shoulder=ls, right_shoulder=rs, face_bbox=face
        )
        is True
    )


def test_live_j_palm_on_face_wrist_at_chin_is_head_zone():
    # LIVE 2026-09-14 j1: palma cobre o rosto, YuNet some, punho no queixo.
    wrist = (1050.402, 710.214, 0.974)
    nose = (1055.331, 468.696, 0.999)
    ls = (1359.698, 785.076, 0.996)
    rs = (697.921, 826.826, 0.998)
    assert (
        wrist_in_true_head_zone(
            wrist, nose=nose, left_shoulder=ls, right_shoulder=rs, face_bbox=None
        )
        is True
    )


def test_hair_crop_with_nose_inside_is_crown_look_down():
    import numpy as np

    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    frame[:] = (20, 20, 20)
    face = (40.0, 20.0, 80.0, 80.0)
    nose = (80.0, 60.0, 0.99)
    assert nose_inside_face_bbox(nose, face) is True
    assert face_crop_skin_ratio(frame, face) < 0.24
    assert crown_look_down_face(frame, nose, face) is True


def test_skin_face_crop_is_not_crown():
    import numpy as np

    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    frame[:] = (90, 140, 200)  # BGR pele clara
    face = (40.0, 20.0, 80.0, 80.0)
    nose = (80.0, 60.0, 0.99)
    assert face_crop_skin_ratio(frame, face) >= 0.24
    assert crown_look_down_face(frame, nose, face) is False


def test_real_face_with_dark_headset_pixels_is_not_crown():
    import numpy as np

    # LIVE h18b: pele alta (~0.81) + pixels escuros do fone. Não é topo da cabeça.
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    frame[:] = (90, 140, 200)
    frame[0:40, :] = (20, 20, 20)
    face = (40.0, 20.0, 80.0, 80.0)
    nose = (80.0, 60.0, 0.99)
    assert face_crop_skin_ratio(frame, face) >= 0.24
    assert crown_look_down_face(frame, nose, face) is False


def test_dark_curtain_without_nose_inside_is_not_crown():
    import numpy as np

    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    frame[:] = (30, 30, 30)
    face = (40.0, 20.0, 80.0, 80.0)
    nose = (180.0, 60.0, 0.99)
    assert nose_inside_face_bbox(nose, face) is False
    assert crown_look_down_face(frame, nose, face) is False
