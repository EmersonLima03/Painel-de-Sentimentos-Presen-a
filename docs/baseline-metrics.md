# Baseline metrics — Fase 0

**Data:** 2026-07-23  
**Tag prevista:** `baseline-fase-0`  
**Python:** 3.12.9  
**Ambiente:** `venv/` (core)

## Testes automatizados

```
pytest tests -q
```

| Resultado | Contagem |
|-----------|----------|
| Passed | 32 |
| Failed | 1 |
| Warnings | 78 (Pydantic `Field(env=...)` deprecation; `datetime.utcnow`) |

### Falha registrada (pré-existente)

- `tests/test_dedup_presence.py::test_dedup_different_days`
- **Não corrigida na Fase 0** (congelamento de comportamento).
- Impacto: dedup entre dias; não bloqueia presença no mesmo dia/sessão.

### Tolerâncias de regressão (paridade Fase 1+)

| Área | Tolerância |
|------|------------|
| Testes de presença/matching (`test_competitor_margin`, demais dedup) | 0 novas falhas além da falha baseline acima |
| `test_behavioral_module`, `test_queue`, `test_events*` | todos PASS |
| Latência ciclo presença (quando medida em hardware) | p95 ≤ baseline_hardware + 15% |
| FPS captura alvo | 20 Hz ± 2 Hz (quando stream saudável) |
| Duplicação de presença (mesma chave dedup) | **0** |

## Intervalos do orquestrador (código)

| Loop | Valor |
|------|-------|
| Captura (`_CAPTURE_HZ`) | 20.0 |
| Overlay detect+recognize (`_DETECT_HZ`) | 6.0 |
| Presença | `presence.sampling_seconds` = **2** |
| Engajamento / behavioral / climate tick | `engagement.sampling_seconds` = **3** |

## Flags / módulos atuais

| Módulo | Estado baseline |
|--------|-----------------|
| Detector | `yunet` |
| Embedder | `facenet` |
| Engagement backend | `head_pose` |
| `climate.use_fer` | `false` |
| `behavioral.enabled` | `true` |
| `phone_yolo.enabled` | `false` |
| Câmera ativa | `cam-vip-5440-01` (RTSP) |

## Hardware / runtime (a completar no spike 0.5)

| Métrica | Valor baseline Fase 0 |
|---------|------------------------|
| CPU média sessão | *não medida — registrar no spike* |
| Memória pico processo | *não medida — registrar no spike* |
| Latência presença p50/p95 | *não medida — registrar no spike* |
| Filas / dropped frames | N/A (sem FrameScheduler ainda) |

## Provenance defaults (congelados para docs)

| Campo | Valor inicial |
|-------|----------------|
| `rule_engine_version` | `rules-v0-baseline` |
| `threshold_profile` | `presence-yaml-2026-07-23` |
| `camera_calibration_version` | `cam-vip-5440-01-uncalibrated` |
