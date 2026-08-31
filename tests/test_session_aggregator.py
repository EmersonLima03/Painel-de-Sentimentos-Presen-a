"""Testes do SessionAggregator — merge identidade, episódios e filtros C1/C4."""

from app.services.session_aggregator import SessionAggregator


def _track(
    *,
    tid: str,
    sid: str | None = None,
    name: str = "Aluno",
    attn: str = "high",
    expr: str = "predominantly_positive",
    quality: str = "observable",
):
    return {
        "person_track_id": tid,
        "student_id": sid,
        "full_name": name,
        "identity": {"student_id": sid, "full_name": name} if sid else {},
        "visual_attention": {"state": attn},
        "expression": {"status": "available", "smoothed_state": expr},
        "observation_quality": {"status": quality},
    }


def test_expression_predominantly_neutral_seconds_accumulate():
    """Relatório não fica zerado quando o live publica predominantly_neutral."""
    agg = SessionAggregator()
    for _ in range(8):
        agg.ingest_live_state(
            {
                "tracks": [
                    _track(
                        tid="p1",
                        sid="stu1",
                        name="Emerson Lima",
                        expr="predominantly_neutral",
                        quality="observable",
                    )
                ],
                "live_event_buffer": [],
            },
            visible_count=1,
        )
    result = agg.aggregate_session(
        climate_samples=[],
        events_seen={},
        duration_seconds=60,
        current_state={},
    )
    profile = result["observation_profile"]
    assert profile["expression_neutral_seconds"] > 0
    assert profile["expression_positive_seconds"] == 0
    assert "neutra" in (result.get("expression_label_pt") or "").lower()


def test_expression_inconclusive_does_not_fill_emotion_buckets():
    agg = SessionAggregator()
    for _ in range(5):
        agg.ingest_live_state(
            {
                "tracks": [
                    _track(
                        tid="p1",
                        sid="stu1",
                        expr="inconclusive",
                        quality="inconclusive",
                        attn="inconclusive",
                    )
                ],
                "live_event_buffer": [],
            },
            visible_count=1,
        )
    students = agg.report_students()
    profile = students[0]["observation_profile"]
    assert profile["expression_positive_seconds"] == 0
    assert profile["expression_neutral_seconds"] == 0
    assert profile["expression_negative_seconds"] == 0
    assert profile["inconclusive_seconds"] > 0



def test_exclude_unidentified_short_presence_c1():
    agg = SessionAggregator()
    agg.ingest_live_state({"tracks": [_track(tid="ghost", sid=None, name="Pessoa não identificada")], "live_event_buffer": []}, visible_count=1)
    assert agg.report_students() == []


def test_keep_identified_zero_observable_c1():
    agg = SessionAggregator()
    for _ in range(5):
        agg.ingest_live_state(
            {
                "tracks": [_track(tid="p1", sid="stu1", name="Emerson Lima", quality="inconclusive", attn="inconclusive", expr="inconclusive")],
                "live_event_buffer": [],
            },
            visible_count=1,
        )
    students = agg.report_students()
    assert len(students) == 1
    assert students[0]["observable_pct"] == 0
    assert students[0]["observability_note_pt"]


def test_dominant_attention_by_duration_c4():
    agg = SessionAggregator()
    for _ in range(10):
        agg.ingest_live_state(
            {"tracks": [_track(tid="p1", sid="stu1", attn="high")], "live_event_buffer": []},
            visible_count=1,
        )
    for _ in range(2):
        agg.ingest_live_state(
            {"tracks": [_track(tid="p1", sid="stu1", attn="low")], "live_event_buffer": []},
            visible_count=1,
        )
    students = agg.report_students()
    assert students[0]["attention_level"] == "high"
    assert "alta" in students[0]["attention_label_pt"].lower()


def test_insufficient_data_when_mostly_inconclusive_c4():
    agg = SessionAggregator()
    for _ in range(20):
        agg.ingest_live_state(
            {
                "tracks": [_track(tid="p1", sid="stu1", attn="inconclusive", expr="inconclusive", quality="inconclusive")],
                "live_event_buffer": [],
            },
            visible_count=1,
        )
    students = agg.report_students()
    assert students[0]["insufficient_data"] is True
    assert "Sem dado suficiente" in students[0]["attention_label_pt"]


