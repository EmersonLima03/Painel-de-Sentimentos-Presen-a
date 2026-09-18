# Auditoria LXP × Integração Sentimentos — 2026-09-17

**Tipo:** somente leitura (Playwright + análise estática do SPA)  
**LXP:** `https://sde.sistemadulino.com.br` (Dulino Skills)  
**Backend LXP:** Supabase `https://kjbygtbgffxggwyukzzl.supabase.co`  
**Sentimentos (referência):** Supabase `rmiaadljzxyehwyuhhgd` + Edge Presença  
**TRI:** não tocado  
**Ações de escrita intencionais nesta auditoria:** **NÃO**

---

## 1. Resumo executivo

O “agendamento / aula” no LXP **não** é uma entidade chamada `aula`. O núcleo operacional é:

| Conceito LXP | Tabela / artefato | Papel |
|--------------|-------------------|--------|
| **Agendamento** | `lab_bookings` | Unidade de aula agendada (título, matéria, turma, professor texto, monitor, início/fim, status, laboratório) |
| **Laboratório (sala/lab)** | `laboratories` | Local físico vinculado a uma entidade da hierarquia (`entity_id`) |
| **Horário de funcionamento** | `lab_schedules` | Horário/feriados do lab — **não** é o agendamento da aula |
| **Chamada** | `attendance_records` | Frequência vinculada a `booking_id` + turma (`entity_id`) |
| **Estrutura escolar** | `hierarchy` | Empresa → Projeto → Escola → Turma |
| **Calendário geral** | `calendar_events` + overlays de bookings/registros | Visão unificada do dia |

**Pergunta-chave:** *como o Sentimentos sabe qual aula está acontecendo?*  
Resposta baseada no LXP observado: pelo **`lab_bookings.id`** (e/ou pelo trio `lab_id` + `start_time`/`end_time` + `target_entity_id`), eventualmente enriquecido por `check_in` (timestamp/GPS do monitor) e pela chamada (`attendance_records`).

Há distinção parcial entre **horário agendado** (`start_time`/`end_time`) e **presença efetiva do monitor** (`check_in.timestamp` + “Validar Presença”). Não foi observada, na UI auditada, uma entidade separada “aula iniciada pelo professor às 08:07” além desse check-in / status do booking.

---

## 2. Mapa de navegação relevante (Owner)

Rotas hash confirmadas na UI autenticada:

| Nome exibido | Rota | Função | Entidades |
|--------------|------|--------|-----------|
| Painel | `#/dashboard` | Painel Owner (licenças, atalhos) | tenant, licenses, courses |
| Calendário | `#/calendar` | Agenda do dia/mês | `calendar_events`, agendamentos de lab, registros de aula |
| Licenças | `#/licenses` | Licenças e usuários | licenses, users |
| Hierarquia | `#/hierarchy` | Projetos / escolas / turmas | `hierarchy` |
| Laboratórios | `#/laboratories` | Labs + links agenda | `laboratories` |
| Ver Agendamentos | `#/labs/:labId/schedules` | Lista de `lab_bookings` | bookings, monitors, turmas |
| Calendário do lab | `#/labs/:labId/calendar` | Horário funcionamento / feriados | `lab_schedules` |
| Chamada | `#/attendance` | Registro de chamada | `attendance_records`, turmas, bookings |
| Diário de Classe | `#/class-diary` | Observações por aluno/turma | diary + turma |
| Registro de Aula | `#/class-records` | Fotos/evidência + vínculo a agendamento | `class_records` |
| Gerenciar Usuários | `#/manage-users` | Cargos e vínculos de turmas | `users`, hierarchy links |
| Cursos / Academias | `#/finances`, `#/academies`, … | LMS (fora do núcleo sala física) | courses, academies |

Menus Owner (sidebar) também incluem Fórum, Formações, Diário de Bordo, Hub, Desempenho, Videoconferência, etc. — fora do escopo escolar de presença.

**Páginas relevantes auditadas ao vivo:** 9  
(dashboard, hierarchy, laboratories, lab schedules, attendance, class-records, calendar, class-diary, manage-users)

