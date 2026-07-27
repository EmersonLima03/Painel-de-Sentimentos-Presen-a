# Operações — instalação, configuração e execução

## Requisitos

| Item | Recomendação |
|------|----------------|
| Python | **3.11 ou 3.12** (evitar 3.14) |
| Node.js | 18+ (frontend) |
| SO | Windows (dev) / Linux (prod) |
| RAM | ≥ 2 GB (recomendado ≥ 8 GB para visão) |
| GPU | Não obrigatória |

Dependências principais: FastAPI, OpenCV, NumPy, SQLAlchemy, FaceNet/torch, YuNet, FAISS (opcional), **MediaPipe Tasks** (Face Landmarker), **onnxruntime** (FER emotion-ferplus), **ultralytics** (YOLO celular).  
Extras isolados: `requirements-emotion.txt`, `requirements-spike-hsemotion.txt`, `requirements-spike-deepface.txt` — **não** instalar no venv core sem necessidade. TensorFlow completo é opcional (FER usa ONNX quando TF não cabe no disco).

Hardware conhecido de lab: notebook i5-class + webcam USB/notebook (**cam-web index 1 validada**); Intelbras VIP-5440-IA (rede) — **ainda sem validação de campo** neste repositório.

### Modelos locais necessários (analytics)

| Modelo | Path | Uso |
|--------|------|-----|
| Face Landmarker | `data/mediapipe_models/face_landmarker.task` | olhos/boca/yaw/pitch/roll |
| Emotion FER+ ONNX | `data/models/emotion-ferplus-8.onnx` | expressão aparente (fallback sem TF) |
| Mini-XCEPTION hdf5 | `data/models/_mini_XCEPTION.106-0.65.hdf5` | FER legado se TensorFlow disponível |
| YOLOv8n | `data/models/yolov8n.pt` | celular (`phone_yolo.enabled: true`) |

## Instalação backend (PowerShell)

```powershell
cd "caminho\Presenca"
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
# Opcional: .\scripts\setup_python311.ps1 / .\scripts\check_python.ps1
```

Copiar `.env.example` → `.env` se existir; ajustar `DEVICE_ID`, `API_AUTH_TOKEN`, paths.

## Instalação frontend

```powershell
cd frontend
npm install
npm run typecheck
npm run build
cd ..
```

O FastAPI serve `frontend/dist` em `/dashboard` e assets em `/assets`.

## Configuração

### Arquivos

- `config.yaml` — câmeras, vision, modules, runtime, experimental
- `.env` / variáveis de ambiente — segredos e overrides

### Runtime e módulos

```yaml
runtime:
  mode: demo   # ou offline | rtsp

modules:
  expression: { mode: debug }          # disabled|debug|shadow|production
  # ... face_landmarks, person_tracking, phone, pose, temporal_fusion
  educational_dashboard: { mode: production }
  lxp: { mode: disabled }

experimental:
  sqlite_005_enabled: false
  longitudinal_approval_recorded: false
```

Inferência real **não** deve ir a `production` sem `longitudinal_approval_recorded: true` (o loader rebaixa para shadow).

### Variáveis úteis

| Variável | Função |
|----------|--------|
| `RUNTIME_MODE` | demo / offline / rtsp |
| `SQLITE_PATH` | Banco real |
| `DEMO_DB_PATH` | Banco demo |
| `API_AUTH_TOKEN` | Se vazio = API aberta (dev) |
| `ENABLE_DEBUG_SNAPSHOT` | `1` para MJPEG/debug |
| `ENABLE_DEBUG_UI` | UI de debug legada |
| `EXPERIMENTAL_SQLITE_005` | `1` aplica migration 005 |
| `RTSP_USERNAME` / `PASSWORD` / `HOST` / `PORT` / `PATH` | Montar URL sem commit |

### Webcam

Em `config.yaml`, `cameras[].rtsp_url` numérico = índice OpenCV (`"0"`, `"1"`, …).  
Neste repositório, o índice **0** pode abrir frame **preto**; o **1** costuma ser a webcam real. O capturador rejeita frame preto e tenta fallback 0–3.

### RTSP (sem credenciais no Git)

```env
RTSP_USERNAME=
RTSP_PASSWORD=
RTSP_HOST=
RTSP_PORT=554
RTSP_PATH=/cam/realmonitor?channel=1&subtype=1
RUNTIME_MODE=rtsp
```

Desabilite câmeras com `PASSWORD` placeholder. Falha de conexão deve aparecer no status — a app **não** deve derrubar.

## Execução

### Demo

```powershell
$env:RUNTIME_MODE="demo"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Controles: `POST /api/v1/demo/control` — play / pause / reset / speed 1|2|5.

### Offline

```powershell
$env:RUNTIME_MODE="offline"
# apontar pasta/vídeo via config ou kwargs do OfflineFrameSource
```

Corpus sob `data/spike/` — **não** commitar imagens. Sem labels ground-truth, não declarar validação real.

### Webcam / RTSP

```powershell
$env:RUNTIME_MODE="rtsp"
$env:ENABLE_DEBUG_SNAPSHOT="1"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Aguarde carga de YuNet/FaceNet (~20–40s na primeira subida).

## URLs

| Path | Uso |
|------|-----|
| `/dashboard` | Educacional |
| `/dashboard-legacy` | Legado |
| `/debug/vision` | Técnico + aba **Validação controlada** |
| `/docs` | OpenAPI |
| `/api/v1/system/health` | Saúde |
| `/api/v1/live/status` | Status live |
| `/api/v1/validation/sessions` | Sessões de validação manual |

## Banco de dados

| Path | Conteúdo |
|------|----------|
| `data/dulino_edge.db` | Produção local (presença, fila, alunos) |
| `data/demo/dulino_edge_demo.db` | Somente demo |
| `data/validation/validation.db` | Sessões/etapas/amostras de validação controlada (isolado) |
| `data/backups/` | Backups manuais / DAT |

**Migration 005:** gated. Rollback em cópia:

```powershell
python migrations/sqlite/005_observation_windows.py rollback path\to\copia.db
```

Backup histórico de referência (pré-spike): `data/backups/dulino_edge_pre_spike_*.db` (se existir). Tags: `pre-spike-sanitized`.

Testes: nunca apontar `SQLITE_PATH` para o banco real; `conftest` isola.

## Logs

Saída estruturada JSON no stdout (nível `logging.level` no YAML).  
**Não** devem aparecer: senha RTSP, URL completa com credencial, embeddings, frames.

## Scripts úteis

| Script | Função |
|--------|--------|
| `scripts/monitor_presence.ps1` | Loop 2s: faces + último match em `/cameras` |
| `scripts/run_dev.ps1` | Subida de desenvolvimento |
| `scripts/check_python.ps1` | Versões Python |
| `scripts/backup_hub.py` / `restore_hub.py` | Backup/restore |

## Checklist operacional

**Antes:** venv ativo; modo correto; câmera certa habilitada; `ENABLE_DEBUG_SNAPSHOT` se for ver preview; token se produção.

**Durante:** `/dashboard` ou legado; monitorar CPU; revisão humana de eventos sensíveis.

**Depois:** encerrar sessão; export relatório (demo); não copiar demo DB → prod.

**Falha:** ver [TROUBLESHOOTING.md](TROUBLESHOOTING.md); rollback via tag Git / backup SQLite; desligar módulos (`mode: disabled`).
