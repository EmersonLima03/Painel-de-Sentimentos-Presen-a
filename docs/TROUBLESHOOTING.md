# Troubleshooting

Para cada item: sintoma → causa → diagnóstico → correção → confirmação.

---

### `person_track_id` muda (001→002) com rosto coberto mas corpo visível

- **Causa:** ByteTrack emitia novo ID bruto; analytics limpava o track no mesmo ciclo sem `temporarily_lost`. Em campo, também gerava **ghost** (`pessoas: 2` = 001 lost + 002 novo).  
- **Correção:** `StablePersonTrackManager` com reclaim frouxo + **forced_single / forced_block_new** (não cria ID novo se houver track reclaimável na mesma região). Identity TTL permanece 12s e é independente.  
- **Confirmação:** 15–20s de oclusão facial → mesmo `person_track_id` + `identity.source=unknown`; overlay **não** deve mostrar `pessoas: 2` com uma só pessoa no quadro.

### Identidade troca sozinha (p01 ↔ outro) com oclusão

- **Causa:** analytics face-cêntrico antigo; swap sem confirmações.  
- **Correção:** person track + `IdentityBinding` (TTL, N confirmações, cooldown, bloqueio se associação ambígua / margem unavailable).  
- **Confirmação:** com rosto coberto, `identity.source=cached_binding`; após TTL → `unknown`; logs `identity_swap_blocked`.

### Cabeça baixa aparece como sonolência

- **Causa:** pitch facial sozinho.  
- **Correção:** pose corporal + regra “sem olhos observáveis fechados → não possible/probable”.  
- **Confirmação:** `head_state=head_down_*` com `drowsiness.state` em `none|inconclusive`.

### Olhos fechados longos ficam só em `possible`

- **Causa:** score só com olhos era baixo; `probable` exigia cabeça baixa; cooldown rebaixava o estado a cada frame.  
- **Correção:** olhos fechados ≥ **30s** → `probable` sem baixar a cabeça; cooldown só ao **abrir** os olhos.  
- **Confirmação:** 30–40s olhos fechados de frente → `sonolência: probable`.

### Sorriso aparece como expressão neutra

- **Causa:** caminho ONNX (FER+) não usava heurística de boca/dentes.  
- **Correção:** boost de sorriso no provider ONNX/TF → `positive` quando sorriso geométrico é forte.  
- **Confirmação:** sorriso sustentado ~8s → `expressão predominantemente positiva` (`n≥3`).

### Celular na mão com `not_detected` / threshold

- **Causa:** associação por face; ou conf baixa.  
- **Diagnóstico:** inspecionar `phone_detector` no snapshot (frame, confs, bboxes) **antes** de baixar conf YOLO.  
- **Correção:** associação por `person_bbox` + punhos; calibrar só com amostras.  
- **Confirmação:** `phone_visible` / `phone_in_hand` sem `confirmed_*`.

### Garrafa/térmico dispara `probable_phone_interaction`

- **Causa:** YOLO COCO classifica objetos verticais como `cell phone`; associação só por proximidade ao tronco.  
- **Correção (P0):** `phone_yolo.max_height_width_ratio` (rejeita bbox alto), `phone.interaction_requires_in_hand: true` (possible/probable só com punho).  
- **Diagnóstico:** em `/debug/vision` → JSON → `phone_detector.rejected_detections` ou `tracks[].phone.reasons`.  
- **Confirmação:** segurar garrafa ≥15s → no máximo `phone_near_person` ou `phone_in_hand`, **sem** evento provável; celular real na mão ≥12s → `possible`/`probable`.

### Garrafa/térmico dispara `probable_phone_interaction`

- **Causa:** YOLO COCO classifica objetos verticais como `cell phone`; associação só por proximidade ao tronco.  
- **Correção (P0):** `phone_yolo.max_height_width_ratio` (rejeita bbox alto), `phone.interaction_requires_in_hand: true` (possible/probable só com punho).  
- **Diagnóstico:** em `/debug/vision` → JSON → `phone_detector.rejected_detections` ou `tracks[].phone.reasons`.  
- **Confirmação:** segurar garrafa ≥15s → no máximo `phone_near_person` ou `phone_in_hand`, **sem** evento provável; celular real na mão ≥12s → `possible`/`probable`.

### Snapshot com `observation_quality: {}` / sem landmarks

- **Causa (antes):** módulos não publicados no `publish_live_debug` ou MediaPipe sem `solutions`.  
- **Correção:** `RealtimeAnalyticsEngine` + **MediaPipe Tasks Face Landmarker** (`face_landmarker.task`); reiniciar uvicorn `RUNTIME_MODE=rtsp`.  
- **Confirmação:** `facial_features.status=available`, `provider=mediapipe`, yaw/pitch/roll e EAR variam.

### Expressão sempre `inconclusive` / conf 0

