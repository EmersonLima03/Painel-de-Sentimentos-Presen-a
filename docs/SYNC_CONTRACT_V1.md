# Sync Contract v1

Outbox local: tabela SQLite `events` (`event_id` unique, `status` pending/sent/failed).

## Tipos de produto (lane cloud MVP)

Únicos tipos selecionados pelo SyncWorker (filtro **antes** do LIMIT):

| event_type | Idempotency key | Destino |
|------------|-----------------|---------|
| `class_session_upsert` | `session:{id}:{status}` | `class_sessions` UPSERT by `id` |
| `session_event_upsert` | `evt:{event_id}:{lifecycle}` | `session_events` UPSERT by `id` |
| `session_report_snapshot` | `snap:{session_id}:{epoch}:{final}` | `session_report_snapshots` UPSERT `(session_id,captured_at)` |
| `device_heartbeat` | `hb:{device}:{minute}` | `edge_devices.last_seen_at` |

Prioridade no lote: session → event → snapshot → heartbeat, depois `created_at`.

## Telemetria local (não sincroniza no MVP)

`climate_window`, `engagement_window`, `behavioral_event`, `attendance_checkin`, `test`

Permanecem no SQLite para relatórios/TRI locais. **Não** são enviados individualmente ao cloud.
Não apagar; o SyncWorker simplesmente não os seleciona (não bloqueiam a fila).

Relatório pedagógico cloud: `session_report_snapshot`.

## Respostas ingest

| status | HTTP | Worker |
|--------|------|--------|
| inserted / duplicate / ignored | 200 | mark_sent |
| unauthorized / invalid | 4xx | mark_failed (não retry cego) |
| retryable_error | 5xx | mark_failed + retries |

## Proibições no payload

`embedding`, `face_template`, `frame_jpeg`, `video_base64`, `rtsp_url`.
