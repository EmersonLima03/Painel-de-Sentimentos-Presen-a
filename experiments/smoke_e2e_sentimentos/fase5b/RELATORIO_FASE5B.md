# Relatório Fase 5B — Homologação final da chamada automática

**Data:** 2026-09-18  
**Branch:** `feat/sentimentos-v1`  
**Base:** commit `3dc17b2` (Fase 5)  
**Escopo:** somente homologação E2E + evidências — **sem** redesenho de arquitetura  
**LXP produção:** intocado  
**TRI:** `git diff app/vision config.tri.yaml` = **vazio**

---

## Veredito

A integração API Sentimentos → LXP Attendance Simulator está **homologada** (contrato, idempotência, erros, offline→online no SyncWorker, seed 50/100 min).

A UI Sentimentos (gestor) foi validada com Playwright (**14/14 PASS**).

O caminho **câmera física ao vivo → enqueue LXP** nesta máquina ficou **NÃO OBSERVADO**: o Edge reiniciado para a sessão não tinha `MODULE_LXP_MODE=simulator` / `LXP_EXTERNAL_LESSON_ID` no ambiente (default `disabled`). A aula local/TRI continuou operando.

**Não foi feito commit** — aguarda aprovação.

---

## Fechamento (2026-09-18 — pós-aprovação homologação)

Homologação da Fase 5B **aprovada** quanto ao que foi efetivamente testado (API, 50/100, mapa, idempotência, erros, offline→online, Playwright, pytest, build, TRI).

Tentativa de **validação física opcional** (câmera USB):

| Sinal | Observação |
|-------|------------|
| Câmera USB | **disponível** (`cameras_online=1`) |
| Identidade / check-in | **ocorrendo** (`attendance_checkin` recente com `student_id=p01`) |
| `MODULE_LXP_MODE` | **`disabled`** (default) |
| `LXP_SIM_*` / `LXP_EXTERNAL_LESSON_ID` | **não configurados** no ambiente do processo |
| Outbox `lxp_attendance_event` ligado a check-in de câmera | **ausente** (só eventos do script de homolog offline) |
| Novos `attendance_records` no Simulator vindos da câmera | **ausentes** |

**Conclusão física:** **NÃO OBSERVADO** — limitação de ambiente (Simulator não ligado no Edge), **sem** alteração de TRI/thresholds/arquitetura para forçar o teste.

Auditoria final: ver seção **17** abaixo.

---

## 1. Testes executados

| Suite | Comando / artefato | Resultado |
|-------|--------------------|-----------|
| Homolog API + SyncWorker | `scripts/fase5b_homolog_validation.py` | **PASS** 18/18 |
| LXP integration | `pytest tests/test_lxp_attendance_integration.py` | **PASS** |
| Guards TRI phone | `pytest tests/test_phone_yolo_module_guard.py` | **PASS** |
| Persistência Sentimentos | `pytest tests/test_sentimentos_persistence_contract.py` | **PASS** |
| SyncWorker product lane | `pytest tests/test_sync_worker_product_lane.py` | **PASS** |
| Aggregate pytest | 4 suites acima | **27 passed** |
| Frontend build | `npm run build` (frontend) | **PASS** |
| Playwright E2E | `fase5b/run_playwright.cjs` | **PASS** 14/14 |
| TRI blindagem | `git diff app/vision config.tri.yaml` | **vazio** |

Evidências JSON:

- `experiments/smoke_e2e_sentimentos/fase5b/json/fase5b_validation.json`
- `experiments/smoke_e2e_sentimentos/fase5b/json/fase5b_playwright.json`
- `experiments/smoke_e2e_sentimentos/fase5b/json/fase5b_edge_outbox.json`

---

## 2. Resultados (taxonomia)

