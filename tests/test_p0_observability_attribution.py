"""Testes P0: pausa por oclusão, attribution, EAR config, body observability fields."""

from __future__ import annotations

import time

import numpy as np

from app.pipeline.analytics_track import RealtimeAnalyticsEngine, TrackAnalyticsCache
from app.vision.identity_binding import IdentityBindingEngine
from app.vision.tracking_types import FaceTrack, PersonTrack
from datetime import datetime, timezone


class _S:
    module_expression_mode = "disabled"
    module_face_landmarks_mode = "debug"
    module_pose_mode = "disabled"
    module_temporal_fusion_mode = "debug"
    module_phone_mode = "disabled"
    phone_yolo_enabled = False
    expression_provider = "fer_legacy"
    pose_body_enabled = False
    person_tracking_enabled = True
    analytics_quality_interval_seconds = 0.0
    analytics_landmarks_interval_seconds = 0.0
    expression_interval_seconds = 0.0
    visual_attention_interval_seconds = 0.0
    visual_attention_window_seconds = 10
    visual_attention_minimum_observation_quality = 0.3
    drowsiness_possible_after_seconds = 6
    drowsiness_probable_after_seconds = 30
    drowsiness_minimum_observation_quality = 0.3
    drowsiness_cooldown_seconds = 20
    drowsiness_eye_closed_ear_threshold = 0.18
    drowsiness_observation_gap_inconclusive_seconds = 8.0
    phone_possible_after_seconds = 5.0
    phone_probable_after_seconds = 12.0
    experimental_perclos_enabled = False
    identity_face_missing_ttl_seconds = 12.0
    identity_minimum_new_confidence = 0.75
    identity_minimum_margin = 0.10
    identity_confirmations_before_switch = 3
    identity_switch_cooldown_seconds = 10.0
    identity_confidence_decay_per_second = 0.04
    identity_body_continuity_uncertain_threshold = 0.45
    identity_temporarily_lost_uncertain_seconds = 4.0
    person_tracking_max_time_lost_seconds = 8.0
    rule_engine_version = "t"
    threshold_profile = "t"
    camera_calibration_version = "t"


def test_occlusion_does_not_inflate_eyes_closed_duration():
    eng = RealtimeAnalyticsEngine(_S())
    cache = eng._get_cache("t1")
    cache.observation_quality = {"overall_observability": 0.9, "overall_score": 0.9, "status": "observable"}
    cache.facial_features = {"status": "available", "average_eye_openness": 0.10, "yaw": 0.0, "pitch": 0.0}
    cache.face_occlusion = {"state": "none"}
    cache.head_state = {"state": "pose_inconclusive"}
    # 4s olhos fechados
    now = 100.0
    cache.eyes_last_tick = now
    cache.eyes_closed_accum_seconds = 0.0
    attn, drow = eng._compute_attention_drowsiness(cache, now + 4.0, face_visible=True)
    assert drow["duration_seconds"] >= 3.5
    accum_before = cache.eyes_closed_accum_seconds
    # oclusão 5s (<8) — pausa sem zerar / sem inconclusive_gap
    cache.facial_features = {"status": "unavailable", "average_eye_openness": None}
    cache.face_occlusion = {"state": "persistent_possible_face_occlusion", "duration_seconds": 5.0}
    attn2, drow2 = eng._compute_attention_drowsiness(cache, now + 9.0, face_visible=False)
    assert drow2.get("observation_paused") is True
    assert abs(cache.eyes_closed_accum_seconds - accum_before) < 0.01
    assert attn2.get("observation_paused") is True
    # duração da pausa = max(unobservable, occlusion.duration); neste tick unobs≈0, usa occ duration
    assert float(attn2.get("duration_seconds") or 0) >= 4.5
    attn2b, _ = eng._compute_attention_drowsiness(cache, now + 14.0, face_visible=False)
    assert float(attn2b.get("unobservable_seconds") or 0) >= 4.5
    # reaparece ainda fechado — retoma do valor pausado, não soma o gap
    cache.facial_features = {"status": "available", "average_eye_openness": 0.10, "yaw": 0.0, "pitch": 0.0}
    cache.face_occlusion = {"state": "none"}
    attn3, drow3 = eng._compute_attention_drowsiness(cache, now + 15.0, face_visible=True)
    assert drow3["duration_seconds"] < 8.0
    assert drow3["duration_seconds"] >= accum_before - 0.1


