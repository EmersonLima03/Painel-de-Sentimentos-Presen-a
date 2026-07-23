# Troubleshooting

Para cada item: sintoma → causa → diagnóstico → correção → confirmação.

---

### Snapshot com `observation_quality: {}` / sem landmarks

- **Causa (antes):** módulos não publicados no `publish_live_debug`.  
- **Correção:** subir build com `RealtimeAnalyticsEngine`; reiniciar uvicorn `RUNTIME_MODE=rtsp`.  
- **Confirmação:** cada track em `/debug/vision` tem `observation_quality.status` e `facial_features.status`.

### Overlay `Aten????o`

- **Causa:** `cv2.putText` sem Unicode.  
- **Correção:** labels ASCII no bitmap (`Atencao nao conclusiva`); API/HTML UTF-8.

### Expressão / phone “vazio”

- **Esperado:** `status: unavailable` com `reason` se FER/YOLO ausentes — **não** objeto vazio.

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
