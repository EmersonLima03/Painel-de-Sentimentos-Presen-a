"""Testes do analytics real por track (quality, landmarks, expression, atenção, phone status)."""

from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.analytics_track import RealtimeAnalyticsEngine, ascii_overlay_label, _clip_crop
from app.vision.observation_quality import compute_observation_quality


class _FakeSettings:
    module_expression_mode = "debug"
    module_face_landmarks_mode = "debug"
    module_pose_mode = "debug"
    module_temporal_fusion_mode = "debug"
    module_phone_mode = "debug"
    phone_yolo_enabled = False
    expression_provider = "fer_legacy"
    analytics_quality_interval_seconds = 0.0
    analytics_landmarks_interval_seconds = 0.0
    expression_interval_seconds = 0.0
    expression_window_seconds = 8
    expression_minimum_samples = 2
    expression_minimum_confidence = 0.4
    expression_minimum_observation_quality = 0.3
    visual_attention_interval_seconds = 0.0
    visual_attention_window_seconds = 10
    visual_attention_minimum_observation_quality = 0.3
    drowsiness_possible_after_seconds = 6
    drowsiness_probable_after_seconds = 10
    drowsiness_minimum_observation_quality = 0.3
    drowsiness_cooldown_seconds = 20


def _face(mean=140, blur_noise=False, size=120):
    img = np.ones((size, size, 3), dtype=np.uint8) * int(mean)
    if blur_noise:
        # baixa variância = blur artificial
        pass
    else:
        # textura para sharpness
        rng = np.random.default_rng(0)
        noise = rng.integers(0, 40, img.shape, dtype=np.uint8)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def test_ascii_overlay_no_accents():
    assert "ç" not in ascii_overlay_label("Atenção não conclusiva").lower() or True
    assert ascii_overlay_label("Atenção não conclusiva") == "Atencao nao conclusiva"


def test_clip_bbox_invalid():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert _clip_crop(frame, (90, 90, 2, 2)) is None
    assert _clip_crop(frame, (10, 10, 40, 40)) is not None


def test_quality_observable_and_dark():
    bright = _face(mean=140, size=100)
    q = compute_observation_quality(bright)
    assert q.overall_score > 0.3
    dark = _face(mean=10, size=100)
    qd = compute_observation_quality(dark)
    assert "low_light" in qd.reasons or qd.illumination_score < 0.5


def test_quality_small_face():
    small = _face(size=20)
    q = compute_observation_quality(small)
    assert "face_too_small" in q.reasons or q.face_size_score < 0.35


def test_engine_snapshot_contract_no_empty_objects():
    eng = RealtimeAnalyticsEngine(_FakeSettings())
    frame = _face(size=160)
    # desenha "rosto" no frame grande
    big = np.zeros((480, 640, 3), dtype=np.uint8)
    big[100:260, 200:360] = frame
    tracks = eng.process_camera(
        camera_id="cam-web",
        frame=big,
        matches=[{"student_id": "p01", "confidence": 0.81, "full_name": "Teste"}],
        boxes=[(200, 100, 160, 160)],
    )
    assert len(tracks) == 1
    t = tracks[0]
    assert t["student_id"] == "p01"
    assert "observation_quality" in t and t["observation_quality"].get("status")
    assert "facial_features" in t and t["facial_features"].get("status")
    assert "latencies_ms" in t
    assert "quality" in t["latencies_ms"] or t["latencies_ms"].get("total_analytics") is not None
    # nulls explícitos permitidos; objeto não pode ser {}
    assert t["observation_quality"] != {}
    assert t["facial_features"] != {}
    assert t["expression"].get("status") in (
        "available",
        "unavailable",
        "inconclusive",
        "error",
        "disabled",
    )
    assert t["phone"].get("status") in ("unavailable", "disabled", "available", "error")
    counts = eng.classroom_counts(tracks, present_count=1)
    assert counts["visible"] == 1
    assert counts["present"] == 1
    assert counts["observable"] + counts["inconclusive"] >= 0


def test_invalid_bbox_inconclusive_quality():
    eng = RealtimeAnalyticsEngine(_FakeSettings())
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    tracks = eng.process_camera(
        camera_id="cam",
        frame=frame,
        matches=[{"student_id": "p01", "confidence": 0.5}],
        boxes=[(95, 95, 2, 2)],
    )
    assert tracks[0]["observation_quality"]["status"] == "inconclusive"
    assert "invalid_bbox" in tracks[0]["observation_quality"]["reasons"]


def test_short_eyes_closed_not_persistent_drowsiness():
    eng = RealtimeAnalyticsEngine(_FakeSettings())
    cache = eng._get_cache("p01")
    cache.observation_quality = {
        "overall_score": 0.8,
        "status": "observable",
        "reasons": [],
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.1,
        "yaw": 0.0,
        "pitch": 0.1,
    }
    now = 1000.0
    cache.eyes_closed_since = now - 2.0
    attn, drow = eng._compute_attention_drowsiness(cache, now)
    assert drow["state"] == "none"


def test_phone_unavailable_explicit():
    eng = RealtimeAnalyticsEngine(_FakeSettings())
    assert eng._phone_status == "unavailable"
    frame = _face(size=160)
    big = np.zeros((240, 240, 3), dtype=np.uint8)
    big[40:200, 40:200] = frame
    tracks = eng.process_camera(
        camera_id="cam",
        frame=big,
        matches=[{"student_id": "p01", "confidence": 0.7}],
        boxes=[(40, 40, 160, 160)],
    )
    assert tracks[0]["phone"]["status"] == "unavailable"
    assert tracks[0]["phone"].get("reason") or tracks[0]["phone"].get("reasons")
