# Presença — Estado Real do Produto

**Documento:** Mapa único da verdade (auditoria somente leitura)  
**Data:** 2026-09-22  
**Fonte de código auditada:** worktree `_facial_enroll_prod` · branch `feat/auth-saas-rbac` @ `1bd701c`  
**URL pública:** https://presenca.sistemadulino.com.br  
**Método:** leitura de código React/Edge/M2 + migrations + APIs live + Supabase A/B + auditoria E2E anterior  
**Regra desta auditoria:** nenhum código alterado; nenhum mock/fixture/force-step

---

## 1. Visão geral

### O que o Presença é hoje

Sistema híbrido **Edge + Cloud** para escola:

1. **Cloud (Supabase A)** — identidade, escola, turmas, alunos, aulas planejadas, auth/RBAC, espelho de status facial (sem biometria).
2. **Edge (FastAPI :8000)** — câmera, YuNet, FaceNet, FAISS, presença, TRI/engajamento, sessão de aula, sync outbox.
3. **M2 (:8766, loopback)** — cadastro facial do aluno (convite/QR → captura → promote → embeddings no SQLite Edge).
4. **Supabase B (LXP sim)** — destino homologado de frequência (`attendance_records`); isolado da biometria.
5. **Dashboard React** — SPA por **tabs** (não há React Router). Login wall no worktree facial.

### Ambiente observado no momento da auditoria

| Item | Estado |
|------|--------|
| Edge | UP · `/health` ok · YuNet + FaceNet · FAISS on · 1 câmera · 4 embeddings |
| M2 | UP · `/m2/healthz` ok · `roster_source=supabase` · `test_hooks=false` |
| Tunnel | Named `presenca-edge` → `127.0.0.1:8000` |
| Sessão Edge | Ativa: **“Sessão automática”** · `context: null` (aula formal **não** vinculada) |
| Cache aulas | 1 occurrence (`lesson-8b-math-50`) |
| Supabase A | 1 escola, 1 turma, 1 aluno (Emerson), 1 aula `scheduled`, `class_sessions=0` cloud |
| Supabase B | 4 `attendance_records` históricos; sem prova de sync “hoje” na E2E |

### Dois workspaces (importante)

| Workspace | Papel real |
|-----------|------------|
| `Presenca` | Repo base; fluxo aula parcial; **sem** UI de cadastro facial / `m2_proxy` |
| `_facial_enroll_prod` | **Produto em operação** (auth SaaS + facial + aula + tunnel) |

Este mapa descreve o **produto em operação** (`_facial_enroll_prod`), com notas quando o repo base diverge.

---

## 2. Usuários e permissões

### 2.1 Papéis

| Papel | Existe no Auth/DB? | Tem tela própria? | “Rotas” (tabs) disponíveis | Permissões reais |
|-------|--------------------|-------------------|----------------------------|------------------|
| **ROOT** | Sim — `profiles.is_platform_admin` | Sim — tab **Plataforma** (`RootPlatformView`) | Todas as product + Admin + Plataforma + Cadastro facial | Criar orgs/escolas/usuários; invite cross-org; reset admin |
| **ADMIN_REDE** | Sim — `organization_memberships.role = admin_rede` | **Não** dedicada | Product + Admin + Cadastro facial (via flags) | `canOpenAdmin`, `canManageFacial`; sem tab Plataforma |
| **GESTOR** | Sim — `memberships.role = gestor` | Administração completa (9 seções) | Ao vivo, Relatórios, Escola, Histórico, Cadastro facial, LXP, Config, Admin | CRUD escola/equipe/disciplinas/turmas/alunos/aulas/salas/devices/câmeras; push cache Edge; **não inicia aula** |
| **COORDENADOR** | Sim no DB/API (CHECK expandido) | Trata-se como gestor na UI (`isGestor=true`) | Igual gestor | Mesmo pacote gestor; **não** aparece no `<select>` de Equipe (gap UI) |
| **PROFESSOR** | Sim | **Minhas aulas** (`ProfessorLimitedView`) | Product tabs + “Minhas aulas” (sem CRUD admin) | Lê aulas do dia atribuídas; **Iniciar aula** / **Encerrar**; push cache automático |
| **MONITOR** | Sim | Igual professor (não-gestor) | Idem | Mesmo shell limitado que professor |
| **ALUNO** | **Não** como login Auth | Sem tela no Dashboard React | — | Entidade `students` + fluxo M2 no celular (`/e/{token}`); não é papel de app |

