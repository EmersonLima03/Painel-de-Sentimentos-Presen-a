"""Engajamento por pose da cabeça."""

from app.vision.head_pose_engagement import _map_pose_to_state


def test_looking_at_camera_attentive():
    assert _map_pose_to_state(yaw=0.05, pitch=0.55, ear=0.22) == "attentive"


def test_turned_away_distracted():
    assert _map_pose_to_state(yaw=0.55, pitch=0.55, ear=0.22) == "distracted"


def test_slight_turn_neutral():
    assert _map_pose_to_state(yaw=0.30, pitch=0.55, ear=0.22) == "neutral"


def test_eyes_closed_distracted():
    assert _map_pose_to_state(yaw=0.0, pitch=0.55, ear=0.08) == "distracted"
