# Testes

## Estado atual (2026-07-23)

| Suite | Resultado |
|-------|-----------|
| `pytest tests -q` | **62 passed** |
| `npm run typecheck` (frontend) | **PASS** |
| `npm run build` (frontend) | **PASS** |
| E2E demo | **PASS** |
| Analytics real (quality/landmarks/expression/attn/phone status) | `tests/test_realtime_analytics.py` |
| Validação de campo / Intelbras | **Pendente** |
| Benchmark FER / HSEmotion / DeepFace | **Não executado** (sem labels) |

Métricas de software/demo **não** representam acurácia ou desempenho da câmera Intelbras.

## Estrutura

- `tests/conftest.py` — SQLite temporário; `reset_db_singleton()`; **bloqueia** uso de `data/dulino_edge.db`
- Presença: `test_dedup_presence`, `test_competitor_margin`, `test_queue`, `test_events`
- Multimodal: `test_multimodal_contracts` (modos, mock expression, binding, phone sem confirmed, qualidade, fusion, LXP)
- Demo: `test_demo_mode` (8 tracks, review, WS, LXP flush, isolamento DB)
- Migration 005: `test_migration_005` em DB temp
- Engajamento / emoção mapeamento: testes legados existentes

## Comandos

```powershell
pytest tests -q
pytest tests/test_dedup_presence.py tests/test_competitor_margin.py tests/test_queue.py -q

cd frontend
npm run typecheck
npm run build
```

## Checklist manual — modo demo

1. `$env:RUNTIME_MODE="demo"` + uvicorn  
2. Abrir `/dashboard` — banner demo + disclaimer  
3. WS: `connected`  
4. Play / Pause / Reset / 1x / 2x / 5x  
5. Após ~70s de cenário (ou seek via API): **8** tracks  
6. Check-ins na timeline  
7. Eventos: celular visível ≠ uso; possível; provável  
8. Olhos fechados curtos **sem** alerta persistente  
9. Sonolência aparente com review  
10. Oclusão / inconclusivo  
11. Confirmar / rejeitar evento  
12. Relatório + CSV  
13. `POST /demo/lxp/flush`  
14. Confirmar escrita só em `data/demo/…`, não em `dulino_edge.db`  
15. Reconectar WebSocket (fechar aba e reabrir)

Alunos fictícios: Ana Lima, Bruno Costa, Carla Souza, Daniel Alves, Eduarda Rocha, Felipe Martins, Gabriela Silva, Henrique Santos.

## Plano futuro — RTSP / campo

Cenários: 1 / 4 / 8 pessoas; distância; iluminação; oclusão; expressão; celular; sonolência; CPU; RAM; FPS; latência; FP/FN.  
Corpus consentido em `data/spike/` (não versionar mídia).  
Roteiro multi-pessoa histórico: cadastro p01…, viewer estável, margin/histerese — usar thresholds **congelados** atuais, não exemplos antigos com `match_margin: 0.08`.

Monitor rápido: `.\scripts\monitor_presence.ps1` (poll `/cameras` a cada 2s).

## Critérios shadow → production (inferência)

1. Corpus rotulado + métricas honestas  
2. Benchmark longitudinal registrado (`longitudinal_approval_recorded: true`)  
3. Review humana amostral  
4. Feature flag / modo módulo = production só após gates  
5. Rollback documentado  
6. **Não** usar métricas demo como evidência de hardware  

## Isolamento e regressão de presença

Após mudanças em analytics, rodar sempre:

```powershell
pytest tests/test_dedup_presence.py tests/test_competitor_margin.py tests/test_queue.py -q
```

Thresholds de presença: perfil `presence-yaml-2026-07-23` — ver [ARCHITECTURE.md](ARCHITECTURE.md).