| # | Item | Status |
|---|------|--------|
| A | Simulator lessons seed 50/100 | **PASS** |
| B | Durações 50 min e 100 min | **PASS** |
| C | Alunos vinculados às aulas | **PASS** |
| D | Mapa p01↔ext-stu-001 … p03↔ext-stu-003 | **PASS** |
| E | Fluxo 50 min → `attendance_records` | **PASS** |
| F | Fluxo 100 min → 1 registro (não 2) | **PASS** |
| G | Idempotência 10× → 1 `attendance_id` / 1 row | **PASS** |
| H | Erros 401/404/duplicate | **PASS** |
| I | Endpoint unreachable (timeout) | **PASS** |
| J | Offline→online SyncWorker (pending→sent, 1 send) | **PASS** |
| K | Playwright UI Sentimentos + admin Simulator | **PASS** |
| L | Sem jargão TRI na UI produto | **PASS** |
| M | `npm run build` | **PASS** |
| N | pytest 27 | **PASS** |
| O | TRI diff vazio | **PASS** |
| P | Sessão Sentimentos cloud com `external_lesson_id` preenchido | **NÃO OBSERVADO** (sessões ativas com `null`) |
| Q | Câmera/TRI → check-in → outbox LXP → Simulator | **PASS** (fluxo físico E2E 2026-09-18; ver §18) |
| R | Relação “duas aulas consecutivas” ↔ bloco 100 | **PENDENTE** (produto) |
| S | UI Turma+Disciplina+Sessão → `external_lesson_id` | **PENDENTE** (já há suporte via env + `metadata_json`) |

---

## 3. Screenshots principais

Pasta: `experiments/smoke_e2e_sentimentos/fase5b/screenshots/`

| Arquivo | Conteúdo |
|---------|----------|
| `01_sim_admin.png` | Admin do LXP Attendance Simulator |
| `02_home.png` / `02_login.png` | Home + login gestor |
| `03_after_login.png` | Pós-login (nav Administração) |
| `04_admin.png` | Administração |
| `05_escola.png` / `05b_escola_produto.png` | Escola (admin + produto) |
| `06_turmas.png` | Turmas |
| `07_alunos.png` | Alunos |
| `08_disciplinas.png` | Disciplinas |
| `09_dashboard.png` | Relatórios (equivalente dashboard produto) |
| `10_ao_vivo.png` | Ao vivo / sessão |
| `11_historico.png` | Histórico |
| `12_config.png` | Configurações |

---

## 4. Fluxo 50 min (`lesson-8b-math-50`)

**PASS**

- Aula existe no Simulator: 8º Ano B / Matemática / 08:00–08:50 (50 min).
- Alunos `ext-stu-001..003` vinculados.
- POST `attendance.events.v1` com `lesson_id=lesson-8b-math-50` → `status=accepted` + `attendance_id`.
- Confirmação em `attendance_records` (REST + SQL MCP `user-supabase-lxp-sim`): aula, aluno, `present`, `source_event_id`.

Não aceito apenas HTTP 200: registro final conferido no banco do Simulator.

---

## 5. Fluxo 100 min (`lesson-8b-math-100`)

**PASS** (comportamento observado) + **PENDENTE** (produto)

**Observado:**

- Um único `external_lesson_id` com duração **100 minutos** (10:00–11:40).
- Um evento de presença → **um** `attendance_record`.
- O sistema **não** cria duas chamadas só porque a duração é 100 min.

**Pendência de produto:**

- Não há modelo explícito de “duas aulas consecutivas” ligadas a um bloco.
- Homologação atual trata o bloco como **uma aula externa** de 100 min.
- **Não inventamos** relação 2↔1 nesta fase.

---

## 6. Aluno → chamada

**PASS** (mapa + envio API)

| Edge | Simulator |
|------|-----------|
| p01 | ext-stu-001 |
| p02 | ext-stu-002 |
| p03 | ext-stu-003 |

Três POSTs distintos → aceitos.  
Regra mantida: sem identidade confiável / sem lesson → **não envia** (testes unitários + código `maybe_enqueue_lxp_attendance_from_checkin`).  
`visible`/`observável` **não** viram presença automaticamente.

**NÃO OBSERVADO:** reconhecimento físico em câmera gerando o enqueue nesta sessão (Edge sem modo simulator ligado).

---

## 7. Idempotência

**PASS**

- Mesmo `event_id` enviado **10×**.
- **1** `attendance_id` único na resposta.
- **1** row em `attendance_records` para o `source_event_id`.
- Replay posterior → `result=duplicate` (HTTP 200 aceito idempotente).

---

## 8. Offline → online

**PASS** (SyncWorker / outbox)

1. Endpoint Simulator inalcançável → exceção de rede (`ConnectTimeout`) — aula local independente.
2. Outbox `lxp_attendance_event` com cliente flaky: 1ª tentativa falha → `pending` + retry; 2ª → `sent`, **1** send, mesmo `event_id`.

**NÃO OBSERVADO nesta sessão:** derrubar a Edge Function real do Simulator e observar o Edge de produção local com SyncWorker vivo (exigiria alterar env/rede do processo). Comportamento coberto por script + pytest `test_sync_worker_retry_then_ok`.

