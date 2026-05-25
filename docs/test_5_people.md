# Teste com 5 Pessoas - Fluxo Completo MVP Preseca

Roteiro repetível para validar presença (check-in) e engajamento com 5 pessoas via webcam, **sem salvar fotos**.

## Critérios de aceite

- Cadastrar 5 pessoas (p01..p05), embedding 512D FaceNet
- Reconhecer as 5 e gerar `attendance_checkin` (ou `attendance_duplicate`) com confidence acima do threshold
- `engagement_window` com `faces_detected_avg > 0` quando há pessoas na câmera
- `/health`: `detector_backend`, `embedder_backend`, `faiss_enabled`, `sqlite_path`, `supabase_enabled`, `version`
- `/cameras`: por câmera `is_connected`, `last_frame_time`, `frame_count`, `last_error`, `faces_detected_last`, `last_presence_match`, `last_presence_event_id`
- Tela de debug opcional: `ENABLE_DEBUG_UI=1` → `/debug/viewer` com frame e overlay

---

## A) Setup

### 1. Ambiente

```bash
cd preseca
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
# ou: source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### 2. .env

Mínimo para teste local:

```env
SIMULATION=0
REAL=1
PRESENCE_ALWAYS_ON=1
ENABLE_DEBUG_SNAPSHOT=1
```

Opcional (tela de debug em tempo real):

```env
ENABLE_DEBUG_UI=1
```

Presença: threshold em `config.yaml` (ex.: `threshold: 0.70`). Se aparecer pouco reconhecimento, baixe para 0.65–0.70.

Supabase (opcional):

```env
SUPABASE_INGEST_URL=https://seu-projeto.supabase.co/functions/v1/...
SUPABASE_ANON_KEY=...
DEVICE_TOKEN=...
EVENT_TYPES_WHITELIST=attendance_checkin,engagement_window
```

### 3. config.yaml

- **Câmera padrão:** Use `rtsp_url: "0"` para webcam do notebook. Para usar iPhone (Camo/Iriun), use `rtsp_url: "1"` (ou "2"); se a câmera não abrir em ~3 s, o sistema faz **fallback automático** para `device.default_camera_index` (ex.: 0).
- **Listar câmeras (DEV):** `GET /cameras/devices` retorna índices testados e quais abriram (útil para saber qual é notebook vs Iriun).
- **Trocar câmera ao vivo:** edite `rtsp_url` em `config.yaml` e chame `POST /config/reload`.

```yaml
device:
  device_id: edge-001
  school_id: 1
  default_camera_index: 0
  camera_connect_timeout_seconds: 3

cameras:
  - camera_id: cam-web
    room_id: DEV
    rtsp_url: "0"   # null ou omitido = usa default_camera_index
    enabled: true

vision:
  presence:
    sampling_seconds: 2
    threshold: 0.70
    match_margin: 0.08
    th_on: 0.75
    th_off: 0.68
    track_ttl_seconds: 2.0
    max_templates_per_student: 7
    min_face_size: 50
    always_on: true
