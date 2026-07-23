"""Testes do módulo de sinais / clima / taxonomia."""

from app.vision.behavioral_taxonomy import (
    DISCLAIMER_PT,
    ClimateBucket,
    LEGACY_STATE_TO_OBSERVABLE,
    ObservableSignal,
    label_pt,
)
from app.pipeline.temporal_aggregator import TemporalSignalAggregator
from app.vision.facial_signals import FacialSignalSample


def test_taxonomy_labels():
    assert "diagnóstico" in DISCLAIMER_PT.lower() or "Estimativa" in DISCLAIMER_PT
    assert label_pt(ObservableSignal.POSSIBLE_DROWSINESS.value)
    assert "Distraido" not in label_pt(LEGACY_STATE_TO_OBSERVABLE["distracted"])
    assert ClimateBucket.POSITIVE_APPARENT.value == "positive_apparent"


def test_temporal_aggregator_out_of_field():
    agg = TemporalSignalAggregator(out_of_field_seconds=1.0, track_ttl_seconds=2.0)
    t0 = 1000.0
    sample = FacialSignalSample(
        yaw=0.0, pitch=0.1, ear=0.3, mouth_aspect=0.1,
        orientation=ObservableSignal.ORIENTATION_FORWARD.value,
        eyes_closed=False, possible_yawn=False, confidence=0.8,
        observation_quality="good", label_pt="ok",
    )
    agg.update_track("t1", sample, now=t0)
    agg.update_track("t1", None, now=t0 + 0.5)
    events = agg.poll_events(now=t0 + 0.6)
    assert not any(e.event_type == ObservableSignal.OUT_OF_FIELD.value for e in events)
    events = agg.poll_events(now=t0 + 2.0)
    assert any(e.event_type == ObservableSignal.OUT_OF_FIELD.value for e in events)


def test_temporal_aggregator_drowsiness_needs_combo():
    agg = TemporalSignalAggregator(
        eyes_closed_seconds=2.0,
        drowsiness_combo_seconds=3.0,
        min_confidence=0.5,
    )
    t0 = 2000.0
    for i in range(10):
        s = FacialSignalSample(
            yaw=0.0, pitch=0.5, ear=0.1, mouth_aspect=0.2,
            orientation=ObservableSignal.EYES_CLOSED_PERSISTENT.value,
            eyes_closed=True, possible_yawn=(i == 5), confidence=0.8,
            observation_quality="good", label_pt="x",
        )
        agg.update_track("t2", s, now=t0 + i * 0.5)
    events = agg.poll_events(now=t0 + 5.0)
    types = {e.event_type for e in events}
    assert ObservableSignal.POSSIBLE_DROWSINESS.value in types or ObservableSignal.EYES_CLOSED_PERSISTENT.value in types


def test_climate_bucket_mapping():
    from app.pipeline.climate import _bucket_from_sample

    s = FacialSignalSample(
        yaw=0.0, pitch=0.1, ear=0.3, mouth_aspect=0.1,
        orientation=ObservableSignal.ORIENTATION_FORWARD.value,
        eyes_closed=False, possible_yawn=False, confidence=0.8,
        observation_quality="good", label_pt="ok",
    )
    assert _bucket_from_sample(s) == ClimateBucket.POSITIVE_APPARENT.value
    assert _bucket_from_sample(s, "sad") == ClimateBucket.NEGATIVE_APPARENT.value
