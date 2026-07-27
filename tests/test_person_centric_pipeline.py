"""Testes críticos do pipeline person-first."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from app.vision.face_person_association import FacePersonAssociator
from app.vision.identity_binding import IdentityBindingEngine
from app.vision.person_phone import PersonPhoneAssociator
from app.vision.person_tracker import BboxPersonTrackerAdapter, detect_persons
from app.vision.tracking_types import FaceTrack, PersonTrack
from app.pipeline.analytics_track import RealtimeAnalyticsEngine


def _now_dt():
    return datetime.now(timezone.utc)


def _person(tid, bbox, cam="cam"):
    n = _now_dt()
    return PersonTrack(tid, cam, n, n, bbox, tracking_confidence=0.9, observation_quality=0.9)


def _face(tid, bbox, cam="cam"):
    n = _now_dt()
    return FaceTrack(tid, cam, n, n, bbox, observation_quality=0.9)


class _FakeSettings:
    module_expression_mode = "disabled"
    module_face_landmarks_mode = "debug"
    module_pose_mode = "disabled"
    module_temporal_fusion_mode = "debug"
    module_phone_mode = "debug"
    phone_yolo_enabled = False
    expression_provider = "fer_legacy"
    pose_body_enabled = False
    person_tracking_enabled = True
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
    identity_face_missing_ttl_seconds = 3.0
    identity_minimum_new_confidence = 0.75
    identity_minimum_margin = 0.10
    identity_confirmations_before_switch = 3
    identity_switch_cooldown_seconds = 10.0
    identity_confidence_decay_per_second = 0.04


def test_bbox_tracker_requires_detections():
    """Fallback: lista vazia sem detecção interna → 0 tracks."""
    ad = BboxPersonTrackerAdapter("cam")
    assert ad.update([], None, 0.0) == []
    assert ad.last_debug["detections_count"] == 0
    tracks = ad.update([(10, 10, 50, 120, 0.8)], None, 0.0)
    assert len(tracks) == 1
    assert tracks[0].track_id.startswith("raw-bbox-")


def test_face_person_association_upper_body_not_iou_only():
    persons = [_person("p1", (0, 0, 100, 200)), _person("p2", (200, 0, 100, 200))]
    # face pequena no topo de p1
    faces = [_face("f1", (30, 10, 30, 30))]
    assoc = FacePersonAssociator()
    r = assoc.associate(persons, faces)
    hit = [a for a in r if a.person_track_id == "p1" and a.face_track_id == "f1"]
    assert hit
    assert hit[0].score >= 0.35
    assert "center_inside" in hit[0].method or "upper_body" in hit[0].method


def test_wrong_face_near_wrong_body_ambiguous_or_low():
    persons = [_person("p1", (0, 0, 100, 200)), _person("p2", (90, 0, 100, 200))]
    # face no meio entre os dois
    faces = [_face("f1", (85, 20, 25, 25))]
    assoc = FacePersonAssociator(ambiguous_gap=0.15)
    r = assoc.associate(persons, faces)
    # pelo menos um ambíguo ou score baixo no vínculo errado
    linked = [a for a in r if a.face_track_id == "f1" and a.person_track_id]
    assert linked
    assert linked[0].ambiguous or linked[0].score < 0.7


def test_identity_ttl_expires_to_unknown():
    eng = IdentityBindingEngine(
        face_missing_ttl_seconds=2.0,
        minimum_new_identity_confidence=0.7,
        confidence_decay_per_second=0.01,
    )
    persons = [_person("cam-person-001", (0, 0, 100, 200))]
    faces = [_face("face-000", (20, 10, 40, 40))]
    fi = {"face-000": {"student_id": "p01", "confidence": 0.9, "margin": 0.2}}
    st1 = eng.update_continuity(now=100.0, person_tracks=persons, face_tracks=faces, face_identities=fi)
    assert st1["cam-person-001"].student_id == "p01"
    # face some
    st2 = eng.update_continuity(now=101.0, person_tracks=persons, face_tracks=[], face_identities={})
    assert st2["cam-person-001"].source == "cached_binding"
    assert st2["cam-person-001"].student_id == "p01"
    st3 = eng.update_continuity(now=103.5, person_tracks=persons, face_tracks=[], face_identities={})
    assert st3["cam-person-001"].student_id is None
    assert st3["cam-person-001"].source == "unknown"
    ev = eng.drain_events()
    assert any(e["event_type"] == "identity_binding_expired" for e in ev)


def test_identity_swap_blocked_low_confidence():
    eng = IdentityBindingEngine(
        face_missing_ttl_seconds=12.0,
        minimum_new_identity_confidence=0.75,
        confirmations_before_switch=3,
    )
    persons = [_person("t1", (0, 0, 100, 200))]
    faces = [_face("f1", (20, 10, 40, 40))]
    eng.update_continuity(
        now=1.0,
        person_tracks=persons,
        face_tracks=faces,
        face_identities={"f1": {"student_id": "p01", "confidence": 0.9, "margin": 0.2}},
    )
    eng.update_continuity(
        now=2.0,
        person_tracks=persons,
        face_tracks=faces,
        face_identities={"f1": {"student_id": "p12", "confidence": 0.55, "margin": 0.05}},
    )
    st = eng.get_state("t1")
    assert st.student_id == "p01"
    ev = eng.drain_events()
    assert any(e["event_type"] == "identity_swap_blocked" for e in ev)


def test_identity_swap_needs_confirmations():
    eng = IdentityBindingEngine(
        face_missing_ttl_seconds=12.0,
        minimum_new_identity_confidence=0.75,
        confirmations_before_switch=3,
        identity_switch_cooldown_seconds=0.0,
    )
    persons = [_person("t1", (0, 0, 100, 200))]
    faces = [_face("f1", (20, 10, 40, 40))]
    eng.update_continuity(
        now=1.0,
        person_tracks=persons,
        face_tracks=faces,
        face_identities={"f1": {"student_id": "p01", "confidence": 0.9, "margin": 0.2}},
    )
    for i in range(2):
        eng.update_continuity(
            now=10.0 + i,
            person_tracks=persons,
            face_tracks=faces,
            face_identities={"f1": {"student_id": "p12", "confidence": 0.88, "margin": 0.15}},
        )
        assert eng.get_state("t1").student_id == "p01"
    eng.update_continuity(
        now=20.0,
        person_tracks=persons,
        face_tracks=faces,
        face_identities={"f1": {"student_id": "p12", "confidence": 0.88, "margin": 0.15}},
    )
    assert eng.get_state("t1").student_id == "p12"
    assert any(e["event_type"] == "identity_swap_committed" for e in eng.drain_events())


def test_no_duplicate_identity_two_tracks():
    eng = IdentityBindingEngine(minimum_new_identity_confidence=0.7)
    persons = [
        _person("t1", (0, 0, 100, 200)),
        _person("t2", (200, 0, 100, 200)),
    ]
    faces = [
        _face("f1", (20, 10, 40, 40)),
        _face("f2", (220, 10, 40, 40)),
    ]
    eng.update_continuity(
        now=1.0,
        person_tracks=persons,
        face_tracks=faces,
        face_identities={
            "f1": {"student_id": "p01", "confidence": 0.9, "margin": 0.2},
            "f2": {"student_id": "p01", "confidence": 0.85, "margin": 0.2},
        },
    )
    s1 = eng.get_state("t1").student_id
    s2 = eng.get_state("t2").student_id
    # no máximo um track com p01
    assert [s1, s2].count("p01") <= 1


def test_margin_unavailable_not_invented():
    eng = IdentityBindingEngine(minimum_new_identity_confidence=0.75)
    persons = [_person("t1", (0, 0, 100, 200))]
    faces = [_face("f1", (20, 10, 40, 40))]
    # só student_id+conf — margem None
    eng.update_continuity(
        now=1.0,
        person_tracks=persons,
        face_tracks=faces,
        face_identities={"f1": {"student_id": "p01", "confidence": 0.76}},
    )
    st = eng.get_state("t1")
    assert st.margin is None
    # conf 0.76 < 0.75+0.05 → pode não bindar
    # com 0.85 deve bindar
    eng2 = IdentityBindingEngine(minimum_new_identity_confidence=0.75)
    eng2.update_continuity(
        now=1.0,
        person_tracks=persons,
        face_tracks=faces,
        face_identities={"f1": {"student_id": "p01", "confidence": 0.85}},
    )
    assert eng2.get_state("t1").student_id == "p01"
    assert eng2.get_state("t1").margin is None


def test_phone_ambiguous_between_two_people():
    assoc = PersonPhoneAssociator(minimum_interaction_seconds=1.0, probable_seconds=3.0)
    people = {
        "p1": (0.0, 0.0, 100.0, 200.0),
        "p2": (80.0, 0.0, 100.0, 200.0),
    }
    # celular no meio
    phones = [(70.0, 80.0, 20.0, 40.0, 0.9)]
    states = assoc.update(now=0.0, person_tracks=people, phone_boxes=phones)
    # não deve gerar interaction confirmada; ambíguo ou visible
    for s in states:
        assert "confirmed" not in s.interaction_level
        if s.ambiguous:
            assert s.interaction_level in ("phone_visible", "not_detected")


def test_phone_visible_not_use():
    assoc = PersonPhoneAssociator()
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(300.0, 300.0, 20.0, 40.0, 0.9)]  # longe
    s = assoc.update(now=0.0, person_tracks=people, phone_boxes=phones)[0]
    assert s.interaction_level in ("phone_visible", "not_detected")
    assert "confirmed" not in s.interaction_level


def test_head_down_not_auto_drowsiness():
    eng = RealtimeAnalyticsEngine(_FakeSettings())
    cache = eng._get_cache("t1")
    cache.observation_quality = {
        "overall_score": 0.8,
        "overall_observability": 0.8,
        "status": "partially_observable",
        "reasons": ["head_down"],
    }
    cache.facial_features = {
        "status": "available",
        "average_eye_openness": 0.5,  # olhos abertos
        "yaw": 0.0,
        "pitch": 0.5,
    }
    cache.head_state = {"state": "head_down_persistent", "confidence": 0.8, "reasons": []}
    cache.face_occlusion = {"state": "none"}
    attn, drow = eng._compute_attention_drowsiness(cache, 1000.0, face_visible=True)
    assert drow["state"] in ("none", "inconclusive")
    assert drow["state"] not in ("possible", "probable")


def test_face_hidden_attention_inconclusive():
    eng = RealtimeAnalyticsEngine(_FakeSettings())
    cache = eng._get_cache("t1")
    cache.observation_quality = {
        "overall_score": 0.5,
        "overall_observability": 0.5,
        "status": "partially_observable",
        "reasons": ["face_not_visible"],
    }
    cache.facial_features = {"status": "inconclusive", "reason": "face_not_observable"}
    cache.head_state = {"state": "head_down_persistent", "confidence": 0.7}
    cache.face_occlusion = {"state": "none"}
    attn, drow = eng._compute_attention_drowsiness(cache, 1000.0, face_visible=False)
    assert attn["state"] == "inconclusive"
    assert drow["state"] == "inconclusive"


def test_two_people_crossing_no_identity_swap():
    eng = IdentityBindingEngine(
        face_missing_ttl_seconds=12.0,
        minimum_new_identity_confidence=0.75,
        confirmations_before_switch=3,
        identity_switch_cooldown_seconds=10.0,
    )
    # t1=p01 esquerda, t2=p12 direita
    p1 = _person("t1", (0, 0, 100, 200))
    p2 = _person("t2", (200, 0, 100, 200))
    f1 = _face("f1", (20, 10, 40, 40))
    f2 = _face("f2", (220, 10, 40, 40))
    eng.update_continuity(
        now=1.0,
        person_tracks=[p1, p2],
        face_tracks=[f1, f2],
        face_identities={
            "f1": {"student_id": "p01", "confidence": 0.9, "margin": 0.2},
            "f2": {"student_id": "p12", "confidence": 0.9, "margin": 0.2},
        },
    )
    assert eng.get_state("t1").student_id == "p01"
    assert eng.get_state("t2").student_id == "p12"
    # cruzam: faces trocam de lado por 1 frame (associação espacial)
    f1x = _face("f1", (220, 10, 40, 40))
    f2x = _face("f2", (20, 10, 40, 40))
    eng.update_continuity(
        now=2.0,
        person_tracks=[p1, p2],
        face_tracks=[f1x, f2x],
        face_identities={
            "f1": {"student_id": "p01", "confidence": 0.9, "margin": 0.2},
            "f2": {"student_id": "p12", "confidence": 0.9, "margin": 0.2},
        },
    )
    # sem 3 confirmações, identidades dos tracks não devem inverter imediatamente
    # (pode manter cached ou bloquear swap)
    s1 = eng.get_state("t1").student_id
    s2 = eng.get_state("t2").student_id
    # não ambos viram o outro no mesmo frame sem confirmações
    swapped_both = s1 == "p12" and s2 == "p01"
    assert not swapped_both


def test_engine_person_first_contract():
    eng = RealtimeAnalyticsEngine(_FakeSettings())
    big = np.zeros((480, 640, 3), dtype=np.uint8)
    big[80:280, 200:320] = 140
    persons = [_person("cam-web-person-001", (200, 80, 120, 200), cam="cam-web")]
    tracks = eng.process_camera(
        camera_id="cam-web",
        frame=big,
        matches=[{"student_id": "p01", "confidence": 0.85, "margin": 0.15, "full_name": "A"}],
        boxes=[(220, 90, 50, 50)],
        person_tracks=persons,
    )
    assert len(tracks) == 1
    t = tracks[0]
    assert t["person_track_id"] == "cam-web-person-001"
    assert "identity" in t
    assert "observation_quality" in t
    assert t["track_id"] == t["person_track_id"]  # alias
    assert t["bbox"] == t["person_bbox"]
    assert "person_visibility" in t["observation_quality"] or t["observation_quality"].get("status")


def test_engine_continues_without_face():
    eng = RealtimeAnalyticsEngine(_FakeSettings())
    big = np.zeros((480, 640, 3), dtype=np.uint8)
    persons = [_person("cam-web-person-001", (200, 80, 120, 200), cam="cam-web")]
    # primeiro com face
    eng.process_camera(
        camera_id="cam-web",
        frame=big,
        matches=[{"student_id": "p01", "confidence": 0.9, "margin": 0.2}],
        boxes=[(220, 90, 50, 50)],
        person_tracks=persons,
        now=100.0,
    )
    # sem face — track continua
    tracks = eng.process_camera(
        camera_id="cam-web",
        frame=big,
        matches=[],
        boxes=[],
        person_tracks=persons,
        now=101.0,
    )
    assert len(tracks) == 1
    assert tracks[0]["person_track_id"] == "cam-web-person-001"
    assert tracks[0]["identity"]["source"] in ("cached_binding", "face_recognition", "unknown")
    assert tracks[0]["visual_attention"]["state"] == "inconclusive" or tracks[0]["identity"][
        "face_visible"
    ] is False
