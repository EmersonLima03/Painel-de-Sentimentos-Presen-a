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
                "identity": {},
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
