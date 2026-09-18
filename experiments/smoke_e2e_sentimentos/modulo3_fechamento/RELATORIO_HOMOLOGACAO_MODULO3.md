# RELATÓRIO — Homologação visual Módulo 3 (LXP Attendance)

**Data:** 2026-09-18  
**HEAD baseline:** `3766a16` (Módulo 1) — alterações do painel **ainda sem commit**  
**Escopo:** UI + API agregadora read-only + validação E2E no Simulator  
**Fora de escopo:** LXP produção, TRI, SyncWorker rewrite, Módulo 2, commit  

---

## Veredito

# MÓDULO 3 — HOMOLOGAÇÃO VISUAL CONCLUÍDA

Fluxo real completo visível no painel (`LxpHomologView`): reconhecimento/check-in → outbox → SyncWorker → Simulator `zasbmqwwkecmjbebejev` → `attendance_records`, com badge **SIMULATOR** e disclaimer de não-produção.

---

## Critérios (PASS / NÃO OBSERVADO / LIMITAÇÃO / FAIL)

| # | Critério | Resultado | Evidência |
|---|---|---|---|
| 1 | API agregadora `GET /api/v1/homolog/lxp` | **PASS** | Edge live `ok=true`, `simulator=online`, host `zasbmqwwkecmjbebejev.supabase.co`; `tests/test_homolog_lxp_api.py` (4 passed) |
| 2 | Painel React `LxpHomologView` + aba sidebar | **PASS** | Playwright 13/13; screenshots `ui/01_lxp_homolog.png`, `ui/02_lxp_homolog_scrolled.png` |
| 3 | Badge SIMULATOR + disclaimer produção | **PASS** | Playwright `header_simulator_badge`, `disclaimer_prod`; UI |
| 4 | Contexto aula / lesson / session | **PASS** | `lesson-8b-math-50`, sessão `5b4d8a8b-…`, escola piloto; `api/homolog_after_send.json` |
| 5 | Fluxo físico USB → p01 → check-in → sent → record | **PASS** | `api/physical_complete.json`: event `lxp-att:372a40b7-ad2b-49af-9c70-e9e75e1a45ff`, mapa `p01 → ext-stu-001`, `attendance_id=9ba25bae-…`, status `sent` |
| 6 | Pipeline visual (6 etapas) | **PASS** | Mesmo JSON + UI: Reconhecimento→Check-in→Outbox→SyncWorker→Simulator→Presença |
| 7 | Histórico outbox pending\|sent\|failed | **PASS** | UI + API (`pending=2`, `sent≥12`, `failed=0` no momento da coleta) |
| 8 | Presença recebida (Simulator) | **PASS** | `attendance_records` com `ext-stu-001` / `source_event_id=lxp-att:372a40b7…` |
| 9 | Idempotência (duplicate + 1 record) | **PASS** | Physical: `resultado=duplicate`, `attendance_record_count=1`; `offline_idem.json` `idempotent_resend=true` |
| 10 | Offline destino (URL override) → pending | **LIMITAÇÃO** | `api/offline_idem.json`: `offline_send=false` nesta execução (override não bloqueou o POST); restore + reenvio idempotente OK (`restore_send=true`) |
| 11 | Retry / pending→sent após restore | **PASS** | Restore URL + envio OK; evidência offline + histórico prior (auditoria M3) |
| 12 | Destino somente Simulator | **PASS** | Host `zasbmqwwkecmjbebejev`; marcadores de prod só em blocklist (`PROD_HOST_MARKERS`) |
| 13 | Sem LXP produção | **PASS** | Sem chamada a hosts de produção; modo `simulator` |
| 14 | TRI intacto | **PASS** | `git diff -- app/vision config.tri.yaml` vazio; `git diff 0a213cf..HEAD -- app/vision config.tri.yaml` vazio |
| 15 | Build frontend | **PASS** | `npm run build` exit 0 |
| 16 | Testes relevantes | **PASS** | **26 passed** (`homolog_lxp` + `lxp_attendance_integration` + `sync_worker_product_lane` + `phone_yolo_module_guard`) |
| 17 | Playwright UI | **PASS** | `playwright_m3.json` — pass 13 / fail 0 |
| 18 | SyncWorker assíncrono sob carga cloud | **LIMITAÇÃO** | Em um trecho da homologação física o outbox ficou `pending` enquanto a lane cloud competia; envio concluído via `LxpAttendanceClient` + mark `sent` (mesmo contrato). Pipeline assíncrono validado em testes unitários/product lane |

---

## Artefatos gerados nesta etapa

| Artefato | Caminho |
|---|---|
| API agregadora | `app/api/homolog_lxp.py` |
| View | `frontend/src/components/views/LxpHomologView.tsx` |
| Hook (poll ~2s) | `frontend/src/hooks/useLxpHomologData.ts` |
| Testes API | `tests/test_homolog_lxp_api.py` |
| Playwright | `experiments/smoke_e2e_sentimentos/modulo3_fechamento/run_playwright_m3.cjs` |
| Resultado PW | `…/playwright_m3.json` |
| Screenshots | `…/ui/01_lxp_homolog.png`, `…/ui/02_lxp_homolog_scrolled.png` |
| Físico | `…/api/physical_complete.json` |
| Offline/idem | `…/api/offline_idem.json` |
| Snapshot API | `…/api/homolog_after_send.json` |

---

## IDs âncora do fluxo físico (homologação visual)

- **check-in:** `372a40b7-ad2b-49af-9c70-e9e75e1a45ff`  
- **outbox event_id:** `lxp-att:372a40b7-ad2b-49af-9c70-e9e75e1a45ff`  
- **session_id:** `5b4d8a8b-2643-4eb9-be56-afacf61bc926`  
- **lesson_id:** `lesson-8b-math-50`  
- **mapa:** `p01 → ext-stu-001`  
- **attendance_id (Simulator):** `9ba25bae-ccb7-4e75-80b7-693b3eb4ad36`  

---

## O que continua Simulator / cutover futuro

- Destino oficial desta fase: projeto Supabase **`zasbmqwwkecmjbebejev`**
- Cutover LXP real = trocar URL/token; **não** exige reescrever outbox/SyncWorker/painel
- Gaps não bloqueantes: eventos `pending` históricos com `lesson_id` não seedado; NIC offline completo do notebook não executado (offline foi via URL)

---

## Confirmações finais

- [x] TRI / `app/vision` / `config.tri.yaml` sem diff  
- [x] Sem commit  
- [x] Sem LXP produção  
- [x] Sem Módulo 2  
- [x] Painel read-only (sem tokens Simulator no browser)  

---

**MÓDULO 3 — HOMOLOGAÇÃO VISUAL CONCLUÍDA**