---

## 3. Estrutura escolar (nomes reais do LXP)

Confirmado na UI Hierarquia (`#/hierarchy`, projeto **Ipecaetá** expandido):

```
Empresa (ex.: Dulino Skills)
  └─ Projeto (ex.: Ipecaetá, Igarassu, …)   [12 projetos na paginação]
       └─ Escola (ex.: Hildo Rocha Trindade, Laudelino Gonçalves de Moura)
            └─ Turma (ex.: 6º ano A, 6º ano B, 7º ano A, …)
```

- UI: *“Organize projetos, escolas e turmas. 562 entidades cadastradas”*.
- Turmas mostram cota de licenças: ex. `34 / 50 usuários`.
- Tipos de entidade observados na UI: **Projeto**, **Escola**, **Turma** (+ empresa do projeto).
- Campos de `hierarchy` (código SPA):  
  `id, name, type, user_ids, children, license_limit, academy_ids, user_roles, is_active, tenant_id, stages`.

**Não assumir** equivalência 1:1 com `organizations/schools/class_groups` do Sentimentos sem mapeamento explícito de `hierarchy.id` → `external_ref`.

---

## 4. Estrutura de usuários

Roles observados no SPA / UI:

| Role LXP | Notas |
|----------|--------|
| Owner / Root / Admin / Manager | administração |
| Monitor | opera lab, chamada, agendamentos |
| Teacher / Professor | menus de chamada/diário |
| Student / StudentB2C | aluno institucional vs B2C |
| Instructor | cursos |

`users` (selects SPA): `id, name, nickname, email, role, avatar, …`

Gerenciar usuários: *“Controle de acessos, cargos globais e vínculos de turmas”* — ~15136 usuários (bate com painel 15134 licenças).

Alunos aparecem como usuários com papel **ALUNO INSTITUCIONAL** / **ALUNO B2C**, vinculados à hierarquia via `user_ids` / `user_roles` nas entidades — **não** há tabela `enrollments` no client LXP (diferente do Sentimentos).

---

## 5. Turmas

- Entidade `hierarchy` com `type` = Turma.
- Exemplo real: sob escola Hildo Rocha Trindade → `6º ano A` … `9º ano`.
- Agendamentos referenciam turma via **`target_entity_id`** (FK lógica para `hierarchy.id`).
- Chamada filtra por turma; diário exige seleção de turma.

---

## 6. Alunos / “matrículas”

| Aspecto | O que o LXP mostra |
|---------|-------------------|
| Cadastro | Usuário (`users`) papel aluno |
| ID | `users.id` (UUID) |
| Vínculo turma | hierarquia `user_ids` / papéis na entidade |
| Status matrícula | **não** há tabela `enrollments` no client; cota `license_limit` na turma |
| Transferência / entrada-saída | **não confirmado** nesta auditoria (UI de edição não aberta) |

Chamada armazena lista JSON `students[]` com pelo menos `studentId`, `status` (Presente/Ausente/Atrasado), `observation` (justificativa/edição).

---

## 7. Professores

No agendamento (`lab_bookings`):

| Campo | Tipo | Significado |
|-------|------|-------------|
| `professor_name` | **texto livre** | “Prof. Bella”, “Prof. Professor” |
| `monitor_id` | UUID → `users` | Monitor responsável (usuário do sistema) |
| `subject` | **texto livre** | “Ciências”, “Mat”, “Geografia” |

Implicações:

- Professor **não** é FK tipada no booking (pelo menos no select usado pela UI).
- Monitor ≠ professor: UI lista ambos.
- Substituição / professor responsável ≠ quem iniciou: possível via texto + monitor diferente; **sem** workflow formal de “substituto” confirmado.
- Um monitor pode ter vários bookings; um professor (texto) aparece em várias turmas.

---

## 8. Disciplinas

- **Não** existe tabela `subjects` / `disciplinas` no client LXP auditado.
- Disciplina = campo texto **`subject`** (“Matéria”) no `lab_bookings`.
- Calendário: *“Agendamento de laboratório - Matemática/Geografia/…”*.

