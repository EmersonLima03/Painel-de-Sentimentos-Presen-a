# Architecture Sentimentos v1

Backend central: **Supabase Sentimentos** (`rmiaadljzxyehwyuhhgd`).  
Edge: Presença FastAPI + TRI (congelado) + SQLite outbox.

## Separação

| Camada | Responsável |
|--------|-------------|
| Supabase | Auth, roles, org/escola/turma/aluno, histórico, sessões/eventos/snapshots syncados, RLS |
| Edge | TRI, vídeo, embeddings, LiveSessionStore, SQLite, outbox, SyncWorker |

**Não sobe:** vídeo, embeddings, RTSP secrets.

## Fluxo sync

```
TRI → SQLite → outbox(events) → SyncWorker → Edge Function ingest-events → Supabase
```

Offline: outbox permanece `pending`. Ao voltar a rede: retry idempotente.

## IDs

- `class_sessions.id` = UUID nascido no Edge
- `session_events.id` = `event_id` do Edge
- Cloud **não** regenera esses IDs

## Env Edge

```
SUPABASE_INGEST_URL=https://rmiaadljzxyehwyuhhgd.supabase.co/functions/v1/ingest-events
SUPABASE_ANON_KEY=<publishable/anon>
DEVICE_TOKEN=<plaintext token provisionado>
CLOUD_ORGANIZATION_ID=11111111-1111-1111-1111-111111111111
CLOUD_SCHOOL_ID=22222222-2222-2222-2222-222222222222
```

## Env Frontend cloud

```
VITE_SUPABASE_URL=https://rmiaadljzxyehwyuhhgd.supabase.co
VITE_SUPABASE_ANON_KEY=<anon>
```

## TRI

Intocado: `app/vision/*`, `config.tri.yaml`, thresholds, phone/emotion/tracking.
