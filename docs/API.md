# API e WebSocket

## Autenticação

- Variável `API_AUTH_TOKEN`.
- Se **vazia**: modo aberto (desenvolvimento).
- Se definida: exigir `X-API-Token`, `Authorization: Bearer …` ou `?api_token=`.
- `/debug/vision` e `/api/v1/live/debug-snapshot`: além do token, **localhost** por padrão (`debug_vision_allow_remote=false`).

**Nunca** retornar: embeddings, senhas, RTSP completa com credencial, frames persistidos.

## Endpoints `/api/v1`

Prefixo do router: `/api/v1`. Em modo demo, payloads incluem `runtime_mode`, `is_simulated`, `disclaimer` e `banner`.

### Live

| Método | Path | Finalidade | Auth | Notas |
|--------|------|------------|------|-------|
| GET | `/live/status` | Modo, módulos, sessão, KPIs | sim | Demo: kpis do `DemoEngine` |
| GET | `/live/tracks` | Tracks + bindings | sim | |
| GET | `/live/classroom-summary` | Presentes/visíveis/observáveis/atenção/clima | sim | |
| GET | `/live/debug-snapshot` | Snapshot técnico | sim + localhost | Sem embeddings |

### Sessions

| Método | Path | Finalidade |
|--------|------|------------|
| GET | `/sessions` | Lista (demo: sessão atual) |
| GET | `/sessions/{id}` | Detalhe |
| GET | `/sessions/{id}/summary` | Relatório / limitações |
| GET | `/sessions/{id}/timeline` | Eventos de timeline |
| GET | `/sessions/{id}/students` | Presença simulada / alunos |
| GET | `/sessions/{id}/engagement` | Atenção por track |
| GET | `/sessions/{id}/climate` | Clima dominante |
| GET | `/sessions/{id}/behavioral-events` | Eventos comportamentais |

Fora do demo, várias rotas de sessão retornam vazio / 404 até persistência shadow completa.

### Review

| Método | Path | Finalidade |
|--------|------|------------|
| GET | `/review/events` | Fila (`?status=`) |
| GET | `/review/events/{id}` | Detalhe |
| PATCH | `/review/events/{id}` | Body: `{ "status": "confirmed\|rejected\|inconclusive\|pending", "notes": "..." }` |

### System

| Método | Path | Finalidade |
|--------|------|------------|
| GET | `/system/health` | `{ status: ok }` |
| GET | `/system/models` | Detector/embedder/provider (sem segredos) |
| GET | `/system/performance` | Latências / FPS demo |
| GET | `/system/configuration` | device, provenance versions, runtime |

### Demo

| Método | Path | Finalidade |
|--------|------|------------|
| POST | `/demo/control` | `{ playing?, speed?, reset? }` — só em demo |
| GET | `/demo/report` | Relatório JSON |
| GET | `/demo/report.csv` | Export CSV |
| POST | `/demo/lxp/flush` | Processa outbox mock |

### WebSocket

- **URL:** `WS /api/v1/ws/live?api_token=…` (se token definido)
- **Eventos (tipos):** `system_status`, `classroom_summary`, `live_tracks`, `heartbeat`, `review_queue_update` (e outros planejados no hub)
- Cliente pode enviar `ping` → `heartbeat`
- Timeout ~30s com heartbeat do servidor
- Demo: ticker ~1s com `is_simulated: true`
- Reconexão: responsabilidade do frontend (backoff no React)

## Rotas legadas relevantes (`app/main.py`)

Ainda usadas operacionalmente (não fazem parte do contrato v1 puro):

- `GET /health`, `/cameras`, `/cameras/devices`
- Cadastro: `POST /enroll`, `/enroll/webcam`, …
- Sessões: `POST /sessions/start`, `…/end`
- Dashboard: `/dashboard`, `/dashboard-legacy`, `/dashboard/api/*`
- Debug: `/debug/vision`, `/debug/mjpeg`, `/debug/snapshot`
- Privacy: consent / delete student
- Backup: `/backup/export`, `/backup/restore`

## Snapshot analítico por track (RTSP)

`GET /api/v1/live/debug-snapshot` e `GET /api/v1/live/tracks` publicam tracks com:

- `observation_quality` (scores + `status`: observable|low_quality|inconclusive|error)
- `facial_features` (olhos, boca, yaw/pitch/roll, `provider`, `status`)
- `expression` (FER legado ou `unavailable`/`inconclusive`)
- `visual_attention` / `drowsiness`
- `phone` (`unavailable` se YOLO desligado — nunca omitir o campo)
- `latencies_ms` medidos (`quality`, `landmarks`, `expression`, `total_analytics`)

Lista `tracks: []` significa somente “ninguém no frame”. Objetos de módulo **não** ficam `{}` sem `status`.

`GET /api/v1/live/classroom-summary` (RTSP): `recognized_people`, `visible_people`, `observable_people`, `inconclusive_people`, `attention_index`, `apparent_climate` — **null** quando sem dado (não forçar zero indevido).

### Provenance

```json
{
  "provider": "demo_mock",
  "model_name": "demo-scenario-v1",
  "model_version": "v1",
  "rule_engine_version": "rules-v0-baseline",
  "threshold_profile": "presence-yaml-2026-07-23",
  "camera_calibration_version": "demo-uncalibrated",
  "runtime_mode": "demo",
  "is_simulated": true
}
```

### Behavioral event (exemplo demo)

```json
{
  "event_id": "demo-phone-probable",
  "event_type": "probable_phone_interaction",
  "severity": "probable",
  "review_status": "pending",
  "confidence": 0.78,
  "observation_quality": 0.7,
  "reasons": ["persistent_near_phone"],
  "is_simulated": true
}
```

### LXP event

```json
{
  "event_type": "attendance_checkin",
  "event_id": "uuid",
  "class_session_id": "uuid",
  "student_id": "demo-ana",
  "identity_confidence": 0.92,
  "is_simulated": true
}
```

### Classroom summary (live)

Campos típicos: `visible_people`, `recognized_people`, `observable_people`, `inconclusive_people`, `attention_index`, `apparent_climate`, `phones`, `active_behavioral_signals`.