### 2.2 Auth — o que existe de verdade

| Fluxo | Existe? | Onde |
|-------|---------|------|
| Login | **Sim** | `LoginView` (wall) + Configurações |
| Logout | **Sim** | Sidebar / Settings / conta disabled |
| Recuperação de senha | **Sim** | `LoginView` forgot/reset + CloudAuthPanel |
| Convite / criar usuário | **Sim** | Admin → Equipe → `admin-invite-user`; ROOT → `platform-admin` |
| Ativação / desativação | **Sim** (perfil `status`) | Conta `disabled` bloqueia app |
| Self-signup público | **Não** | — |
| React Router / middleware de rota | **Não** | Guards só em `App.tsx` + RLS SQL |

### 2.3 Como o RBAC é aplicado

- **UI:** `AuthContext` (`isRoot`, `isAdminRede`, `isGestor`, `canManageFacial`, `canOpenAdmin`).
- **`isGestor` (facial):** root **ou** admin_rede **ou** role escolar `gestor`/`coordenador`.
- **Admin shell:** se `!isGestor` → `ProfessorLimitedView`.
- **SQL RLS:** `has_school_role`, `is_root`, `has_org_role`, policies em migrations.
- **Edge Functions:** `admin-invite-user`, `platform-admin` (ROOT).

---

## 3. Fluxos reais

### 3.1 Fluxo gestor (escola entra e opera)

```
Login (LoginView)
  ↓
Ao vivo (default) — pode já haver “Sessão automática” do Edge
  ↓
Administração → Minha escola / Equipe / Disciplinas / Turmas / Alunos / Salas / Devices / Câmeras
  ↓
Cadastro facial → convite aluno → aluno captura no celular → promote → FAISS
  ↓
Administração → Aulas → Criar aula (lesson_occurrences)
  ↓
Botão “Enviar aulas do dia ao Edge (cache)” → POST /api/v1/lessons/cache
  ↓
⚠ Gestor NÃO tem botão “Iniciar aula”
  ↓
Professor (outro usuário) inicia → start-with-context
  ↓
Ao vivo / Relatórios / (sync) LXP Homologação
```

| Etapa | Existe? | Onde / botão | API | Banco |
|-------|---------|--------------|-----|-------|
| Login | Sim | `LoginView` | Supabase Auth | `auth.users` / `profiles` |
| Criar escola | Sim (ROOT) / parcial gestor | Plataforma ou Minha escola | Supabase / `platform-admin` | `schools` |
| Criar turma | Sim | Admin → Turmas | `adminApi` insert | `class_groups` |
| Cadastrar alunos | Sim | Admin → Alunos | insert + trigger `edge_student_key` | `students`, `enrollments` |
| Cadastro facial | Sim | Tab Cadastro facial | M2 via proxy | SQLite `face_embeddings` + mirror A |
| Criar aula | Sim | Admin → Aulas → Criar | `lesson_occurrences.insert` | Supabase A |
| Enviar ao Edge | Sim | “Enviar aulas do dia ao Edge (cache)” | `POST /api/v1/lessons/cache` | arquivo `lesson_cache/today.json` |
| Iniciar aula | **Não na UI do gestor** | Só professor | `POST /api/v1/sessions/start-with-context` | SQLite `class_sessions` + update occurrence |
| Acompanhar presença | Sim | Ao vivo / Relatórios | `/api/v1/live/*`, timeline | Edge + (sync) A |

### 3.2 Fluxo professor

```
Login
  ↓
Mesmas tabs de produto (Ao vivo, Relatórios, …)
  ↓
Nav “Minhas aulas” (não “Administração”)
  ↓
Lista aulas do dia (atribuídas a ele)
  ↓
Cache Edge automático (best-effort)
  ↓
Botão “Iniciar aula” → start-with-context + status in_progress
  ↓
Ao vivo passa a refletir lesson_context (quando start ok)
  ↓
“Encerrar aula ativa” → POST /sessions/{id}/end + occurrence completed
```

