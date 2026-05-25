"""Testes de geração de eventos."""

import json
import pytest
from app.utils.ids import generate_event_id
from app.utils.time import get_date_key


def test_event_id_generation():
    """Testa geração de event_id."""
    event_id = generate_event_id()
    assert event_id is not None
    assert len(event_id) > 0
    assert isinstance(event_id, str)


def test_attendance_event_structure():
    """Testa estrutura de evento de presença."""
    event = {
        "event_id": generate_event_id(),
        "event_type": "attendance_checkin",
        "student_id": "12345",
        "school_id": "1",
        "room_id": "A01",
        "device_id": "edge-001",
        "timestamp": 1739400000,
        "confidence": 0.82,
        "model_version": "emb-v1",
        "template_version": "tpl-v1",
        "face_quality": "good"
    }
    
    # Validar JSON
    event_json = json.dumps(event)
    parsed = json.loads(event_json)
    
    assert parsed["event_type"] == "attendance_checkin"
    assert "event_id" in parsed
    assert "student_id" in parsed
    assert "confidence" in parsed


def test_engagement_event_structure():
    """Testa estrutura de evento de engajamento."""
    event = {
        "event_id": generate_event_id(),
        "event_type": "engagement_window",
        "school_id": "1",
        "room_id": "A01",
        "device_id": "edge-001",
        "ts_start": 1739400000,
        "ts_end": 1739400010,
        "faces_detected_avg": 22.0,
        "engagement_index_avg": 0.63,
        "states_distribution": {
            "attentive": 0.55,
            "neutral": 0.35,
            "distracted": 0.10
        },
        "model_version": "eng-v0"
    }
    
    # Validar JSON
    event_json = json.dumps(event)
    parsed = json.loads(event_json)
    
    assert parsed["event_type"] == "engagement_window"
    assert "event_id" in parsed
    assert "states_distribution" in parsed
    assert parsed["states_distribution"]["attentive"] == 0.55


def test_date_key():
    """Testa geração de date_key."""
    date_key = get_date_key()
    assert date_key is not None
    assert len(date_key) == 10  # YYYY-MM-DD
    assert date_key.count("-") == 2