Sentimentos tem `subjects` tipado — mapeamento futuro seria por string ou catálogo externo, não por ID LXP estável hoje.

---

## 9. Salas / laboratórios

| Campo | Origem |
|-------|--------|
| `laboratories.id` | UUID do lab |
| `name` | ex. “Laboratório Teste”, “Laboratório Presidente Costa e Silva” |
| `entity_id` | entidade da hierarquia (escola/unidade) |

Agendamento **sempre** tem `lab_id` → laboratório.  
Capacidade de sala: **não** vista em `laboratories` (só id/name/entity_id no select). Cota vista é de **usuários na turma** (`license_limit`), não assentos da sala.

`lab_schedules`: `operating_hours`, `holidays`, `monthly_booking_limits` — calendário operacional do lab.

---

## 10. Agendamentos (núcleo)

### Onde aparece

- `#/labs/:labId/schedules` — lista principal  
- `#/calendar` — tipo **AGENDAMENTO** no dia  
- Chamada — coluna “Atividade / Agendamento”  
- Registro de aula — vínculo opcional ao agendamento  

### Campos confirmados (`lab_bookings`)

```
id
lab_id
monitor_id
activity_title
start_time
end_time
status
subject
professor_name
justification
cancel_requested
pending_changes
target_entity_id
check_in            // { timestamp, location, inconsistencyNote }
checkin_photo_url
checkin_photo_path
```

### Status de booking (UI + enum SPA)

- Agendado  
- Concluído / Finalizado  
- Cancelado  
- Aguardando Aprovação  

### Exemplos reais (Laboratório Teste)

| Status | Duração UI | Título | Início UI | Matéria | Turma | Professor | Monitor |
|--------|------------|--------|-----------|---------|-------|-----------|---------|
| Aguardando Aprovação | 6 MINUTOS | Teste | 15/09/2026, 15:35 | Mat | Turma A | Bella | Monitor Dulino |
| Finalizado | 3 MINUTOS | Teste agora | 08/05/2026, 16:37 | Ciências | Turma A | Professor | Monitor Dulino |
| Agendado / Cancelado | 60 MINUTOS | Planetas e sistema solar | 08/04/2026, 08:00 | Ciências | Turma B | Professor | Monitor Dulino |

**Identificação de uma aula 08:00–08:50 Turma X Prof Y Disc Z Sala W:**  
no LXP isso é um **`lab_bookings`** com `start_time`/`end_time`, `target_entity_id`=turma, `professor_name`, `subject`, `lab_id`.

### Horário agendado vs início efetivo

| Conceito | Existe? | Evidência |
|----------|---------|-----------|
| Horário agendado | **Sim** | `start_time`, `end_time` |
| Duração | **Derivada** | `(end−start)` → “N MINUTOS” |
| Check-in do monitor | **Sim** | `check_in.timestamp` + GPS + foto; botão “Validar Presença” |
| “Aula aberta às 08:07” tipada | **Não confirmado** como entidade própria | UI calcula early/normal/late vs janela agendada |
| Chamada iniciada | **Sim (registro)** | `attendance_records` com `date` + `booking_id` |

---

## 11. Aulas de 50 e 100 minutos

**O que o sistema mostra (sem inventar):**

- Duração = diferença `end_time − start_time`, exibida como **“N MINUTOS”**.
- Exemplos observados: **3, 6, 60** minutos.
- Literais `50` e `100` existem no chunk de UI de schedules (provável suporte a duração livre / presets), **sem** label “aula dupla” ou “bloco” na UI auditada.
- **Não** há evidência de entidade “bloco” ou “aula dupla”.
- 100 minutos = **um** `lab_booking` com janela de 100 min **ou** dois bookings consecutivos — **ambos possíveis em tese**; nos exemplos desta auditoria só vimos um booking por linha com duração própria.
- Recorrência: **não** confirmada nos campos do select de bookings (sem `rrule`/`recurrence` no payload listado).

---

## 12. Chamada / frequência

Tela `#/attendance` — **Registro de Chamada** (579 resultados no Owner).

Colunas UI:

- Data  
- Turma  
- Atividade / Agendamento  
- Presentes / Total  
- Ações  

