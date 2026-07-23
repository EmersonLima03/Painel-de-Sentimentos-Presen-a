# Entrega Fase 0 — Baseline

**Data:** 2026-07-23  
**Status:** CONCLUÍDA  
**Gate 0 → 0.5:** PASS (documentação/artefatos). **Não iniciar 0.5 sem autorização explícita.**

## 1. Testes executados e resultados

```powershell
.\venv\Scripts\Activate.ps1
pytest tests -q
```

- **32 passed**
- **1 failed:** `tests/test_dedup_presence.py::test_dedup_different_days` (pré-existente; documentado; não corrigido na Fase 0)
- Warnings: Pydantic Field(env) deprecation; datetime.utcnow

## 2. Métricas do baseline

Ver [baseline-metrics.md](baseline-metrics.md). Tolerâncias de paridade registradas. Métricas de hardware (CPU/mem/latência RTSP) ficam para o spike.

## 3. Versões das dependências

Ver [dependencies-baseline.md](dependencies-baseline.md).

## 4. Thresholds congelados

Ver [thresholds-frozen.md](thresholds-frozen.md). Perfil: `presence-yaml-2026-07-23`.

## 5. Arquivos criados ou alterados

**Criados:**

- `docs/architecture.md`
- `docs/vision-pipeline.md`
- `docs/baseline-metrics.md`
- `docs/gates.md`
- `docs/thresholds-frozen.md`
- `docs/dependencies-baseline.md`
- `docs/spike-data-readme.md`
- `docs/FASE0_ENTREGA.md` (este arquivo)
- `data/spike/README.md`
- `requirements-spike-hsemotion.txt`
- `requirements-spike-deepface.txt`

**Alterados:**

- `.gitignore` (spike/validation_dataset/venvs isolados)

## 6. Commit / tag de baseline

Após commit: tag `baseline-fase-0`.

## 7. Resultado do gate 0 → 0.5

| Item | Status |
|------|--------|
| Docs architecture / pipeline / baseline / gates / thresholds / deps | OK |
| Thresholds de presença congelados | OK |
| Pasta `data/spike` + gitignore | OK |
| Testes registrados | OK (1 falha pré-existente documentada) |
| Commit/tag | a aplicar nesta entrega |
| Autorização para executar 0.5 | **PENDENTE (usuário)** |

**Gate documental: PASS.** Execução da Fase 0.5: **bloqueada até autorização explícita.**

## 8. Comandos exatos para iniciar o spike (após autorização)

```powershell
cd "c:\Users\dulin\OneDrive\Documentos\Teste de monitoramento\Presenca"
.\venv\Scripts\Activate.ps1

# Captura configurável (exemplos)
python scripts/spike_capture_intelbras.py --camera cam-vip-5440-01 --duration-seconds 120 --sample-fps 2 --corpus expression_samples --out data/spike/session_$(Get-Date -Format yyyyMMdd)/
python scripts/spike_capture_intelbras.py --camera cam-vip-5440-01 --duration-seconds 60 --sample-fps 10 --corpus tracking_clips --out data/spike/session_$(Get-Date -Format yyyyMMdd)/
python scripts/spike_capture_intelbras.py --camera cam-vip-5440-01 --duration-seconds 90 --sample-fps 5 --corpus phone_scenarios --out data/spike/session_$(Get-Date -Format yyyyMMdd)/
python scripts/spike_capture_intelbras.py --camera cam-vip-5440-01 --duration-seconds 60 --sample-fps 2 --corpus quality_samples --out data/spike/session_$(Get-Date -Format yyyyMMdd)/

# Venvs isolados (não contaminar core)
python -m venv .venv-hsemotion
python -m venv .venv-deepface

# Benchmark por provider (scripts criados na Fase 0.5)
# .\.venv-hsemotion\Scripts\Activate.ps1
# python scripts/spike_benchmark_expression.py --input data/spike/session_.../expression_samples --provider hsemotion --out data/spike/bench_hsemotion.json

pytest tests/test_dedup_presence.py tests/test_competitor_margin.py tests/test_behavioral_module.py -q
```

Scripts `spike_*.py` e `/debug/vision` são entregáveis da **Fase 0.5**, não desta fase.
