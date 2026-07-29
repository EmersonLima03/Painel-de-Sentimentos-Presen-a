"""Digitação / cabeça baixa não deve alimentar sonolência via EAR falso (cenário F)."""

from app.analytics.attention_drowsiness import evaluate_apparent_drowsiness


def test_brief_closed_not_event():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=2.0,
        head_pitch=0.1,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state == "none"


def test_possible_at_6s_frontal():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=6.0,
        head_pitch=0.05,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state == "possible"


def test_probable_at_30s_frontal():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=30.0,
        head_pitch=0.05,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state == "probable"


def test_boundary_just_below_possible():
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=5.99,
        head_pitch=0.0,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state in ("none", "inconclusive")


def test_head_down_pitch_alone_does_not_make_probable_without_eyes_duration():
    """Cabeça baixa sem duração de olhos fechados válidos ≠ sono."""
    st = evaluate_apparent_drowsiness(
        eyes_closed_seconds=1.0,
        head_pitch=0.6,
        head_supported=True,
        sample_count=10,
        observation_quality=0.9,
        possible_after_seconds=6.0,
        min_duration_seconds=30.0,
    )
    assert st.state == "none"
