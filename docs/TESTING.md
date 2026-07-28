# Testes

## Estado atual (2026-07-27 — P0)

| Suite | Resultado |
|-------|-----------|
| `pytest tests -q` | Inclui identidade body_continuity, observabilidade, attribution |
| Analytics person-first | `test_person_centric_pipeline` — **12s ≠ expire**; 15/30/60s body_continuity |
| P0 observabilidade | `tests/test_p0_observability_attribution.py` |
| Analytics real | `tests/test_realtime_analytics.py` |

**Timeline / eventos:** `live_event_buffer` in-memory (não sobrevive reinício). Sem migração SQLite no P0.

## Checklist manual webcam (P0)

1. Ocultar só o rosto 15–60s com corpo estável → identidade `body_continuity` (não unknown).
2. Cabeça baixa >12s → identidade mantida; sem sono só por pose.
3. Virar de costas / oclusão → mesma regra; `temporarily_lost` ≥4s → `uncertain`.
4. Cruzar com outra pessoa → `uncertain`; nova pessoa na posição → não herda id.
5. Olhos 3s / 6s / 30s → descritivo / possible / probable.
6. Ocluir rosto no meio do evento → duração não soma gap; após ~8s gap → inconclusivo.
7. Celular breve / 5s / 12s → estados corretos; sem “desatento”.
8. Interromper API → UI `unavailable`/`stale` cinza; restaurar → `recovering`/`live`.
9. Preview falho ≠ snapshot OK; `no_tracks` quando API ok sem pessoas.

## Estrutura

- `tests/conftest.py` — SQLite temporário; `reset_db_singleton()`; **bloqueia** uso de `data/dulino_edge.db`
- Presença: `test_dedup_presence`, `test_competitor_margin`, `test_queue`, `test_events`
- Person-first: associação face↔pessoa, IdentityBinding **body_continuity** (não expire@12s), **continuidade corporal** (`test_person_track_continuity`), phone ambíguo, buffers por `person_track_id`
- P0: `test_p0_observability_attribution` (pausa oclusão, attribution pending, EAR config)
- Multimodal: `test_multimodal_contracts` (modos, mock expression, binding, phone sem confirmed, qualidade, fusion, LXP)
- Demo: `test_demo_mode` (8 tracks, review, WS, LXP flush, isolamento DB)
- Validação: `test_validation_panel` (DB `validation.db` isolado; sem frames/embeddings; não altera presença)
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

## Checklist person-first (1 pessoa antes de multi)

1. Person detect+track estável sem rosto  
2. Face associada à pessoa correta (`face_person_association`)  
3. Identidade no TTL sob oclusão; após TTL → unknown **no mesmo** `person_track_id`  
4. 15–20s com rosto coberto: ID corporal não muda (`tracking_state` pode ser active/temporarily_lost)  
5. Swap bloqueado com conf baixa / ambiguidade  
6. Cabeça baixa ≠ sonolência; celular visível ≠ uso  
7. Só então 2 → 4 → 8 pessoas  

## Checklist manual — validação controlada (webcam RTSP)

1. `$env:RUNTIME_MODE="rtsp"; $env:ENABLE_DEBUG_SNAPSHOT="1"` + uvicorn  
2. Abrir `/debug/vision` → aba **Validação controlada**  
3. **Nova sessão** (operador + `cam-web`)  
4. Para cada cenário: **Iniciar** → executar a instrução → **Finalizar** (+ observação)  
5. Amostras são coletadas automaticamente (~0.5s) a partir do `debug-snapshot` live  
6. **Gerar relatório** → export JSON / CSV  
7. Confirmar que dados foram para `data/validation/validation.db` (não `dulino_edge.db`)  
8. Confirmar que attendance/presença não mudou por causa da validação  

Resultados por etapa: **PASS** / **FAIL** / **INCONCLUSIVO** (heurística + observação manual).

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