| Pergunta | Resposta real |
|----------|---------------|
| Possui painel? | Sim — `ProfessorLimitedView` |
| Recebe aulas? | Sim — `fetchMyLessonsToday` (onde é `teacher_profile_id`) |
| Inicia aula? | **Sim — único papel com botão na UI** |
| Encerra aula? | Sim |
| CRUD escola/turmas? | Não |

**Estado live E2E:** só havia membership **gestor**; `teacher_assignments=0`. Sem login professor validado nesta homologação → aula formal não iniciada.

### 3.3 Fluxo aluno (cadastro facial)

```
Aluno oficial em students (gestor)
  ↓
student_id (UUID cloud)
  ↓
edge_student_key (auto: e_<hex> ou legado p01)
  ↓
Gestor abre Cadastro facial → gera invite / campanha
  ↓
Aluno abre /e/{token} no celular (via tunnel → proxy → M2)
  ↓
Captura frames → FaceNet → gallery_temp campanha
  ↓
Promote → face_embeddings (SQLite) → POST /internal/matcher/reload
  ↓
FAISS reconhece na aula (matcher usa edge_student_key)
```

| Peça | Status |
|------|--------|
| Convite / QR / link | **Implementado** (M2) |
| Câmera aluno | **Implementado** (browser celular) |
| Conclusão + promote | **Implementado** |
| Fallback / lab legado | Existe galeria `facenet_aligned_v2` (POC) |
| Campanha interna | Tabelas `facial_enrollment_*` ainda existem (ops) |
| Login aluno no Dashboard | **NÃO IMPLEMENTADO** |

---

## 4. Telas existentes

Navegação = **tabs** em `App.tsx` (path HTTP tipicamente `/dashboard`). Não há rotas `/live`, `/gestor` como páginas React Router.

| Tela | Tab / acesso | Perfil | Status | Objetivo |
|------|--------------|--------|--------|----------|
| Login | wall se sem sessão | público | ativo | Autenticar |
| Ao vivo | `live` | autenticado | ativo | Presença + TRI + tracks em tempo real |
| Relatórios | `report` | autenticado | ativo | Resumo / presença / sinais / clima |
| Escola | `school` | autenticado | ativo | Visão escola (produto) |
| Histórico | `history` | autenticado | ativo | Sessões passadas |
| Cadastro facial | `facialEnrollment` | root/admin_rede/gestor/coordenador | ativo | Gate + iframe/srcDoc M2 gestor |
| LXP Homologação | `lxpHomolog` | autenticado | ativo | Conferência simulador B |
| Configurações | `settings` | autenticado | ativo | Auth panel, tokens, ops |
| Administração | `admin` | staff (gestor+) | ativo | 9 seções CRUD |
| Minhas aulas | `admin` se !gestor | professor/monitor | ativo | Iniciar/encerrar |
| Plataforma | `platform` | ROOT only | ativo | Orgs/escolas/usuários |
| QA Alunos/Eventos/Sistema | `?qa=1` | debug | oculto | Laboratório |

### Subseções Administração (gestor)

Minha escola · Equipe · Disciplinas · Turmas · Alunos · Aulas · Salas · Dispositivos · Câmeras

### Componentes / APIs (resumo)

| Tela | Componentes | APIs principais |
|------|-------------|-----------------|
| Ao vivo | `LiveClassView`, `useDashboardData` | `GET /api/v1/live/status`, `classroom-summary`, `tracks`, WS `/ws/live` |
| Relatórios | `ReportView` | `/sessions/{id}/summary|timeline|students|…` |
| Admin aulas | `LessonsAdmin` em `AdminShellView` | Supabase `lesson_occurrences`; `POST /lessons/cache` |
| Minhas aulas | `ProfessorLimitedView` | cache + `POST /sessions/start-with-context` + `/sessions/{id}/end` |
| Facial | `FacialEnrollmentView` | `/gestor`, `/api/gestor/*`, gate `/dashboard/api/m2-gestor-gate` |
| Plataforma | `RootPlatformView` | edge function `platform-admin` |

### Telas órfãs / incompletas / sem acesso

| Item | Classificação |
|------|---------------|
| HTML legado dashboard | Backend ainda serve `/dashboard/api/*`; UI React é a superfície |
| `/enroll`, `/enroll/webcam` | **SÓ BACKEND** (debug) |
| `POST /sessions/start` (sem contexto) | **SÓ BACKEND** — UI não usa |
| Select Equipe sem `coordenador` | **Incompleto** (API aceita; UI não oferece) |
| Admin rede sem home dedicada | **Sem tela própria** (só permissões) |
| Painel aluno no React | **Ausente** |

