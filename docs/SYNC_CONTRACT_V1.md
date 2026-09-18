# Sync Contract v1

Outbox local: tabela SQLite `events` (`event_id` unique, `status` pending/sent/failed).

## Tipos de produto (lane cloud MVP → Sentimentos)

Únicos tipos selecionados pelo SyncWorker para o ingest Sentimentos (filtro **antes** do LIMIT):

| event_type | Idempotency key | Destino |
|------------|-----------------|---------|
| `class_session_upsert` | `session:{id}:{status}` | `class_sessions` UPSERT by `id` (incl. `external_lesson_id`) |
| `session_event_upsert` | `evt:{event_id}:{lifecycle}` | `session_events` UPSERT by `id` |
| `session_report_snapshot` | `snap:{session_id}:{epoch}:{final}` | `session_report_snapshots` UPSERT `(session_id,captured_at)` |
| `device_heartbeat` | `hb:{device}:{minute}` | `edge_devices.last_seen_at` |

## Lane LXP (→ Attendance Simulator)

| event_type | Idempotency key | Destino |
|------------|-----------------|---------|
| `lxp_attendance_event` | `lxp-att:{checkin_event_id}` | Edge Function `attendance-events` no projeto simulador |

Prioridade no lote: session → event → snapshot → heartbeat → lxp_attendance, depois `created_at`.

Contrato: `docs/LXP_ATTENDANCE_CONTRACT_V1.md`.

## Telemetria local (não sincroniza no MVP)

`climate_window`, `engagement_window`, `behavioral_event`, `attendance_checkin`, `test`

Permanecem no SQLite para relatórios/TRI locais. **Não** são enviados individualmente ao cloud.
O check-in local **pode** gerar um `lxp_attendance_event` separado se houver identidade + aula externa.

Relatório pedagógico cloud: `session_report_snapshot`.

## Respostas ingest / LXP

| status | HTTP | Worker |
|--------|------|--------|
| inserted / duplicate / ignored / accepted | 200 | mark_sent |
| unauthorized / invalid | 4xx | mark_failed (não retry cego) |
| retryable_error | 5xx | mark_failed + retries |

## Proibições no payload

`embedding`, `face_template`, `frame_jpeg`, `video_base64`, `rtsp_url`.
