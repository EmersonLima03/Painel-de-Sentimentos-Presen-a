# Sync Contract v1

Outbox local: tabela SQLite `events` (`event_id` unique, `status` pending/sent/failed).

## Tipos de produto

| event_type | Idempotency key | Destino |
|------------|-----------------|---------|
| `class_session_upsert` | `session:{id}:{status}` | `class_sessions` UPSERT by `id` |
| `session_event_upsert` | `evt:{event_id}:{lifecycle}` | `session_events` UPSERT by `id` |
| `session_report_snapshot` | `snap:{session_id}:{epoch}:{final}` | `session_report_snapshots` UPSERT `(session_id,captured_at)` |
| `device_heartbeat` | `hb:{device}:{minute}` | `edge_devices.last_seen_at` |

Legado (`behavioral_event`, `attendance_checkin`, …): ingest responde `ignored` (ok para mark_sent).

## Respostas ingest

| status | HTTP | Worker |
|--------|------|--------|
| inserted / duplicate / ignored | 200 | mark_sent |
| unauthorized / invalid | 4xx | mark_failed (não retry cego) |
| retryable_error | 5xx | mark_failed + retries |

## Proibições no payload

`embedding`, `face_template`, `frame_jpeg`, `video_base64`, `rtsp_url`.