Dashboard/aula local: Edge reiniciado e saudável (`/health` ok, câmera online).

---

## 9. Testes de erro

| Caso | Esperado | Status |
|------|----------|--------|
| Token inválido | 401 | **PASS** |
| Aula inexistente | 404 `lesson_not_found` | **PASS** |
| Aluno inexistente | 404 `student_not_found` | **PASS** |
| Duplicado | 200 `duplicate` | **PASS** |
| Simulator indisponível | timeout/falha de rede | **PASS** |

**Observação (P2 — não corrigido nesta fase):**

- `LxpAttendanceClient` trata 4xx como `return False` (não sucesso).
- O `SyncWorker` ainda incrementa retries até o máximo e marca `failed` — **não é retry infinito**, mas também **não** é fail-fast imediato em 4xx.
- 5xx/timeout → mesmo caminho de retry (desejado).
- Aula local **não** depende do Simulator.

---

## 10. Playwright

**PASS** 14/14

- Login gestor (`SMOKE_GESTOR_*`).
- Administração → Minha escola / Turmas / Alunos / Disciplinas.
- Relatórios, Escola, Ao vivo, Histórico, Configurações.
- Admin Simulator (`admin.html`).
- Sem jargão TRI (`yolo`, `fusion`, `track_id`, etc.) nas telas produto.

Nota UX: o produto chama a visão de relatório de **“Relatórios”** (não “Dashboard”).

---

## 11. Build

**PASS** — `frontend`: `tsc -b && vite build` OK.

---

## 12. Pytest

**PASS** — **27 passed** (LXP + phone guard + persistence + SyncWorker lane).

---

## 13. git diff TRI

```
git diff -- app/vision config.tri.yaml
```

**Resultado: vazio.** TRI intacto.

---

## 14. Problemas encontrados

| ID | Classe | Descrição |
|----|--------|-----------|
| P5B-1 | P2 | 4xx do Simulator ainda consomem retries do SyncWorker até o teto (não infinito). |
| P5B-2 | P1/ops | Edge local sem `MODULE_LXP_MODE`/`LXP_*` no restart → caminho câmera→LXP não observado. |
| P5B-3 | P3 | Sessões cloud Sentimentos com `external_lesson_id` null (env/metadata não aplicados nesta sessão). |
| P5B-4 | — | Cursor fechou no meio do Playwright; FE/Edge caíram — reinício controlado feito. |

Nenhum P0 que impeça aula local.

---

## 15. Correções feitas nesta etapa

Somente artefatos de homologação (sem tocar TRI / visão / LXP prod):

- `scripts/fase5b_homolog_validation.py` — validação API + SyncWorker offline→online
- `scripts/fase5b_inspect_edge.py` — inspeção outbox local
- `scripts/fase5b_playwright_e2e.mjs` — rascunho ESM
- `experiments/smoke_e2e_sentimentos/fase5b/run_playwright.cjs` — E2E Playwright
- `experiments/smoke_e2e_sentimentos/fase5b/package.json` (+ `.gitignore` de `node_modules`)
- Evidências em `fase5b/json/` e `fase5b/screenshots/`
- Este relatório

**Nenhuma** alteração em `app/vision/**`, `config.tri.yaml`, phone, Fusion, tracking, emoção, thresholds, `/debug/vision`.

---

## 16. Pendências

1. **Produto / 100 min:** modelar (ou não) “duas aulas consecutivas” vs um bloco; hoje = 1 `external_lesson_id`.
2. **Config aula sem `.env` fixo:** já existe `resolve_external_lesson_id` via `LXP_EXTERNAL_LESSON_ID` **ou** `class_sessions.metadata_json.external_lesson_id`. Falta UI/admin simples Turma+Disciplina+Sessão → gravar esse campo (sem conectar LXP real).
3. **Ops homolog:** documentar/ligar no Edge local:
   - `MODULE_LXP_MODE=simulator`
   - `LXP_SIM_ATTENDANCE_URL=...`
   - `LXP_SIM_INTEGRATION_TOKEN=...`
   - `LXP_SIM_ANON_KEY=...`
   - `LXP_EXTERNAL_LESSON_ID=lesson-8b-math-50`
4. **Fail-fast 4xx** no SyncWorker/LXP client (opcional, P2).
5. **Smoke físico** câmera→chamada — **VALIDADO** em 2026-09-18 (ver §18).