Exemplos do dia **17/09/2026**:

| Turma | Atividade | Presentes/Total |
|-------|-----------|-----------------|
| 6º ano A | SEMANA TEMÁTICA DA AMAZONIA | 22/23 |
| 5º ano A | Sistema monetário | 14/15 |
| 7º ano B | A Música como Manifestação Artística | 12/37 |

Modelo `attendance_records`:

```
id, entity_id, booking_id, date, monitor_id, students, edits, tenant_id
```

Status por aluno (enum SPA): **Presente**, **Ausente**, **Atrasado** (+ observation/justificativa via edição).

UI menciona: vincular agendamento; “Nenhum agendamento encontrado para esta turma nesta data”; edição de justificativas.

**Sentimentos não deve substituir a chamada LXP** — pode complementar com observação TRI da sessão.

---

## 13. Identificadores

| Conceito Sentimentos | ID real no LXP | Notas |
|----------------------|----------------|-------|
| organização / tenant | `tenants.id`, `hierarchy.tenant_id` | Tenant exemplo visto em rede: `f789d0ff-703f-431e-bdfe-fa7deca87ac4` |
| escola | `hierarchy.id` (type Escola) | |
| turma | `hierarchy.id` (type Turma) = `target_entity_id` | |
| aluno | `users.id` | também `students[].studentId` na chamada |
| professor | **sem ID estável no booking** | `professor_name` texto |
| monitor | `users.id` = `monitor_id` | |
| disciplina | **sem ID** | `subject` texto |
| sala/lab | `laboratories.id` = `lab_id` | |
| agendamento | **`lab_bookings.id`** | chave principal |
| enrollment | **não tipado** | vínculo via hierarchy.user_ids |
| course | `courses.id` | LMS, não aula presencial |
| chamada | `attendance_records.id` | |

Lab exemplo: `bb82700b-105f-4a74-a403-6871c647f148` (Laboratório Teste).

---

## 14. Endpoints GET observados (leitura)

Backend: PostgREST Supabase LXP (`/rest/v1/...`).  
**Não** GraphQL.

### GETs relevantes confirmados em network (sessão Owner)

| Método | Endpoint (padrão) | Uso |
|--------|-------------------|-----|
| GET | `/rest/v1/hierarchy?select=id,name,type,user_ids,user_roles,children,license_limit,is_active` | hierarquia |
| GET | `/rest/v1/laboratories?select=id,name,entity_id` | labs |
| GET | `/rest/v1/lab_schedules?select=*&lab_id=eq.{labId}` | horário do lab |
| GET | `/rest/v1/lab_bookings?select=id,lab_id,monitor_id,activity_title,start_time,end_time,status,subject,professor_name,...&lab_id=eq.{labId}` | agendamentos |
| GET | `/rest/v1/users?select=...&role=eq.Monitor` | monitores |
| GET | `/rest/v1/users?select=*&id=eq.{uid}` | perfil |
| GET | `/rest/v1/tenants?select=*&id=eq.{tid}` | tenant |
| GET | `/rest/v1/courses?select=...&status=eq.Aguardando+Aprovação` | cursos pendentes |
| GET | `/rest/v1/notifications?...` | notificações |
| GET | `/rest/v1/announcements?...` | comunicados |
| POST* | `/rest/v1/rpc/get_tenant_by_domain` | resolve tenant (RPC leitura) |
| POST* | `/rest/v1/rpc/tenant_license_usage` | métrica licenças |

\*RPC PostgREST usa POST; efeito observado = leitura de métricas/tenant.

### Quantidade

- **GET REST relevantes catalogados:** ≥ 10 padrões  
- **Chunks SPA analisados:** index + LabSchedules, Attendance, Hierarchy, ClassRecords, ClassDiary, ManageUsers, LabCalendar  

Estrutura de resposta: arrays JSON de linhas PostgREST (campos snake_case como na seção 10).

---

## 15. Modelo de dados inferido (aula presencial)

