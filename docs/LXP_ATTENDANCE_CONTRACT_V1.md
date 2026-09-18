# Contrato API — Chamada assíncrona Sentimentos → LXP Attendance Simulator

**Versão:** `attendance.events.v1`  
**Data:** 2026-09-18  
**Escopo:** homologação apenas no projeto Supabase `zasbmqwwkecmjbebejev`  
**Proibido:** qualquer chamada ao LXP de produção (`sde.sistemadulino.com.br` / `kjbygtbgffxggwyukzzl`)

---

## Endpoint

```
POST https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events
```

`verify_jwt=false` — autenticação custom por token de integração.

### Leitura (homolog / admin)

```
GET .../attendance-events?token=TOKEN&view=lessons|attendance|receipts
```

---

## Autenticação

| Header / query | Valor |
|----------------|--------|
| `X-Integration-Token` | plaintext provisionado ao Edge |
| ou `?token=` | idem |
| `Authorization: Bearer ANON_KEY` + `apikey` | gateway Supabase (anon do **simulador**) |

O plaintext **não** vai no frontend/React. Apenas:

```
LXP_SIM_INTEGRATION_TOKEN=...
LXP_SIM_ATTENDANCE_URL=https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events
LXP_SIM_ANON_KEY=...
MODULE_LXP_MODE=simulator
LXP_EXTERNAL_LESSON_ID=lesson-8b-math-50
```

No simulador, o hash SHA-256 do token fica em `integration_tokens.token_hash`.

---

## Payload POST

```json
{
  "event_id": "lxp-att:<edge-checkin-uuid>",
  "lesson_id": "lesson-8b-math-50",
  "student_id": "ext-stu-001",
  "attendance": "present",
  "occurred_at": "2026-09-18T11:00:00+00:00",
  "source": "sentimentos",
  "contract_version": "attendance.events.v1"
}
```

| Campo | Obrigatório | Notas |
|-------|-------------|--------|
| `event_id` | sim | Idempotência global |
| `lesson_id` | sim | = `lessons.external_lesson_id` |
| `student_id` | sim | = `students.external_student_id` |
| `attendance` | sim | `present` \| `absent` \| `late` |
| `occurred_at` | sim | ISO-8601 |
| `source` | não | default `sentimentos` |
| `contract_version` | não | default `attendance.events.v1` |

Aliases aceitos: `external_lesson_id`, `external_student_id`, `status`.

---

## Respostas

| HTTP | `status` | Significado | Worker Edge |
|------|----------|-------------|-------------|
| 200 | `accepted` + `result=inserted` | primeira gravação | `mark_sent` |
| 200 | `accepted` + `result=duplicate` | mesmo `event_id` | `mark_sent` |
| 400 | `invalid` | payload | `mark_failed` (sem retry cego) |
| 401 | `unauthorized` | token | `mark_failed` |
| 404 | `invalid` (`lesson_not_found` / `student_not_found` / `student_not_in_lesson`) | domínio | `mark_failed` |
| 500 | `retryable_error` | falha servidor | retry com backoff |

Exemplo sucesso:

```json
{
  "ok": true,
  "status": "accepted",
  "result": "inserted",
  "event_id": "lxp-att:…",
  "attendance_id": "…",
  "contract_version": "attendance.events.v1"
}
```

---

## Idempotência

- UNIQUE(`attendance_records.source_event_id`)
- UNIQUE(`attendance_records.lesson_id, student_id, source`)
- `integration_receipts.event_id` UNIQUE (auditoria)

Reenviar o mesmo `event_id` 1×, 2× ou 10× → **um** registro de presença.

---

## Fluxo Edge

```
attendance_checkin (identidade válida)
  → maybe_enqueue_lxp_attendance_from_checkin
  → outbox event_type=lxp_attendance_event
  → SyncWorker
  → LxpAttendanceClient
  → attendance-events (simulador)
```

Sem `student_id` confiável ou sem `LXP_EXTERNAL_LESSON_ID` → **não envia** (não inventa presença).

Offline: outbox `pending` → retry ao voltar rede.

---

## Dados seed (simulador)

| Entidade | Valor |
|----------|--------|
| Escola | Escola Demo |
| Turma | 8º Ano B |
| Disciplina | Matemática |
| Aula 50 min | `lesson-8b-math-50` (08:00–08:50 UTC do dia) |
| Aula 100 min | `lesson-8b-math-100` (bloco 100 min) |
| Alunos | `ext-stu-001`…`003` ↔ edge `p01`…`p03` |

---

## Versionamento

Campo `contract_version`. Breaking changes exigem `attendance.events.v2` e dual-run.
