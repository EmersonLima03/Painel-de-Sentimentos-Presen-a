# Fix phone YOLO — IndentationError (2026-09-17)

## Sintoma

No LIVE com XWF, rosto / cabeça baixa / olhos ok; **celular sempre `not_detected`** (sem bbox magenta), mesmo com aparelho bem visível na mão.

## Causa

Em `app/vision/phone_yolo.py`, dentro de `_roi_pass`, o `continue` do

`if _person_has_nearby_phone(out, pb):`

foi desindentado por acidente (working tree local). Isso gerava **IndentationError** na importação do módulo.

O analytics engolia a falha (`dependency_or_model_missing` / status error) e seguia com `not_detected`. O log `YOLOv8n summary` vinha do **person** tracker, não do phone YOLO.

## Correção

Restaurar a indentação do `continue` (conteúdo = HEAD válido em `tri/congelado-baseline-validado`).

## Blindagem

- Teste: `tests/test_phone_yolo_module_guard.py`
  - `ast.parse` do ficheiro
  - import de `detect_phones` / `get_phone_detector_debug`
  - AST: o `if _person_has_nearby_phone` tem `continue` no corpo
- Revalidação LIVE pós-fix: estado `phone_near_person` + overlay “Celular visível”.

## Não confundir

- Não alterar thresholds T5 / `config.tri.yaml` neste fix.
- Não misturar com Fase 1 do dashboard frontend.