```

### 4. Iniciar servidor

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 5. Verificar /health

```bash
curl http://127.0.0.1:8000/health
```

Esperado: `detector_backend` (mediapipe_tasks / opencv_haar), `embedder_backend` (facenet), `faiss_enabled`, `sqlite_path`, `supabase_enabled`, `version`.

---

## B) Cadastro (enrollment)

Cadastrar **p01, p02, p03, p04, p05** via POST `/enroll/webcam`.

**Importante:** A pessoa a ser cadastrada deve estar **sozinha e bem enquadrada** na câmera. Se a câmera estiver em outra pessoa, chame de novo com a pessoa certa para atualizar (o sistema usa o embedding mais recente).

**Precisão:** O cadastro usa vários frames e faz a **média dos melhores embeddings** (config em `config.yaml` → `enrollment`). Por padrão: 15 frames capturados, 10 melhores usados, 5 s de captura. Mais frames = mais precisão; para máxima precisão use `num_frames: 20` e `frames_used: 12` no config (ou envie no body do POST).

**Óculos / múltiplos looks (multi-template):** Para manter vários looks por pessoa (ex.: com/sem óculos), use **append_template**:
- Primeiro cadastro: `POST /enroll/webcam` com `{"student_id":"p01","full_name":"Pessoa 01","camera_id":"cam-web"}` (comportamento atual).
- Para adicionar outro template (ex.: sem óculos): `{"student_id":"p01","full_name":"Pessoa 01","camera_id":"cam-web","append_template": true}`. O sistema mantém até `max_templates_per_student` (config, ex.: 7); o mais antigo é descartado ao exceder.
- `/health` → `presence_debug.templates_per_student` mostra quantos templates por aluno.

Exemplo (PowerShell):

```powershell
# Usa config (enrollment.num_frames, frames_used, capture_duration_seconds)
Invoke-WebRequest -Uri "http://127.0.0.1:8000/enroll/webcam" -Method POST -ContentType "application/json" -Body '{"student_id":"p01","full_name":"Pessoa 01","camera_id":"cam-web"}' -UseBasicParsing
```

Repetir para p02..p05 (trocar `student_id` e `full_name`).

Registrar em cada um: `model_version`, `embedding_dim`, `quality_score`.

---

## C) Reconhecimento individual

Cada pessoa fica **~10 s** na frente da câmera.

- Logs: `presence_match_found`, `attendance_checkin` (ou `attendance_duplicate`).
- Endpoints:
  - `GET /events?event_type=attendance_checkin&limit=100`
  - `GET /cameras` → `last_presence_match` com `student_id` e `confidence`.

---

## D) Reconhecimento em dupla

Duas pessoas lado a lado **30–60 s**.

- `GET /cameras`: `faces_detected_last` >= 2; `last_presence_match` deve listar os dois (ex.: p01 e p02).
- `GET /events?event_type=attendance_checkin&limit=100`: check-ins para ambos.

Script de monitor (a cada 1 s): `.\scripts\monitor_live.ps1`

---

## E) Engajamento

1–2 pessoas na câmera por **1–2 minutos**.

- Logs: `engagement_window` com `room_id`, `faces_avg`, `activity_level`, `engagement_index_avg`.
- Endpoint: `GET /events?event_type=engagement_window&limit=20`
- Payload: `faces_detected_avg` > 0, `engagement_index_avg`, `activity_level` (low/medium/high).

Com 2 pessoas, `faces_detected_avg` deve ficar > 0 de forma consistente.

---

## F) Coletar evidências

| Comando | O que registrar |
|--------|------------------|
| `GET /health` | detector_backend, embedder_backend, faiss_enabled, sqlite_path, supabase_enabled, version |
| `GET /cameras` | is_connected, faces_detected_last, last_presence_match, last_presence_event_id |
| `GET /events?event_type=attendance_checkin&limit=100` | student_id, confidence, room_id, timestamp |
| `GET /events?event_type=engagement_window&limit=20` | ts_start, ts_end, faces_detected_avg, engagement_index_avg, activity_level |
| `GET /stats` | events_by_type, events_by_status |

Logs esperados: `presence_match_found`, `attendance_checkin`/`attendance_duplicate`, `engagement_window` (faces_avg, activity_level, engagement_index_avg), `event_sent`/`event_synced` se Supabase ativo.

---

## G) Testes de estabilidade (5 pessoas)

Objetivo: validar que com 5 cadastrados o sistema mantém **nomes estáveis** (sem piscar), **UNKNOWN não vira cadastrado** e que o viewer/APIs dão evidências suficientes.

### Pré-requisitos

- 5 pessoas cadastradas (p01..p05) via `POST /enroll/webcam`. Opcional: usar `append_template: true` para alguém com óculos/sem (multi-template).
- Servidor rodando com webcam do notebook (`rtsp_url` no índice correto no `config.yaml`).
- `ENABLE_DEBUG_UI=1` e `ENABLE_DEBUG_SNAPSHOT=1` para o viewer.

### Roteiro de validação

| # | Cenário | Duração | O que validar |
|---|--------|--------|----------------|
| 1 | **Uma pessoa** (cadastrada) | ~30 s | Viewer: 1 face, label estável (ex.: Emerson 0.93). Sem piscar para UNKNOWN. |
| 2 | **Duas pessoas** (ambas cadastradas) | ~60 s | Viewer: 2 track_ids, dois nomes estáveis. Painel "Current matches" com 2 linhas (track_id, label, score, top2, margin). |
| 3 | **Uma cadastrada + uma não cadastrada** | ~60 s | A não cadastrada deve ficar **UNKNOWN** o tempo todo. Nunca deve "virar" o nome da cadastrada. |
| 4 | **Três no frame** (2 cadastradas + 1 desconhecido) | ~45 s | Três linhas no viewer; UNKNOWN estável; cadastrados estáveis. |
| 5 | **Viewer 2 min** | 2 min | Deixar o viewer aberto com 1–2 pessoas. Vídeo não deve travar; contadores atualizam. |

### Como coletar evidências

- **Debug viewer:** Abra `http://127.0.0.1:8000/debug/viewer`. Observe "Status / cameras" (JSON da câmera) e "Current matches (per face)" (track_id, label, score, top2, margin). Screenshots ou anotações em cada cenário.
- **APIs (PowerShell):**
  ```powershell
  # Câmera + último match
  (Invoke-WebRequest "http://127.0.0.1:8000/cameras" -UseBasicParsing).Content | ConvertFrom-Json | ConvertTo-Json -Depth 5

  # Matches atuais (por face) – igual ao que o viewer usa
  (Invoke-WebRequest "http://127.0.0.1:8000/debug/overlay_matches?camera_id=cam-web" -UseBasicParsing).Content | ConvertFrom-Json | ConvertTo-Json -Depth 5

  # Check-ins gravados
  (Invoke-WebRequest "http://127.0.0.1:8000/events?event_type=attendance_checkin&limit=50" -UseBasicParsing).Content | ConvertFrom-Json | ConvertTo-Json -Depth 4
  ```