def test_event_duration_rollup():
    agg = SessionAggregator()
    # Cria pessoa via track sample para aparecer no relatório
    for _ in range(5):
        agg.ingest_live_state(
            {"tracks": [_track(tid="p1", sid="stu1", name="Emerson")], "live_event_buffer": []},
            visible_count=1,
        )
    events = {
        "ev1": {
            "event_id": "ev1",
            "event_type": "probable_drowsiness",
            "person_track_id": "p1",
            "student_id": "stu1",
            "lifecycle": "closed",
            "duration_seconds": 120.0,
            "ended_at": 1000.0,
        },
        "ev2": {
            "event_id": "ev2",
            "event_type": "probable_drowsiness",
            "person_track_id": "p1",
            "student_id": "stu1",
            "lifecycle": "closed",
            "duration_seconds": 60.0,
            "ended_at": 2000.0,
        },
        "ev3": {
            "event_id": "ev3",
            "event_type": "probable_phone_interaction",
            "person_track_id": "p1",
            "student_id": "stu1",
            "lifecycle": "closed",
            "duration_seconds": 90.0,
            "ended_at": 2500.0,
        },
    }
    result = agg.aggregate_session(
        climate_samples=[],
        events_seen=events,
        duration_seconds=900,
        current_state={},
    )
    student = result["students"][0]
    assert student["signals"]
    eyes = next(s for s in student["signals"] if s["signal_key"] == "probable_drowsiness")
    assert eyes["total_seconds"] == 180.0
    assert eyes["occurrence_count"] == 2
    cats = {c["category_id"]: c for c in student["time_by_category"]}
    assert cats["eyes"]["total_seconds"] == 180.0
    assert cats["phone"]["total_seconds"] == 90.0
    class_cats = {c["category_id"]: c for c in result["time_by_category"]}
    assert class_cats["eyes"]["total_seconds"] == 180.0
    assert class_cats["phone"]["total_seconds"] == 90.0


def test_updated_then_closed_does_not_double_count():
    agg = SessionAggregator()
    agg.ingest_event(
        {
            "event_id": "ev1",
            "event_type": "head_down_persistent",
            "person_track_id": "p1",
            "student_id": "stu1",
            "lifecycle": "updated",
            "duration_seconds": 40.0,
            "updated_at": 100.0,
        },
        now=100.0,
    )
    agg.ingest_event(
        {
            "event_id": "ev1",
            "event_type": "head_down_persistent",
            "person_track_id": "p1",
            "student_id": "stu1",
            "lifecycle": "closed",
            "duration_seconds": 55.0,
            "ended_at": 155.0,
        },
        now=155.0,
    )
    rec = agg.persons["student:stu1"]
    assert rec.signals["head_down_persistent"].total_seconds == 55.0
    assert rec.signals["head_down_persistent"].occurrence_count == 1


def test_aggregate_session_kpis_c5():
    agg = SessionAggregator()
    agg.peak_visible = 3
    agg.ingest_live_state({"tracks": [_track(tid="p1", sid="stu1")], "live_event_buffer": []}, visible_count=2)
    result = agg.aggregate_session(
        climate_samples=[{"observable_pct": 80, "apparent_climate": "predominantly_positive", "t": 15}],
        events_seen={},
        duration_seconds=900,
        current_state={"attention_index": 0.72, "apparent_climate": "predominantly_positive", "visible_people": 2},
    )
    assert result["peak_visible"] == 3
    assert result["students_count"] == 1
    assert result["attention_label_pt"]
    assert result["class_summary"]["attention_level"] == "high"


def test_eye_flicker_episodes_merge_to_few_occurrences():
    """Piscadas / possible→probable próximos não viram 9 episódios pedagógicos."""
    agg = SessionAggregator()
    for _ in range(5):
        agg.ingest_live_state(
            {"tracks": [_track(tid="p1", sid="stu1", name="Emerson")], "live_event_buffer": []},
            visible_count=1,
        )
    # 9 “episódios” técnicos em ~2 min, gaps curtos (flicker)
    events = {}
    t0 = 1000.0
    for i in range(9):
        start = t0 + i * 12.0
        events[f"ev{i}"] = {
            "event_id": f"ev{i}",
            "event_type": "possible_drowsiness" if i % 2 == 0 else "probable_drowsiness",
            "person_track_id": "p1",
            "student_id": "stu1",
            "lifecycle": "closed",
            "duration_seconds": 8.0,
            "started_at": start,
            "ended_at": start + 8.0,
        }
    result = agg.aggregate_session(
        climate_samples=[],
        events_seen=events,
        duration_seconds=900,
        current_state={},
    )
    student = result["students"][0]
    cats = {c["category_id"]: c for c in student["time_by_category"]}
    assert cats["eyes"]["total_seconds"] == 72.0
    # Um bloco contínuo (gaps 4s) → 1 ocorrência pedagógica
    assert cats["eyes"]["occurrence_count"] == 1


def test_distant_eye_episodes_remain_separate():
    agg = SessionAggregator()
    for _ in range(5):
        agg.ingest_live_state(
            {"tracks": [_track(tid="p1", sid="stu1", name="Emerson")], "live_event_buffer": []},
            visible_count=1,
        )
    events = {
        "a": {
            "event_id": "a",
            "event_type": "probable_drowsiness",
            "person_track_id": "p1",
            "student_id": "stu1",
            "lifecycle": "closed",
            "duration_seconds": 30.0,
            "started_at": 1000.0,
            "ended_at": 1030.0,
        },
        "b": {
            "event_id": "b",
            "event_type": "probable_drowsiness",
            "person_track_id": "p1",
            "student_id": "stu1",
            "lifecycle": "closed",
            "duration_seconds": 40.0,
            "started_at": 2000.0,
            "ended_at": 2040.0,
        },
    }
    result = agg.aggregate_session(
        climate_samples=[],
        events_seen=events,
        duration_seconds=900,
        current_state={},
    )
    cats = {c["category_id"]: c for c in result["students"][0]["time_by_category"]}
    assert cats["eyes"]["occurrence_count"] == 2
    assert cats["eyes"]["total_seconds"] == 70.0