---

## 18. Fechamento definitivo — fluxo físico E2E

**Status:** **VALIDADO** (2026-09-18)

Fluxo comprovado:

Câmera USB → identidade `p01` → `attendance_checkin` → `lxp_attendance_event` → outbox → SyncWorker → Simulator `zasbmqwwkecmjbebejev` → `attendance_records`

| Campo | Valor |
|-------|--------|
| `session_id` | `fb5cd196-bf74-4c8d-a597-027f188c6830` |
| `checkin_event_id` | `64739219-6ec5-45cb-89ca-ec481f96e6a4` |
| LXP `event_id` | `lxp-att:64739219-6ec5-45cb-89ca-ec481f96e6a4` |
| aluno | `p01` → `ext-stu-001` |
| aula | `lesson-8b-math-50` |
| `attendance_id` | `9ba25bae-ccb7-4e75-80b7-693b3eb4ad36` |

Idempotência: reenvio 2× → `duplicate` → 1 registro.

`integration_receipts`: **NÃO OBSERVADO** (schema/REST sem `source_event_id` exposto). Não altera schema. Fluxo funcional já comprovado por `attendance_records` + idempotência.

**Config temporária do teste** (`modules.lxp: simulator` / env `LXP_SIM_*`): operacional para homologação — **não** é alteração do TRI. `config.tri.yaml` e `app/vision/**` intactos. `modules.lxp` restaurado para `disabled` após o teste.

Evidência: `json/fase5b_physical_e2e.json`

---

## Arquivos Fase 5B (commit)

```
scripts/fase5b_homolog_validation.py
scripts/fase5b_inspect_edge.py
scripts/fase5b_physical_probe.py
scripts/fase5b_physical_env_audit.py
scripts/fase5b_physical_e2e.py
scripts/fase5b_physical_e2e_watch.py
scripts/fase5b_playwright_e2e.mjs
experiments/smoke_e2e_sentimentos/fase5b/**  (exceto node_modules)
```

---

## 17. Auditoria final (fechamento)

### 17.1 Arquivos Fase 5B (novos)

| Path | Papel |
|------|--------|
| `scripts/fase5b_homolog_validation.py` | Homolog API + SyncWorker |
| `scripts/fase5b_inspect_edge.py` | Inspeção outbox local |
| `scripts/fase5b_physical_probe.py` | Probe read-only câmera/LXP env |
| `scripts/fase5b_physical_env_audit.py` | Auditoria de env/sessão |
| `scripts/fase5b_physical_e2e.py` | Orquestração E2E físico |
| `scripts/fase5b_physical_e2e_watch.py` | Watch checkin→Simulator |
| `scripts/fase5b_playwright_e2e.mjs` | Rascunho ESM Playwright |
| `experiments/smoke_e2e_sentimentos/fase5b/**` | Evidências, runner CJS, relatório |

**Modificados de produto nesta etapa:** nenhum (`app/**` / TRI).

### 17.2 Fora do escopo Fase 5B (working tree sujo pré-existente)

Não entram no commit 5B:

- `config.yaml` (modificado localmente; LXP voltou a `disabled`)
- `frontend/tsconfig.tsbuildinfo`
- experimentos emoção/TRI (`experiments/hsemotion_*`, `tri_*`, `scenario_i_ai`, etc.)
- outros scripts smoke/E2E não-fase5b
- `supabase_lxp_sim/functions/` (untracked local)

### 17.3 TRI

- `git diff -- app/vision config.tri.yaml` → **vazio**
- Desde âncora de blindagem `0a213cf` até `HEAD`: **nenhum** commit tocou `app/vision/**` nem `config.tri.yaml`

### 17.4 Testes finais / build

- pytest (LXP + phone guard + persistence + SyncWorker): **27 passed** (env LXP limpo)
- `npm run build`: **PASS**

### 17.5 LXP produção vs Simulator

- Homologação usa **somente** Simulator `zasbmqwwkecmjbebejev`
- Sentimentos cloud: `rmiaadljzxyehwyuhhgd` (produto Sentimentos, não LXP)
- **LXP de produção:** intocado

### 17.6 Câmera física → chamada

**PASS** — ver §18.

### 17.7 Veredito de fechamento

Homologação + fluxo físico E2E validados; TRI intacto; evidências preservadas.  
**Commit exclusivo da Fase 5B.**
