"""Testes do acumulador de sessão live para dashboard."""

from app.services.live_session import LiveSessionStore, dashboard_track_view


def test_dashboard_track_view_normalizes_analytics_track():
    raw = {
        "person_track_id": "cam-web-person-001",
        "full_name": "Emerson Lima",
        "student_id": "stu1",
        "identity": {"identity_state": "face_confirmed"},
        "visual_attention": {"state": "high", "confidence": 0.8},
        "expression": {
            "status": "available",
            "smoothed_state": "predominantly_positive",
            "smoothed_display_pt": "expressão predominantemente positiva",
        },
        "observation_quality": {"status": "observable", "overall_score": 0.9},
        "phone": {"state": "not_detected"},
        "drowsiness": {"state": "none"},
        "active_events": [],
    }
    v = dashboard_track_view(raw)
    assert v["attention_state"] == "high"
    assert v["expression_window"] == "predominantly_positive"
    assert v["full_name"] == "Emerson Lima"


def test_live_session_accumulates_climate_samples():
    store = LiveSessionStore()
    store.last_sample_at = 0.0
    state = {
        "tracks": [
            {
                "person_track_id": "p1",
                "student_id": "stu-a",
                "full_name": "A",
                "visual_attention": {"state": "high"},
                "expression": {"status": "available", "smoothed_state": "predominantly_positive"},
                "observation_quality": {"status": "observable"},
                "phone": {},
                "drowsiness": {},
                "identity": {"face_visible": True, "identity_state": "face_confirmed"},
                "face_bbox": [10, 10, 40, 40],
                "track_confidence": 0.9,
                "tracking_state": "active",
            }
        ],
        "visible_people": 1,
        "observable_people": 1,
        "apparent_climate": "predominantly_positive",
        "classroom_counts": {"climate_distribution": {"predominantly_positive": 1}},
        "live_event_buffer": [],
    }
    store.ingest_live_state(state)
    students = store.students_list()
    assert len(students) == 1
    assert students[0]["student_id"] == "stu-a"
    assert students[0]["attention_label_pt"]
    assert store.climate_samples


def test_bind_session_id_clears_prior_session_accumulators():
    """Troca de aula não deve vazar clima/eventos da sessão anterior."""
    store = LiveSessionStore()
    store.bind_session_id("sess-old", started_at=1000.0)
    store.climate_samples.append({"t": 1.0, "apparent_climate": "predominantly_positive"})
    store.timeline.append({"t": 1.0, "type": "event_opened", "label": "possible_phone_interaction"})
    store.events_seen["ev-old"] = {
        "event_id": "ev-old",
        "event_type": "possible_phone_interaction",
        "session_id": "sess-old",
    }
    store.display_smoothing["student:p01"] = {"last_stable_expression": "predominantly_neutral"}

    store.bind_session_id("sess-new", started_at=2000.0)

    assert store.session_id == "sess-new"
    assert store.climate_samples == []
    assert store.timeline == []
    assert store.events_seen == {}
    assert store.display_smoothing == {}


def test_build_report_uses_aggregator_kpis():
    store = LiveSessionStore()
    store.ingest_live_state(
        {
            "tracks": [
                {
                    "person_track_id": "p1",
                    "student_id": "stu1",
                    "full_name": "Emerson",
                    "visual_attention": {"state": "high"},
                    "expression": {"smoothed_state": "predominantly_positive"},
                    "observation_quality": {"status": "observable"},
                    "identity": {},
                }
            ],
            "visible_people": 1,
            "observable_people": 1,
            "attention_index": 0.8,
            "apparent_climate": "predominantly_positive",
            "live_event_buffer": [],
        }
    )
    report = store.build_report({"attention_index": 0.8, "apparent_climate": "predominantly_positive"})
    assert report["students_count"] == len(report["students"])
    assert report["attention_label_pt"]
    assert "alta" in report["attention_label_pt"].lower()
