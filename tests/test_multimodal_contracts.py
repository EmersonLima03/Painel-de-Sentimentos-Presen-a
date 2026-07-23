"""Testes de modos, normalização, binding, phone, fusão, LXP, qualidade."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from app.module_modes import ModuleMode, assert_max_shadow_after_spike, parse_module_mode
from app.vision.expressions.normalization import normalize_expression_label, normalize_probabilities, pick_label
from app.vision.expressions.mock_provider import MockExpressionProvider
from app.vision.identity_binding import IdentityBindingEngine
from app.vision.tracking_types import FaceTrack, PersonTrack
from app.vision.person_phone import PersonPhoneAssociator
from app.vision.observation_quality import engagement_state_from_scores, compute_observation_quality
from app.analytics.fusion import FusionEngine
from app.integrations.lxp import LXPEvent, MockLXPClient, LXPOutbox, new_event_id
from app.vision.domain import Provenance


def test_parse_module_modes():
    assert parse_module_mode("debug") == ModuleMode.DEBUG
    assert parse_module_mode("SHADOW") == ModuleMode.SHADOW
    with pytest.raises(ValueError):
        parse_module_mode("on")


def test_no_direct_production_after_spike():
    with pytest.raises(ValueError):
        assert_max_shadow_after_spike(ModuleMode.PRODUCTION)
    assert_max_shadow_after_spike(ModuleMode.SHADOW)


def test_normalize_expression():
    assert normalize_expression_label("Happy") == "positive"
    assert normalize_expression_label("sad") == "negative"
    probs = normalize_probabilities({"happy": 0.6, "sad": 0.4})
    assert abs(sum(probs.values()) - 1.0) < 1e-6
    label, conf, ok = pick_label({"positive": 0.9}, minimum_confidence=0.6)
    assert label == "positive" and ok
    label2, _, ok2 = pick_label({"positive": 0.2}, minimum_confidence=0.6)
    assert label2 == "inconclusive" and not ok2


def test_mock_provider_deterministic():
    p = MockExpressionProvider()
    bright = np.ones((64, 64, 3), dtype=np.uint8) * 200
    dark = np.ones((64, 64, 3), dtype=np.uint8) * 20
    a = p.predict_batch([bright])[0]
    b = p.predict_batch([dark])[0]
    assert a.label in ("positive", "neutral", "negative", "surprise", "inconclusive")
    assert a.provider == "mock"


def test_identity_binding_not_iou_only():
    now = datetime.now(timezone.utc)
    persons = [
        PersonTrack("p1", "cam", now, now, (0, 0, 100, 200), observation_quality=0.9),
        PersonTrack("p2", "cam", now, now, (200, 0, 100, 200), observation_quality=0.9),
    ]
    faces = [
        FaceTrack("f1", "cam", now, now, (20, 10, 40, 40), observation_quality=0.9),
        FaceTrack("f2", "cam", now, now, (220, 10, 40, 40), observation_quality=0.9),
    ]
    eng = IdentityBindingEngine()
    r1 = eng.bind(persons, faces)
    r2 = eng.bind(persons, faces)
    assert any(x.face_track_id for x in r1)
    assert any("temporal_pair_count" in " ".join(x.reasons) for x in r2)


def test_phone_never_confirmed():
    assoc = PersonPhoneAssociator(minimum_interaction_seconds=1.0, probable_seconds=3.0)
    people = {"p1": (0.0, 0.0, 100.0, 200.0)}
    phones = [(40.0, 80.0, 20.0, 40.0, 0.9)]
    s1 = assoc.update(now=0.0, person_tracks=people, phone_boxes=phones)[0]
    s2 = assoc.update(now=2.0, person_tracks=people, phone_boxes=phones)[0]
    s3 = assoc.update(now=5.0, person_tracks=people, phone_boxes=phones)[0]
    assert s2.interaction_level in (
        "none",
        "phone_visible",
        "phone_near_person",
        "possible_phone_interaction",
        "probable_phone_interaction",
    )
    assert s3.interaction_level in ("possible_phone_interaction", "probable_phone_interaction", "phone_near_person")
    assert "confirmed" not in s1.interaction_level
    assert "confirmed" not in s3.interaction_level


def test_low_quality_not_low_engagement():
    state, reasons = engagement_state_from_scores(
        visual_attention=0.1, observation_quality=0.2, min_quality=0.55
    )
    assert state == "inconclusive"
    assert "insufficient_observation_quality" in reasons


def test_observation_quality_empty():
    q = compute_observation_quality(None)
    assert q.overall_score == 0.0
    assert "face_not_visible" in q.reasons


def test_fusion_phone_and_provenance():
    eng = FusionEngine(Provenance(provider="test", model_name="m", model_version="1"))
    ev = eng.interpret_phone("probable_phone_interaction", 0.8, 0.7, "t1")
    assert ev is not None
    assert ev.severity == "probable"
    d = eng.to_shadow_dict(ev)
    assert d["auto_confirmed"] is False
    assert d["provider"] == "test"
    assert d["review_status"] == "pending"


def test_lxp_mock_idempotent(tmp_path):
    import asyncio

    client = MockLXPClient()
    eid = new_event_id()
    ev = LXPEvent("attendance_checkin", eid, "s1", {"student_id": "a"})

    async def run():
        r1 = await client.send_event(ev)
        r2 = await client.send_event(ev)
        assert r1.status == "sent"
        assert r2.status == "duplicate"

    asyncio.run(run())

    outbox = LXPOutbox(str(tmp_path / "out.jsonl"))
    assert outbox.enqueue(ev) is True
    assert outbox.enqueue(ev) is False
