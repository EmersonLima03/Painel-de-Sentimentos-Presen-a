# Fase 5 — LXP Attendance Simulator + integração de chamada

**Data:** 2026-09-18  
**Branch:** `feat/sentimentos-v1`  
**TRI:** intocado (`git diff app/vision config.tri.yaml` = vazio)  
**LXP produção:** intocado

---

## Arquitetura implementada

```
Câmera → TRI (congelado) → attendance_checkin (identidade válida)
                              ↓
                    maybe_enqueue_lxp_attendance_from_checkin
                              ↓
                    outbox SQLite (lxp_attendance_event)
                              ↓
                    SyncWorker (lane lxp)
                              ↓
                    LxpAttendanceClient + token
                              ↓
                    Edge Function attendance-events
                              ↓
                    LXP Attendance Simulator (zasbmqwwkecmjbebejev)
                              ↓
                    attendance_records + integration_receipts
```

Sentimentos cloud (`rmiaadljzxyehwyuhhgd`) continua recebendo sessão/eventos/snapshots via `ingest-events` (agora com `external_lesson_id`).

---

## Projetos Supabase

| Projeto | Ref | Papel |
|---------|-----|--------|
| Sentimentos | `rmiaadljzxyehwyuhhgd` | produto |
| **LXP Attendance Simulator** | `zasbmqwwkecmjbebejev` | LXP fictício de homologação |

---

## Tabelas criadas (Simulator)

`schools`, `teachers`, `class_groups`, `subjects`, `students`, `lessons`, `lesson_students`, `attendance_records`, `integration_receipts`, `integration_tokens`

### Seed

- Escola Demo / 8º Ano B / Matemática  
- `lesson-8b-math-50` (50 min)  
- `lesson-8b-math-100` (100 min bloco)  
- Alunos `ext-stu-001`…`003` ↔ edge `p01`…`p03`

## Sentimentos (migration)

- `class_sessions.external_lesson_id` (text, indexado)

---

## Edge Function

`POST/GET https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events`  
Contrato: `docs/LXP_ATTENDANCE_CONTRACT_V1.md`

Auth: `X-Integration-Token` (hash em `integration_tokens`) + anon gateway.

---

## Código Edge (Presença)

| Arquivo | Papel |
|---------|--------|
| `app/integrations/attendance_lxp.py` | enqueue + cliente HTTP |
| `app/sync/outbox_contract.py` | lane `lxp` |
| `app/sync/worker.py` | roteia LXP vs Sentimentos |
| `app/pipeline/presence.py` | hook após check-in válido |
| `app/config.py` | `LXP_SIM_*`, `LXP_EXTERNAL_LESSON_ID` |
| Frontend | label “Aula externa…” em header/config |

---

## Env (Edge) — não commitar plaintext

```
MODULE_LXP_MODE=simulator
LXP_SIM_ATTENDANCE_URL=https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events
LXP_SIM_INTEGRATION_TOKEN=<mesmo plaintext cujo hash está no simulador>
LXP_SIM_ANON_KEY=<anon do projeto simulador>
LXP_EXTERNAL_LESSON_ID=lesson-8b-math-50
```

Token de homolog documentado nos testes: configurar localmente (não no git).

---

## Testes

| Suite | Resultado |
|-------|-----------|
| `test_lxp_attendance_integration` + guards TRI + persistence + sync worker | **27 passed** |
| `scripts/smoke_lxp_sim_attendance.py` (API real simulador) | **passed** — 10× mesmo `event_id` → 1 attendance |
| `git diff app/vision config.tri.yaml` | **vazio** |

Evidência API: `experiments/smoke_e2e_sentimentos/lxp_sim_integration_results.json`  
Admin UI estática: `experiments/lxp_attendance_simulator/admin.html`

---

## Offline → online

Mesmo mecanismo do outbox product: `pending` → SyncWorker retry → `sent`.  
Erro 5xx/timeout: retry; 4xx contrato: falha sem retry cego.

---

## Pendências reais

1. Playwright E2E full UI Sentimentos + admin com Edge live (API smoke OK; UI admin HTML pronta).  
2. Provisionar token de integração **não-demo** em secret store.  
3. Mapear `external_lesson_id` por sessão no cloud UI (hoje: env Edge + campo local Configurações).  
4. Substituir simulador pelo endpoint real do LXP quando a Dulino publicar o contrato.  
5. Não há sync automático de hierarquia LXP→Sentimentos (fora do escopo desta fase).

---

## O que NÃO foi feito (conforme regra)

- Integração com LXP de produção  
- Alterações TRI / vision / thresholds  
- Multicâmera, biometria cloud, vídeo no Supabase  
