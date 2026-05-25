"""Testes de schema de eventos."""

import json
import pytest
from app.utils.ids import generate_event_id


def test_attendance_checkin_schema():
    """Valida schema de evento attendance_checkin."""
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
    
    # Validar campos obrigatórios
    assert "event_id" in event
    assert "event_type" in event
    assert event["event_type"] == "attendance_checkin"
    assert "student_id" in event
    assert "confidence" in event
    assert isinstance(event["confidence"], (int, float))
    assert 0.0 <= event["confidence"] <= 1.0
    
    # Validar JSON serializável
    event_json = json.dumps(event)
    parsed = json.loads(event_json)
    assert parsed["event_type"] == "attendance_checkin"


def test_engagement_window_schema():
    """Valida schema de evento engagement_window."""
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
    
    # Validar campos obrigatórios
    assert "event_id" in event
    assert "event_type" in event
    assert event["event_type"] == "engagement_window"
    assert "states_distribution" in event
    assert "engagement_index_avg" in event
    
    # Validar distribuição soma ~1.0
    dist = event["states_distribution"]
    total = dist["attentive"] + dist["neutral"] + dist["distracted"]
    assert abs(total - 1.0) < 0.01  # Tolerância para arredondamento
    
    # Validar JSON serializável
    event_json = json.dumps(event)
    parsed = json.loads(event_json)
    assert parsed["event_type"] == "engagement_window"


def test_event_id_uniqueness():
    """Valida que event_id é único."""
    ids = [generate_event_id() for _ in range(100)]
    assert len(ids) == len(set(ids))  # Todos únicos