```
tenants
users (role: Owner|Monitor|Teacher|Student|…)
hierarchy (tree: Empresa/Projeto/Escola/Turma)
laboratories (lab ↔ hierarchy.entity_id)
lab_schedules (hours/holidays do lab)
lab_bookings (AGENDAMENTO = aula)
    ├─ lab_id → laboratories
    ├─ target_entity_id → hierarchy (Turma)
    ├─ monitor_id → users
    ├─ professor_name, subject (texto)
    └─ check_in {timestamp, location, …}
attendance_records
    ├─ booking_id → lab_bookings
    ├─ entity_id → hierarchy (Turma)
    └─ students[{studentId, status, observation}]
class_records (evidência fotográfica; linked_booking_id)
calendar_events (eventos genéricos; coexistentes no calendário)
```

---

## 16–17. Comparação LXP × Sentimentos / Fonte de verdade

| Entidade | Fonte de verdade proposta | ID LXP | ID Sentimentos | Sincronizar? |
|----------|---------------------------|--------|----------------|--------------|
| organização / tenant | **LXP** (operacional escolar) | `tenants.id` / hierarchy | `organizations.id` | Sim (mapa `external_ref`) |
| escola | **LXP** `hierarchy` type Escola | `hierarchy.id` | `schools.id` | Sim |
| turma | **LXP** `hierarchy` type Turma | `hierarchy.id` | `class_groups.id` | Sim |
| aluno | **LXP** `users` | `users.id` | `students.id` | Sim |
| matrícula | **LXP** (vínculo hierarchy) | implícito | `enrollments` | Sim (derivar/espelhar) |
| professor | **LXP** (hoje frágil: texto) | `professor_name` / user? | `profiles` + `teacher_assignments` | Parcial — precisa decisão de ID |
| disciplina | **LXP** texto `subject` | string | `subjects.id` | Catálogo Sentimentos ou normalizar LXP |
| sala / lab | **LXP** `laboratories` | `lab_id` | `rooms.id` | Sim |
| agendamento | **LXP** `lab_bookings` | **`lab_bookings.id`** | *(ainda não existe tabela dedicada; `class_sessions.scheduled_*`)* | Sim — **chave de contexto** |
| sessão de observação | **Sentimentos / Edge** | — | `class_sessions.id` | Não duplicar no LXP |
| eventos TRI / indicadores | **Sentimentos** | — | `session_events` | Não |
| chamada / frequência oficial | **LXP** | `attendance_records.id` | — | Não substituir; opcional espelho |
| câmeras / Edge device | **Sentimentos** | — | `cameras`, `edge_devices` | LXP não cobre |

### O que **não** duplicar no Sentimentos

- Cadastro canônico de alunos/turmas/escolas (espelhar com `external_ref`).  
- Criação/edição de agendamentos e chamada oficial.  
- LMS (cursos, academias, missões, loja).  

### O que **é** do Sentimentos

- Sessão de observação (`class_sessions`), TRI, eventos, snapshots, offline/outbox, dashboard pedagógico, câmeras.

---

## 18. Dados mínimos offline (conceitual — não implementar)

Para o Edge funcionar sem internet, cache mínimo sugerido:

1. `lab_bookings` do dia (ou janela ±N h) filtrados pelo `lab_id` / escolas do device  
2. Mapa `lab_id` ↔ `rooms` / câmeras Sentimentos  
3. `target_entity_id` → turma Sentimentos (`class_groups.external_ref`)  
4. Lista de alunos da turma (ids + nomes) para overlay  
5. `scheduled_start` / `scheduled_end` / `subject` / `professor_name` / `monitor_id`  
6. `lab_bookings.id` como **foreign context** da `class_sessions`  

Fluxo:

```
LXP lab_bookings (contexto)
    ↓ cache local
Edge class_sessions (observação) + TRI
    ↓ outbox
Supabase Sentimentos (histórico)
    ↓ (futuro) opcional notificar/espelhar LXP
```

---

## 19. Fluxo proposto LXP → Sentimentos