---

## 5. APIs

### 5.1 Edge — aula e live (`/api/v1`)

| Método | Rota | Quem chama | Status |
|--------|------|------------|--------|
| POST | `/lessons/cache` | Gestor (botão) / Professor (auto + start) | UI+API |
| GET | `/lessons/cache` | Ops / auditoria | API |
| POST | `/sessions/start-with-context` | **Só UI professor** | UI+API |
| GET | `/sessions/current-context` | Professor / dashboard | UI+API |
| GET | `/live/status` | Ao vivo | UI+API |
| GET | `/live/classroom-summary` | Ao vivo | UI+API |
| GET | `/live/tracks` | Ao vivo | UI+API |
| WS | `/ws/live` | Ao vivo | UI+API |
| GET | `/sessions/{id}/…` | Relatórios | UI+API |

### 5.2 Edge — raiz (`main.py`)

| Método | Rota | Nota |
|--------|------|------|
| POST | `/sessions/start` | Legado **sem** lesson context — **sem botão React** |
| POST | `/sessions/{id}/end` | Encerrar (professor) |
| GET | `/health`, `/stats`, `/cameras` | Ops |
| POST | `/internal/matcher/reload` | Promote M2 → FAISS |
| POST | `/enroll*` | Debug |

### 5.3 Proxy M2 (só worktree facial)

`/gestor*`, `/e/*`, `/a/*`, `/api/gestor/*`, `/api/aluno/*`, `/m2/healthz`, gate `POST /dashboard/api/m2-gestor-gate`

### 5.4 Cloud Functions (Supabase A)

| Function | Papel |
|----------|-------|
| `ingest-events` | Edge → A (sessões/eventos/snapshots/heartbeat) |
| `admin-invite-user` | Convite equipe escolar |
| `platform-admin` | ROOT |

### 5.5 LXP (Supabase B)

| Function | Papel |
|----------|-------|
| `attendance-events` | Edge SyncWorker → `attendance_records` + receipts |

---

## 6. Banco

### 6.1 Supabase A (produto) — `rmiaadljzxyehwyuhhgd`

| Tabela | Finalidade | Quem escreve | Rows live (auditoria) |
|--------|------------|--------------|------------------------|
| organizations / schools | Tenant | admin/ROOT | 1 / 1 |
| profiles / memberships | Usuários e papéis | Auth + invite | 5 / 1 |
| organization_memberships / invites / audit_logs | Rede + SaaS | platform-admin | 0 |
| subjects / class_groups / students / enrollments | Domínio escolar | Gestor | 1 cada |
| teacher_assignments | Professor↔turma | Gestor | **0** |
| rooms / cameras | Física | Gestor | 1 / **0** |
| edge_devices / device_credentials | Device ingest | Provisionamento | **0 / 0** |
| lesson_occurrences | Aula planejada | Gestor | 1 (`scheduled`) |
| class_sessions / session_events / snapshots | Execução syncada | Edge ingest | **0** |
| facial_enrollment_* / facial_student_enrollments | Ops facial **sem embedding** | M2 | 1 (mirror `failed` vs Edge enrolled) |

**Não existe em A:** `face_embeddings`, templates, frames.

### 6.2 Supabase B (LXP sim) — `zasbmqwwkecmjbebejev`

| Tabela | Finalidade | Quem escreve |
|--------|------------|--------------|
| schools, teachers, class_groups, subjects, students | Domínio simulado | Seed |
| lessons, lesson_students | Aulas externas | Seed |
| attendance_records | Frequência | `attendance-events` ← Edge |
| integration_receipts / integration_tokens | Idempotência / auth | Function / setup |

### 6.3 SQLite Edge (local)

| Artefato | Finalidade |
|----------|------------|
| `class_sessions` | Sessão real (incl. automática) |
| `face_embeddings` | **Única** loja de biometria |
| outbox `events` | Sync dual-lane A + B |
| `lesson_cache/today.json` | Cache do dia |

### 6.4 Isolamento biometria

