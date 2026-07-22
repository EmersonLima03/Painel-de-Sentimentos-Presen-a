"""Margem entre alunos distintos (multi-template)."""

from app.vision.matcher import competitor_margin_from_topk


def test_margin_ignores_same_student_templates():
    topk = [
        ("emerson", 0.95),
        ("emerson", 0.93),
        ("emerson", 0.91),
    ]
    margin, other_sim, other_id = competitor_margin_from_topk(topk)
    assert margin is None
    assert other_sim is None


def test_margin_uses_different_student():
    topk = [
        ("emerson", 0.90),
        ("emerson", 0.88),
        ("ester", 0.82),
    ]
    margin, other_sim, other_id = competitor_margin_from_topk(topk)
    assert abs(margin - 0.08) < 1e-6
    assert other_sim == 0.82
    assert other_id == "ester"