- **Script de monitor (terminal):** `.\scripts\monitor_live.ps1` — atualiza a cada 1 s com `faces_detected_last` e reconhecidos.
- **Salvar evidência em arquivo (opcional):** `.\scripts\collect_stability_evidence.ps1` (veja abaixo).

### Critérios de sucesso

1. **Estabilidade por face:** Cada face mantém o mesmo label (nome ou UNKNOWN) por vários segundos, sem piscar, mesmo com variação de iluminação/ângulo.
2. **UNKNOWN não vira cadastrado:** Pessoa não cadastrada permanece sempre UNKNOWN (regra de margin + th_on).
3. **Viewer fluido:** ~10 fps; sem travar por 2 min.
4. **Evidências:** Dados de `/cameras`, `/debug/overlay_matches` e `/events` coerentes com o que se vê no viewer.

---

## Cadastrei a pessoa errada (câmera em outro rosto)

Se você rodou o enroll com a câmera apontada para outra pessoa, o sistema guardou o rosto errado para aquele `student_id`. Para corrigir:

1. Deixe **apenas a pessoa certa** na frente da câmera.
2. Chame de novo o **POST /enroll/webcam** com o mesmo `student_id` e `full_name`.
3. O embedding mais recente passa a ser usado; o reconhecimento usará o rosto correto.

---

## Se aparecer NINGUÉM (checklist)