```
Embeddings / FAISS  →  somente Edge SQLite
Status enrolled     →  A (espelho; pode atrasar)
Frequência LXP      →  B (IDs externos; sem face)
```

---

## 7. Integrações

| Integração | Como funciona | Status |
|------------|---------------|--------|
| Cloudflare Tunnel | Named → `:8000` (nunca M2 direto) | Produção homolog |
| M2 enrollment | Loopback `:8766` + proxy Edge | Produção homolog |
| SyncWorker | Outbox → A (product) + B (LXP) | Código presente; cloud A `class_sessions=0` agora |
| Device token ingest | `DEVICE_TOKEN` → A | **Frágil** — `edge_devices=0` live |
| LXP produção (projeto C) | Documentado; **proibido** no sync | Fora do escopo operacional |
| Câmera RTSP/USB | Pipeline orchestrator | 1 câmera online |

### Pipeline visão (real)

```
Câmera
  → YuNet (detect)
  → FaceNet (embed)
  → FAISSMatcher (edge_student_key)
  → PresencePipeline (presença)
  → Analytics / Behavioral / Climate (TRI / engajamento)
  → live/status + classroom-summary + UI Ao vivo
```

---

## 8. Funcionalidades prontas (produção-homologável)

| Capacidade | Evidência |
|------------|-----------|
| Login wall + RBAC SaaS (root/gestor/…) | UI + migrations + E2E login |
| CRUD escolar gestor | AdminShell 9 seções |
| Convite equipe | Edge function + UI Equipe |
| Cadastro facial ponta a ponta | Emerson `p01` · 4 emb · match ~0,84 |
| Criar aula planejada | `lesson_occurrences` |
| Push cache Edge | `POST /lessons/cache` + arquivo cache |
| Iniciar aula com contexto (código+UI professor) | `start-with-context` + botão |
| Ao vivo presença + TRI | Health + E2E Ao vivo |
| Isolamento biometria vs LXP B | Contratos + schemas |
| Tela LXP Homologação | Tab dedicada |

---

## 9. Funcionalidades incompletas / laboratório

| Item | Classificação |
|------|---------------|
| Gestor iniciar aula | **AUSENTE na UI** (intencional no código; bloqueia E2E só-gestor) |
| Professor validado no tenant E2E | Sem membership professor / `teacher_assignments=0` |
| Sync A de sessões no momento | `class_sessions` cloud = 0; devices = 0 |
| Mirror `facial_student_enrollments` | UI enrolled · A = `failed` |
| Tab Admin rede dedicada | Só flags |
| Coordenador no select Equipe | Gap UI |
| React Router / deep links | Não existe |
| LXP produção | Só docs |
| Repo `Presenca` sem facial UI | Atrasado vs worktree |
| Sessão automática sem lesson | Runtime atual (`context: null`) |
| QA tabs / enroll debug | Laboratório |

---

## 10. Gaps críticos (documentação × código × produto)

| Documento afirma | Código faz | Produto mostra | Divergência |
|------------------|------------|----------------|-------------|
| “Professor inicia aula” | Botão só em `ProfessorLimitedView` | Gestor não vê Iniciar; E2E ficou em sessão automática | **GAP operacional** se só gestor loga |
| “Aula inicia e Ao vivo mostra turma” | `start-with-context` grava `lesson_context` | Ao vivo: “Nenhuma aula iniciada” + presença na sessão auto | **GAP** — start formal não rodou |
| “Facial enrolled espelha no cloud” | Dual-write M2 → A | A `failed` · UI `enrolled` | **GAP de sync/status** |
| “Device provisionado para ingest” | Modelos `edge_devices` | 0 devices | **GAP** sync cloud |
| “Coordenador é papel escolar” | DB + `isGestor` | Select Equipe sem opção | **GAP UI** |
| “Presenca repo = produto” | Facial só no worktree | Operação no `_facial_enroll_prod` | **GAP de fonte** |
| `LESSON_CONTEXT_*` YAML pedagógico | Conceito/docs | Runtime = `lesson_occurrences` + cache JSON | **DOC desatualizado** |
| Tenant piloto `4444…` | `.env` / runbooks | Escola live `aaaaaaaa…` E2E | **GAP de tenant** |
| “Path /classroom-summary” | Correto: `/api/v1/live/classroom-summary` | 404 se path errado | Erro de auditoria anterior, não ausência |

