"""Guarda anti-regressão: phone_yolo deve importar e ter sintaxe válida.

Incidente 2026-09-17: `continue` desindentado em `_roi_pass` → IndentationError.
O módulo deixava de carregar; o pipeline engolia o erro e o celular ficava
sempre `not_detected`, enquanto rosto/cabeça/olhos seguiam ok.
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_phone_yolo_source_parses():
    path = Path(__file__).resolve().parents[1] / "app" / "vision" / "phone_yolo.py"
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))


def test_phone_yolo_detect_phones_importable():
    from app.vision.phone_yolo import detect_phones, get_phone_detector_debug

    assert callable(detect_phones)
    dbg = get_phone_detector_debug()
    assert isinstance(dbg, dict)
    assert dbg.get("provider") == "yolo"


def test_roi_pass_nearby_phone_guard_has_continue_body():
    """Garante que o `if _person_has_nearby_phone(...):` não ficou com corpo vazio."""
    path = Path(__file__).resolve().parents[1] / "app" / "vision" / "phone_yolo.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Call):
            continue
        func = test.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "_person_has_nearby_phone":
            continue
        assert node.body, "if _person_has_nearby_phone sem corpo (IndentationError latente)"
        assert any(isinstance(stmt, ast.Continue) for stmt in node.body), (
            "if _person_has_nearby_phone deve ter `continue` no corpo"
        )
        found = True

    assert found, "não achou if _person_has_nearby_phone em phone_yolo.py"