- **Causa:** health check antigo aceitava só o arquivo `.hdf5`; TensorFlow ausente (disco).  
- **Correção:** health real + fallback **ONNX emotion-ferplus-8**; `sample_count` sobe com o tempo.  
- **Confirmação:** `expression.status=available`, `model_name=emotion-ferplus-8` (ou mini-xception se TF).

### Celular `unavailable`

- **Causa:** `phone_yolo.enabled: false` ou ultralytics/pesos ausentes.  
- **Correção:** `enabled: true`, `model_path: data/models/yolov8n.pt`, `pip install ultralytics`.  
- **Confirmação:** `phone.status=available` (mesmo com `not_detected`).

### WebSocket só heartbeat no RTSP

- **Causa:** ticker só existia no demo.  
- **Correção:** `live_hub.rtsp_ticker` publica `live_tracks`, `classroom_summary`, métricas, eventos.  
- **Confirmação:** cliente WS recebe `live_tracks` ~1 Hz.

- **Causa:** índice OpenCV errado (ex.: `0` abre mas frame preto; `1` tem imagem).  
- **Diagnóstico:** script probe de índices; log `async_capture_black_frame`.  
- **Correção:** `cam-web.rtsp_url: "1"` (ou outro); fechar apps que usam a câmera; reiniciar uvicorn.  
- **Confirmação:** `/debug/mjpeg?camera_id=cam-web` mostra imagem; faces > 0 com rosto na frente.

### RTSP unreachable / senha `PASSWORD`

- **Causa:** placeholder ou rede.  
- **Diagnóstico:** ping host; tentar VLC com URL montada do env.  
- **Correção:** `RTSP_*` no `.env`; desabilitar câmera inválida.  
- **Confirmação:** status `connected`; app não crasha se falhar.

### Modo demo mas esperava webcam

- **Causa:** `RUNTIME_MODE=demo` desliga orquestrador de câmera.  
- **Correção:** `RUNTIME_MODE=rtsp` e reiniciar.

### Dashboard React vazio / sem assets

- **Causa:** build ausente.  
- **Correção:** `cd frontend && npm install && npm run build`.  
- **Confirmação:** `/dashboard` carrega UI; rede mostra `/assets/*`.

### WebSocket desconectado

- **Causa:** token ausente/errado; servidor reiniciado.  
- **Correção:** `localStorage.api_token` ou query; frontend já faz backoff.  
- **Confirmação:** badge WS `connected`.

### Debug 403

- **Causa:** acesso remoto com `debug_vision_allow_remote=false`.  
- **Correção:** usar `127.0.0.1` ou habilitar flag conscientemente.

### API 401

- **Causa:** `API_AUTH_TOKEN` definido sem header.  
- **Correção:** `X-API-Token` ou limpar token em dev.

### Testes alterando / medindo banco real

- **Causa:** `SQLITE_PATH` apontando para prod.  
- **Correção:** não setar; confiar no `conftest`.  
- **Confirmação:** mtime de `dulino_edge.db` inalterado após pytest.

### Migration 005 indesejada

- **Causa:** `EXPERIMENTAL_SQLITE_005=1`.  
- **Correção:** remover flag; rollback só em **cópia**.  
- **Confirmação:** startup sem log `experimental_migration_005_applied`.

### OpenCV / NumPy / Torch / MediaPipe

- **Sintoma:** import error ou `mediapipe has no attribute solutions`.  
- **Correção:** Python 3.12 + `requirements.txt`; face mesh pode desligar sem derrubar presença.  
- **Confirmação:** logs `detector_initialized` / `embedder_initialized`.

### HSEmotion / DeepFace / TensorFlow

- **Causa:** não instalados no core (proposital).  
- **Correção:** venv isolado + requirements-spike; lazy import não deve crashar app.

### Porta 8000 em uso

- **Correção:** matar processo anterior ou mudar porta.

### Banco bloqueado / WAL

- **Correção:** fechar conexões; não abrir o mesmo DB em dois writers pesados; backup antes de operações.

### LXP mock / fila

- **Sintoma:** outbox pending.  
- **Correção:** `POST /api/v1/demo/lxp/flush`; ver dead-letter após 3 falhas.

### CPU alto

- **Causa:** resolução alta + max_faces + emotion.  
- **Correção:** substream; reduzir `max_faces`; backend `head_pose`; desligar módulos.

### Frontend npm / typecheck

- **Correção:** Node 18+; apagar `node_modules` e reinstalar; `npm run typecheck`.

### Rollback geral

1. Tag `pre-spike-sanitized`  
2. Restaurar backup em `data/backups/`  
3. `modules.*.mode: disabled` para analytics  
4. Limpar `data/demo/` se necessário  

### CORS

API e dashboard no mesmo origin (`127.0.0.1:8000`) — preferir isso em vez de Vite separado sem proxy.