---

## 11. Próximos passos recomendados

*(Recomendações apenas — **não executar correções nesta missão**.)*

1. **Fechar E2E aula formal:** convidar/logar **professor** com `teacher_profile_id` na occurrence → clicar **Iniciar aula** → validar `current-context.context ≠ null`.
2. **Ou** decidir produto: gestor também pode iniciar (hoje é gap UX consciente).
3. **Reparar mirror facial** `facial_student_enrollments` (status real = enrolled no Edge).
4. **Provisionar `edge_devices`** se sync A for requisito do piloto.
5. **Unificar fonte de código** (promover `_facial_enroll_prod` → trunk `Presenca`).
6. **Alinhar docs** (tenant, lesson context, professor vs gestor).
7. **Validar LXP B no mesmo dia** após start-with-context + presença.

---

## Apêndice A — Respostas obrigatórias (critério de sucesso)

| Pergunta | Resposta (estado real) |
|----------|------------------------|
| Como uma escola entra no sistema? | ROOT cria org/escola/usuário na **Plataforma**, ou seed; gestor faz login na URL pública. |
| Como um gestor cadastra alunos? | Administração → Alunos (+ matrícula em Turmas); `edge_student_key` automático. |
| Como um aluno cadastra rosto? | Gestor → Cadastro facial → convite/link → celular `/e/{token}` → promote → FAISS. |
| Como uma aula começa? | Gestor cria + envia cache; **professor** clica **Iniciar aula** → `POST /sessions/start-with-context`. |
| Como a câmera gera presença? | Frame → YuNet → FaceNet → FAISS(`edge_student_key`) → PresencePipeline → Ao vivo. |
| Como o professor participa? | Login → Minhas aulas → Iniciar/Encerrar; vê Ao vivo/Relatórios; sem CRUD admin. |
| Como o LXP recebe dados? | Edge SyncWorker → lane LXP → `attendance-events` → Supabase B `attendance_records` (sem biometria). |
| O que é produção vs laboratório? | **Produção-homolog:** auth, admin, facial, visão, presença, TRI, cache aula, start-with-context (código). **Laboratório / incompleto:** sessão automática sem aula, sync A vazio agora, mirror facial, LXP mesmo-dia, QA/enroll debug, LXP prod C. |

---

## Apêndice B — Matriz fluxo de aula (ponto crítico)

| Etapa | Backend | Frontend gestor | Frontend professor | Live agora |
|-------|---------|-----------------|--------------------|------------|
| Criar aula | Sim (A) | Sim | Não | `scheduled` existe |
| Cache Edge | Sim | Sim (botão) | Auto | Cache count=1 |
| Start-with-context | Sim | **Não** | **Sim** | **Não executado** (`context: null`) |
| Sessão automática | Sim | — | — | **Ativa** |
| Presença vision | Sim | Consome Ao vivo | Consome | Emerson presente |
| Sync A sessão | Sim (código) | — | — | cloud sessions=0 |
| Sync B LXP | Sim (código) | Tela homolog | — | sem prova “hoje” |

**Classificação do fluxo aula escolar completo:** **AMARELO** — peças prontas; jornada fechada só com professor iniciando; homologação atual parou no gestor + sessão automática.

---

## Apêndice C — Arquivos-chave

- `frontend/src/App.tsx` — tabs / login wall / guards  
- `frontend/src/cloud/AuthContext.tsx` — papéis  
- `frontend/src/components/views/admin/AdminShellView.tsx` — gestor + `ProfessorLimitedView`  
- `frontend/src/cloud/lessonApi.ts` — cache + start-with-context  
- `frontend/src/components/views/FacialEnrollmentView.tsx`  
- `frontend/src/components/views/LiveClassView.tsx`  
- `app/api/v1.py` · `app/services/lesson_context.py` · `app/pipeline/orchestrator.py`  
- `app/m2_proxy.py` · `experiments/.../enrollment_promote.py`  
- `supabase/migrations/20260922120000_auth_saas_rbac_foundation.sql`  
- `supabase/migrations/20260922153000_auto_edge_student_key.sql`  
- `results/AUDITORIA_E2E_AULA_REAL_20260922.md`  

---

*Fim do mapa. Nenhuma correção automática foi aplicada após esta auditoria.*