```
1. Device/sala conhece laboratories.id (ou room.external_ref)
2. Ao iniciar sessão Sentimentos:
   - buscar lab_bookings onde now ∈ [start_time, end_time] e lab_id = sala
   - senão: booking mais próximo / escolha do monitor
3. Gravar em class_sessions:
   - scheduled_start_at / scheduled_duration_minutes
   - class_group_id (via target_entity_id)
   - external booking id (campo a criar na Fase 5 — NÃO criado nesta auditoria)
4. TRI roda independentemente
5. Chamada continua no LXP; Sentimentos não marca falta
```

Se o professor chega às **08:07**:

- LXP continua com booking 08:00–08:50.  
- `check_in.timestamp` pode registrar presença efetiva do monitor.  
- Sentimentos deve usar **início da sessão Edge** (`started_at`) como tempo real de observação, sem exigir que o LXP mude o agendamento.

---

## 20. Pontos ainda desconhecidos

1. Schema completo de `hierarchy.type` (todos os valores oficiais) e regras de `user_roles` por nó.  
2. Se existe (ou existirá) FK de professor além de `professor_name`.  
3. Recorrência de agendamentos (série semanal).  
4. Política exata de 50 vs 100 min na operação Dulino (convenção humana vs regra de sistema).  
5. Payload completo de um `attendance_records.students[]` em produção (só inferido do JS).  
6. API oficial / contrato estável LXP→integrações (hoje: PostgREST direto do SPA).  
7. RLS/policies do projeto `kjbygtbgffxggwyukzzl` (não auditadas via service role).  
8. Mapeamento multi-tenant: um Edge Sentimentos ↔ qual `tenant_id` / projetos.  
9. Se “Validar Presença” altera só `check_in` ou também `status` do booking (não clicado).  
10. Diário de classe: estrutura completa após selecionar turma (não aprofundado).

---

## 21. Recomendações para a Fase 5

1. **Tratar `lab_bookings.id` como ID de contexto de aula** — não reinventar agendamento no Sentimentos.  
2. Adicionar no Sentimentos (quando for implementar): `external_ref` / `lxp_booking_id` em `class_sessions` + sync de hierarquia via `external_ref`.  
3. Mapear `laboratories` → `rooms` (1 lab LXP = 1 sala observada).  
4. Não depender de `subject`/`professor_name` como IDs — normalizar depois ou aceitar texto na sessão.  
5. **Não** sincronizar chamada LXP como fonte de eventos TRI; no máximo correlacionar por `booking_id` + data.  
6. Spec HTTP: preferir Edge Function/API estável LXP em vez de o Edge falar PostgREST cru com JWT de usuário.  
7. Offline: cachear bookings do dia por `lab_id`.  
8. Manter TRI congelado; Fase 5 = produto/integração apenas.  
9. Próximo passo de auditoria (se necessário): abrir **um** “Ver Detalhes” + um registro de chamada existente **sem editar**, e documentar JSON completo — ainda somente leitura.

---

## Apêndice A — Controles da auditoria

| Item | Valor |
|------|-------|
| Páginas relevantes auditadas | **9** |
| Endpoints GET/RPC leitura relevantes observados | **≥ 10** |
| Escrita intencional (criar/editar/excluir/aprovar/matricular/chamada) | **NÃO** |
| Escrita automática do LXP no login da sessão Playwright | `user_sessions` upsert + `audit_logs` insert (efeito colateral de autenticação; não é alteração escolar deliberada) |
| Alteração de código Sentimentos / TRI / LXP | **NÃO** |
| Commit | **NÃO** |

### Confirmado

- Hierarquia Empresa → Projeto → Escola → Turma  
- Agendamento = `lab_bookings` ligado a lab + turma + monitor  
- Duração livre via start/end  
- Chamada vinculável a agendamento; status Presente/Ausente/Atrasado  
- Check-in de presença do monitor  
- Calendário mistura AGENDAMENTO e REGISTRO DE AULA  

### Desconhecido / parcial

Itens da seção 20; estrutura interna completa de alunos na turma sem abrir edição; detalhes de um booking via modal “Ver Detalhes” (clique instável/timeout — não forçado).

---

*Documento gerado em 2026-09-17. Auditoria somente leitura para planejamento da Fase 5 — sem implementação.*
