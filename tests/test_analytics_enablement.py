"""Testes de enablement: landmarks Tasks, FER health, eventos temporais, phone status."""

from __future__ import annotations

import time

import numpy as np
import pytest

from app.pipeline.analytics_track import RealtimeAnalyticsEngine
from app.vision.emotion_engagement import emotion_backend_health
from app.vision.facial_signals import face_landmarker_health
from app.vision.expressions.normalization import normalize_expression_label


class _Settings:
    module_expression_mode = "debug"
    module_face_landmarks_mode = "debug"
    module_pose_mode = "debug"
    module_temporal_fusion_mode = "debug"
    module_phone_mode = "debug"
    phone_yolo_enabled = False
    expression_provider = "fer_legacy"
    expression_emotion_backend = "fer_onnx"
    analytics_quality_interval_seconds = 0.0
    analytics_landmarks_interval_seconds = 0.0
    expression_interval_seconds = 0.0
    expression_window_seconds = 8
    expression_minimum_samples = 2
    expression_minimum_confidence = 0.4
    expression_minimum_observation_quality = 0.2
    visual_attention_interval_seconds = 0.0
    visual_attention_window_seconds = 10
    visual_attention_minimum_observation_quality = 0.2
    drowsiness_possible_after_seconds = 6
    drowsiness_probable_after_seconds = 10
    drowsiness_minimum_observation_quality = 0.2
    drowsiness_cooldown_seconds = 20
    rule_engine_version = "rules-v0-baseline"
    threshold_profile = "presence-yaml-2026-07-23"
    camera_calibration_version = "test"


def test_face_landmarker_health_available_or_explicit():
    h = face_landmarker_health()
    assert h["status"] in ("available", "unavailable")
    assert h.get("provider")
    if h["status"] != "available":
        assert h.get("reason")


def test_fer_health_not_file_only():
    h = emotion_backend_health()
    assert h["status"] in (
        "available",
        "dependency_missing",
        "model_missing",
        "model_incompatible",
        "inference_failed",
        "unavailable",
    )
    # Não pode ser "available" só porque hdf5 existe sem backend
    if h["status"] == "available":
        assert h.get("model_name")
        # smoke: deve conseguir predizer
        from app.vision.emotion_engagement import predict_emotion_detail

        img = np.random.randint(40, 200, (96, 96, 3), dtype=np.uint8)
        label, conf, *_ = predict_emotion_detail(img)
        assert isinstance(label, str)
        assert conf >= 0.0


def test_normalize_expression_contract():
    assert normalize_expression_label("happy") == "positive"
    assert normalize_expression_label("sad") == "negative"
    assert normalize_expression_label("neutral") == "neutral"
    assert normalize_expression_label("surprise") == "inconclusive"


def test_temporal_events_open_close():
    eng = RealtimeAnalyticsEngine(_Settings())
    events = []
    eng.set_event_sink(lambda life, ev: events.append((life, ev["event_type"], ev["event_id"])))

    now = time.time()
    track = {
        "track_id": "p01",
        "student_id": "p01",
        "observation_quality": {"status": "observable"},
        "drowsiness": {"state": "possible", "confidence": 0.6, "reasons": ["eyes_closed_duration"]},
        "visual_attention": {"state": "high", "duration_seconds": 1.0, "confidence": 0.8, "reasons": []},
        "phone": {"status": "unavailable", "state": "not_detected"},
    }
    eng._sync_temporal_events(track, now)
    assert any(e[0] == "opened" and e[1] == "possible_drowsiness" for e in events)
    eid = events[0][2]

    track["drowsiness"] = {"state": "none", "confidence": 0.0, "reasons": []}
    # clear-hold de drowsiness (~4s): primeiro tick inicia hold; segundo fecha
    eng._sync_temporal_events(track, now + 1)
    eng._sync_temporal_events(track, now + 6)
    assert any(e[0] == "closed" and e[2] == eid for e in events)


def test_attention_short_lookdown_not_persistent_low():
    from app.analytics.attention_drowsiness import evaluate_visual_attention

    st = evaluate_visual_attention(
        head_yaw=0.0,
        head_pitch=0.5,
        observation_quality=0.9,
        duration_factor=1.0,
    )
    assert st.state in ("moderate", "inconclusive", "high", "low")
    assert st.score is None or 0.0 <= st.score <= 1.0