def test_ear_threshold_from_settings():
    s = _S()
    s.drowsiness_eye_closed_ear_threshold = 0.05
    eng = RealtimeAnalyticsEngine(s)
    cache = eng._get_cache("t1")
    cache.observation_quality = {"overall_observability": 0.9, "overall_score": 0.9}
    cache.facial_features = {"status": "available", "average_eye_openness": 0.10, "yaw": 0.0, "pitch": 0.0}
    cache.face_occlusion = {"state": "none"}
    cache.head_state = {"state": "pose_inconclusive"}
    _, drow = eng._compute_attention_drowsiness(cache, 10.0, face_visible=True)
    # 0.10 > 0.05 → não fecha
    assert drow["state"] in ("none", "inconclusive") or drow["duration_seconds"] == 0


def test_attribution_pending_when_uncertain():
    eng = RealtimeAnalyticsEngine(_S())
    track = {
        "track_id": "p1",
        "person_track_id": "p1",
        "student_id": "stu1",
        "identity": {
            "student_id": "stu1",
            "identity_state": "uncertain",
            "confidence": 0.5,
            "body_continuity_confidence": 0.3,
            "revalidation_required": True,
            "ambiguity_reasons": ["person_overlap"],
        },
        "observation_quality": {"status": "observable"},
        "drowsiness": {"state": "possible", "confidence": 0.6, "reasons": ["eyes_closed_duration"]},
        "visual_attention": {},
        "phone": {"status": "disabled"},
        "head_state": {},
        "face_occlusion": {},
    }
    eng._sync_temporal_events(track, time.time())
    evs = [e for e in eng._open_events.values() if e["event_type"] == "possible_drowsiness"]
    assert evs
    assert evs[0]["attribution_status"] == "pending"
    assert evs[0]["confirmed_student_id"] is None
    assert evs[0]["candidate_student_id"] == "stu1"
    assert evs[0]["person_track_id"] == "p1"


def test_persistent_occlusion_opens_timed_event():
    eng = RealtimeAnalyticsEngine(_S())
    now = time.time()
    track = {
        "track_id": "p1",
        "person_track_id": "p1",
        "identity": {"identity_state": "body_continuity", "student_id": "stu1", "confidence": 0.8, "body_continuity_confidence": 0.8},
        "observation_quality": {"status": "partially_observable"},
        "drowsiness": {"state": "inconclusive"},
        "visual_attention": {"state": "inconclusive", "duration_seconds": 45.0, "observation_paused": True},
        "phone": {"status": "disabled"},
        "head_state": {"state": "head_forward"},
        "face_occlusion": {
            "state": "persistent_possible_face_occlusion",
            "confidence": 0.55,
            "duration_seconds": 45.0,
            "reasons": ["wrist_near_face_persistent"],
        },
    }
    eng._sync_temporal_events(track, now)
    evs = [e for e in eng._open_events.values() if e["event_type"] == "face_occluded_persistent"]
    assert evs
    eng._sync_temporal_events(track, now + 12.0)
    assert float(evs[0]["duration_seconds"]) >= 11.0


def test_evaluate_drowsiness_uses_possible_after_not_4():
    from app.analytics.attention_drowsiness import evaluate_apparent_drowsiness

    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=5.0,
        head_pitch=0.0,
        sample_count=10,
        observation_quality=0.9,
        min_duration_seconds=30,
        possible_after_seconds=6,
    )
    assert st.state == "none"
    st2 = evaluate_apparent_drowsiness(
        eyes_closed_seconds=6.5,
        head_pitch=0.0,
        sample_count=10,
        observation_quality=0.9,
        min_duration_seconds=30,
        possible_after_seconds=6,
    )
    assert st2.state == "possible"