- **Iluminação**: ambiente claro, rosto bem iluminado.
- **Distância**: rosto a ~30–60 cm da câmera, enquadrado.
- **camera_id**: mesma câmera do enrollment (ex.: cam-web); conferir em `/cameras`.
- **Threshold**: em `config.yaml` → `vision.presence.threshold` (ex.: 0.70 ou 0.65).
- **Embeddings**: `/health` → `presence_debug.matcher_embeddings` > 0; cadastrar p01..p05 se necessário.
- **Janela de presença**: `always_on: true` em config ou testar dentro do horário de `active_windows`.
- **Detector**: `/health` → `detector_backend` (mediapipe_tasks preferível; opencv_haar é fallback).

---

## Debug (DEV ONLY)

- **Snapshot**: `ENABLE_DEBUG_SNAPSHOT=1` → `GET /debug/snapshot?camera_id=cam-web&overlay=1` (bboxes e labels).
- **Viewer**: `ENABLE_DEBUG_UI=1` → abrir `http://127.0.0.1:8000/debug/viewer` no navegador (frame ao vivo + status).
- **Monitor em terminal**: `.\scripts\monitor_live.ps1` (faces_detected_last e last_presence_match a cada 1 s).

---

## Câmera iPhone: Iriun / Camo (recomendado)

O **Iriun Webcam** ou **Camo** usa a câmera do iPhone como **câmera virtual** no PC (não é RTSP). No Windows aparece como dispositivo de vídeo (índice 0, 1 ou 2).

1. **Instalar**: Iriun/Camo no iPhone + app no PC. Conectar (Wi‑Fi ou USB).
2. **Descobrir índice (DEV):** `GET /cameras/devices` lista índices (ex.: 0, 1) e quais abriram; use isso para saber "Notebook (0)" vs "Iriun (1)".
3. **config.yaml**: use `rtsp_url: "1"` para Iriun (0 = webcam do notebook). Se **"1" não abrir** em ~3 s, o sistema faz **fallback automático** para a câmera default (0) e loga `camera_open_failed` + `fallback_to_default` — não fica preso em "Looking for the phone".
4. **Validar**: `http://127.0.0.1:8000/debug/viewer` (ENABLE_DEBUG_UI=1). Se o vídeo não aparecer, a mensagem será "Aguardando frames da câmera… Se índice falhou, use rtsp_url: \"0\" no config e recarregue."

---

## Câmera iPhone (RTSP/HTTP)

Para usar o iPhone como câmera via **stream RTSP ou HTTP** (outros apps, não Iriun):

1. **App no iPhone**: use um app que exponha a câmera via RTSP ou HTTP (ex.: **iVCam**, **EpocCam**, **Camo**, ou apps que gerem URL de stream).
2. **Rede**: iPhone e PC na mesma Wi‑Fi; anote a URL (ex.: `rtsp://192.168.1.10:8554/live`).
3. **config.yaml**: use essa URL em `rtsp_url` (não use "0"/"1"/"2", use a URL completa).
4. **Validar**: reinicie o servidor e confira `/cameras` e o Debug Viewer.

---

## Observações

- **Presença**: face detectada + embedding + match (threshold + margin) + dedup. Check-in só é gravado quando passa threshold e margin; overlay usa histerese (TH_ON/TH_OFF) para estabilidade.
- **Tracker + histerese**: cada face mantém um `track_id` por alguns segundos (TTL em `track_ttl_seconds`). Reconhecido só vira "desconhecido" abaixo de `th_off`; desconhecido só vira reconhecido acima de `th_on`. Reduz alternância nome ↔ desconhecido com 2+ pessoas (uma perto, outra longe).
- **Labels no overlay**: múltiplos reconhecidos (ex.: p01 0.91, p02 0.84); "provável" quando confiança está na faixa de histerese; "Desconhecido" estável quando abaixo de th_off.
- **Falsos positivos**: `match_margin` e `th_on`/`th_off` ajudam; se alguém não cadastrado aparecer como outra pessoa, aumentar margem ou recadastrar.
- **Engajamento**: agregado (faces + atividade); `engagement_index_avg` e `activity_level` por janela.
- **Sync**: sem alterar schema_staging nem edge function.
