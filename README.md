# Dulino Edge Vision - MVP

Sistema de processamento de vídeo RTSP em edge para detecção de presença e análise de engajamento, enviando apenas eventos JSON para a nuvem (Supabase). **O vídeo nunca é enviado ou armazenado por padrão.**

## 🎯 Objetivo

Processar streams RTSP de câmeras IP localmente, gerar dois tipos de eventos:
- **Presença (check-in)**: Identificar aluno por embedding facial local e gerar eventos `attendance_checkin`
- **Engajamento**: Gerar métricas agregadas por janela de tempo e emitir eventos `engagement_window`

## 🏗️ Arquitetura

```
┌─────────────┐
│  Câmera IP  │──RTSP──>┌──────────────┐
│  (Stream)   │         │  Edge Device  │
└─────────────┘         │  (Este App)  │
                        └──────┬───────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
              ┌─────▼─────┐        ┌─────▼─────┐
              │  SQLite   │        │  Supabase │
              │  (Local)  │        │  (Cloud)  │
              └───────────┘        └───────────┘
```

### Componentes Principais

- **RTSP Ingest**: Captura e reconexão robusta de streams RTSP
- **Vision Pipeline**: Detecção facial, geração de embeddings, matching
- **Presence Rules**: Dedup de presença por dia/turno
- **Event Queue**: Fila local SQLite com sincronização assíncrona
- **Sync Worker**: Envio de eventos para Supabase com retry e offline-first

## 📋 Requisitos

- **Python 3.11 ou 3.12** (⚠️ Python 3.14 requer compilação de código-fonte)
- Sistema operacional: Linux (produção) ou Windows (desenvolvimento)
- CPU: Não requer GPU para MVP (roda em CPU)
- Memória: Mínimo 2GB RAM recomendado

> **⚠️ Nota sobre Python 3.14:** Se você tem Python 3.14 instalado, veja [INSTALL_PYTHON.md](INSTALL_PYTHON.md para instruções de instalação do Python 3.11/3.12.

## 🚀 Instalação Rápida

### 1. Clonar e Configurar

```bash
# Copiar arquivos de exemplo
cp .env.example .env
cp config.yaml.example config.yaml

# Editar .env com suas configurações
nano .env
```

### 2. Instalar Dependências

**⚠️ IMPORTANTE: Use Python 3.11 ou 3.12**

Se você tem Python 3.14, veja [INSTALL_PYTHON.md](INSTALL_PYTHON.md) primeiro.

**Linux/Mac:**
```bash
python3.11 -m venv venv  # ou python3.12
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

**Windows (com Python 3.11/3.12 instalado):**
```powershell
# Verificar versões disponíveis
.\scripts\check_python.ps1

# Configurar automaticamente (recomendado)
.\scripts\setup_python311.ps1

# Ou manualmente:
py -3.11 -m venv venv  # ou py -3.12
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### 3. Executar

**Linux/Mac:**
```bash
chmod +x scripts/run_dev.sh
./scripts/run_dev.sh
```

**Windows:**
```powershell
.\scripts\run_dev.ps1
```

Ou manualmente:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## ⚙️ Configuração

### Variáveis de Ambiente (.env)

```env
# Device Identity
DEVICE_ID=edge-001
DEVICE_TOKEN=your-device-token-here
SCHOOL_ID=1

# Supabase
SUPABASE_INGEST_URL=https://your-project.supabase.co/functions/v1/ingest-events

# Database
SQLITE_PATH=./data/dulino_edge.db

# Modos
SIMULATION=1  # 1 = simulação (sem modelos reais), 0 = desabilitado
REAL=0        # 1 = usar modelos reais (InsightFace/MediaPipe)

# RTSP
PRESENCE_SAMPLING_SECONDS=2
ENGAGEMENT_SAMPLING_SECONDS=5
PRESENCE_THRESHOLD=0.75
FACE_MIN_SIZE=50

# Presence
PRESENCE_DEDUP_MODE=day  # day | shift | class
PRESENCE_ACTIVE_WINDOWS=07:00-07:20,13:00-13:20

# Logging
LOG_LEVEL=INFO
```

### Configuração YAML (config.yaml)

```yaml
device:
  device_id: edge-001
  school_id: 1

cameras:
  - camera_id: cam-001
    room_id: A01
    rtsp_url: rtsp://admin:password@192.168.1.100:554/stream1
    enabled: true
```

## 🎮 Modos de Operação

### Modo Simulação (SIMULATION=1)

- Usa detectores e embedders simulados
- Gera eventos de teste sem depender de modelos pesados
- Ideal para desenvolvimento e testes
- Não requer instalação de modelos de ML

### Modo Real (REAL=1)

- Usa modelos reais (MediaPipe para detecção, InsightFace para embeddings)
- Requer instalação de dependências adicionais
- Consome mais recursos de CPU

**Para ativar modo real:**
```bash
# Instalar modelos InsightFace (opcional)
pip install insightface onnxruntime

# Configurar
export REAL=1
export SIMULATION=0
```

## 🎥 Testar com Webcam (Windows/Linux)

Para testar com sua webcam local sem precisar de câmera IP:

### 1. Configurar .env

```env
SIMULATION=0
REAL=0
DISABLE_RTSP=0
ENABLE_DEBUG_SNAPSHOT=1
SUPABASE_INGEST_URL=http://localhost:8000/mock/ingest
```

### 2. Configurar config.yaml

```yaml
cameras:
  - camera_id: cam-web
    room_id: DEV
    rtsp_url: "0"  # Device index 0 (webcam padrão)
    enabled: true
```

### 3. Iniciar Servidor

```powershell
python -m uvicorn app.main:app --reload --host localhost --port 8000
```

### 4. Testar Endpoints

- **Status das câmeras:**
  ```
  http://localhost:8000/cameras
  ```
  Deve mostrar `cam-web` com `is_connected: true` e `frame_count` aumentando.

- **Ver snapshot (debug):**
  ```
  http://localhost:8000/debug/snapshot?camera_id=cam-web
  ```
  Deve mostrar imagem da webcam no navegador.

- **Ver eventos:**
  ```
  http://localhost:8000/stats
  ```
  Deve mostrar eventos sendo criados e enviados para `/mock/ingest`.

### 5. Verificar Logs

No terminal, você verá:
- `rtsp_connecting_webcam` - Conectando à webcam
- `rtsp_connected` source=webcam - Conectado
- `engagement_window` - Eventos sendo gerados
- `mock_ingest_received` - Eventos sendo processados pelo mock

### Notas

- **Device index:** `"0"` = primeira webcam, `"1"` = segunda, etc.
- **Debug snapshot:** Só funciona com `ENABLE_DEBUG_SNAPSHOT=1`. Use `?camera_id=cam-web&overlay=1` para bboxes e labels.
- **Debug viewer (DEV):** Com `ENABLE_DEBUG_UI=1`, abra `GET /debug/viewer` para tela ao vivo com frame e status.
- **Monitor ao vivo:** `.\scripts\monitor_live.ps1` — imprime a cada 1s `faces_detected_last` e `last_presence_match`.
- **Teste 5 pessoas:** Roteiro completo em [docs/test_5_people.md](docs/test_5_people.md). Sessão guiada opcional: `python scripts/run_test_session.py`.
- **Mock ingest:** Permite testar sync sem Supabase real
- **Modo simulação:** Mantém funcionando normalmente com `SIMULATION=1`

## 📹 Simulando Stream RTSP

### Opção 1: Usar arquivo de vídeo local

```bash
# Instalar rtsp-simple-server (Linux)
wget https://github.com/aler9/rtsp-simple-server/releases/download/v1.0.0/rtsp-simple-server_v1.0.0_linux_amd64.tar.gz
tar -xzf rtsp-simple-server_v1.0.0_linux_amd64.tar.gz

# Em um terminal, iniciar servidor RTSP
./rtsp-simple-server

# Em outro terminal, publicar vídeo local
ffmpeg -re -stream_loop -1 -i video.mp4 -c copy -f rtsp rtsp://localhost:8554/stream1
```

### Opção 2: Usar câmera real

Configure a URL RTSP da sua câmera IP no `config.yaml`:
```yaml
cameras:
  - camera_id: cam-001
    room_id: A01
    rtsp_url: rtsp://admin:password@192.168.1.100:554/stream1
    enabled: true
```

## 👤 Enrollment (Cadastro de Faces)

### Via API

```bash
# Cadastrar face de aluno a partir de imagem local
curl -X POST http://localhost:8000/enroll \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "12345",
    "image_path": "/path/to/student_photo.jpg"
  }'
```

### Modo Mock (para testes)

Crie imagens de teste e faça enrollment:
```bash
# Exemplo com imagem de teste
curl -X POST http://localhost:8000/enroll \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "student-001",
    "image_path": "./test_images/student1.jpg"
  }'
```

## 📊 Endpoints da API

### Health Check
```bash
GET http://localhost:8000/health
```

Resposta:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_seconds": 3600,
  "cameras_online": 2,
  "cameras_total": 2
}
```

### Estatísticas
```bash
GET http://localhost:8000/stats
```

### Status das Câmeras
```bash
GET http://localhost:8000/cameras
```

### Recarregar Configuração
```bash
POST http://localhost:8000/config/reload
```

## 🗄️ Banco de Dados Local (SQLite)

O banco é criado automaticamente em `./data/dulino_edge.db`. Para instalações existentes com schema antigo (embedding_vector), execute uma vez:

```powershell
python migrations/sqlite/003_embedding_blob.py
```

### Sanity Check

Para validar embedding, banco e FAISS:

```powershell
python scripts/sanity_check.py
```

### Tabelas

- **events**: Eventos pendentes/enviados
- **attendance_cache**: Cache de presença (dedup)
- **students**: Alunos cadastrados
- **face_embeddings**: Embeddings faciais (BLOB 512D)
- **device_state**: Estado do dispositivo

### Consultar eventos

```bash
sqlite3 data/dulino_edge.db "SELECT * FROM events WHERE status='pending' LIMIT 10;"
```

## ☁️ Integração Supabase Staging

> 📖 **Guia Completo:** Veja `SUPABASE_SETUP_COMPLETO.md` para passo a passo detalhado do início ao fim.

### 📋 Checklist Manual (Passo a Passo)

#### 1. Criar Projeto Staging no Supabase

1. Acesse https://supabase.com
2. Clique em "New Project"
3. Preencha:
   - **Name:** `dulino-edge-staging` (ou nome de sua escolha)
   - **Database Password:** (anote esta senha!)
   - **Region:** Escolha mais próxima
4. Aguarde criação do projeto (~2 minutos)

#### 2. Executar Schema SQL

1. No projeto criado, vá em **SQL Editor** (menu lateral)
2. Clique em **New Query**
3. Copie e cole o conteúdo de `supabase/schema_staging.sql`
4. Clique em **Run** (ou F5)
5. Verifique se as tabelas foram criadas:
   - `edge_events_raw`
   - `attendance_checkins`
   - `engagement_windows`
   - `edge_devices`

#### 3. Criar Edge Function

1. No menu lateral, vá em **Edge Functions**
2. Clique em **Create a new function**
3. Configure:
   - **Function name:** `ingest-events`
   - **Method:** POST
4. Cole o código de `supabase/ingest_function_staging.ts`
5. Clique em **Deploy**

#### 4. Configurar Variáveis de Ambiente da Function

1. Na função `ingest-events`, vá em **Settings**
2. Adicione **Secrets**:
   - `SUPABASE_URL`: Copie de **Project Settings** → **API** → **Project URL**
   - `SUPABASE_SERVICE_ROLE_KEY`: Copie de **Project Settings** → **API** → **service_role** (secret)
   - `EDGE_DEVICE_TOKENS`: Lista de tokens separados por vírgula (ex: `token1,token2`)

#### 5. Gerar DEVICE_TOKEN

Gere um UUID para seu dispositivo:

**PowerShell:**
```powershell
[guid]::NewGuid()
```

**Python:**
```python
import uuid
print(uuid.uuid4())
```

Anote este token!

#### 6. Adicionar Token na Function

1. Volte em **Edge Functions** → `ingest-events` → **Settings**
2. Edite o secret `EDGE_DEVICE_TOKENS`
3. Adicione o token gerado (ex: `seu-token-aqui`)
4. Salve

#### 7. Obter URL do Endpoint

1. Vá em **Edge Functions** → `ingest-events`
2. Copie a **Function URL** (algo como: `https://xxxxx.supabase.co/functions/v1/ingest-events`)

#### 8. Configurar .env Local

Edite seu `.env`:

```env
DEVICE_ID=edge-001
DEVICE_TOKEN=seu-token-gerado-aqui
SUPABASE_INGEST_URL=https://xxxxx.supabase.co/functions/v1/ingest-events
```

#### 9. Testar Envio Real

```powershell
# Testar manualmente
Invoke-WebRequest -Uri $env:SUPABASE_INGEST_URL `
  -Method POST `
  -Headers @{"Authorization"="Bearer $env:DEVICE_TOKEN"; "Content-Type"="application/json"} `
  -Body '{"event_id":"test-123","event_type":"test","device_id":"edge-001","school_id":"1","timestamp":1234567890}'
```

**Esperado:** `{"ok":true,"received":1,"inserted":1,"duplicated":0}`

### 🔒 Segurança

- **Tokens:** Armazene `DEVICE_TOKEN` de forma segura (não commite no git)
- **RLS:** Tabelas criadas sem RLS por padrão (ajuste conforme necessário)
- **Service Role Key:** Nunca exponha em frontend, apenas em Edge Functions

### 📊 Verificar Dados

No Supabase:
- **Table Editor** → `edge_events_raw` → Ver eventos recebidos
- **Table Editor** → `attendance_checkins` → Ver check-ins normalizados
- **Table Editor** → `engagement_windows` → Ver janelas de engajamento

### 3. Configurar URL

No `.env`:
```env
SUPABASE_INGEST_URL=https://your-project.supabase.co/functions/v1/ingest-events
DEVICE_TOKEN=seu-token-de-dispositivo
```

## 🐳 Deploy com Docker

### Build e Run

```bash
cd docker
docker-compose up -d
```

### Logs

```bash
docker-compose logs -f
```

## 🖥️ Deploy no Mini PC Linux

### Opção 1: Systemd Service

Criar `/etc/systemd/system/dulino-edge.service`:

```ini
[Unit]
Description=Dulino Edge Vision
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/opt/dulino-edge-vision
Environment="PATH=/opt/dulino-edge-vision/venv/bin"
ExecStart=/opt/dulino-edge-vision/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Ativar:
```bash
sudo systemctl enable dulino-edge
sudo systemctl start dulino-edge
sudo systemctl status dulino-edge
```

### Opção 2: Docker Compose

```bash
# Copiar arquivos para Mini PC
scp -r . user@mini-pc:/opt/dulino-edge-vision

# No Mini PC
cd /opt/dulino-edge-vision
docker-compose -f docker/docker-compose.yml up -d
```

## 🧪 Testes

```bash
# Instalar pytest
pip install pytest

# Executar testes
pytest tests/
```

## 📝 Logs

Logs estruturados em JSON (quando `LOG_LEVEL=INFO`):
```json
{"event": "attendance_checkin", "student_id": "12345", "room_id": "A01", "confidence": 0.82, "timestamp": "2024-01-15T10:30:00"}
```

## 🔒 Privacidade e Segurança

### Checklist de Privacidade

- ✅ **Vídeo nunca é enviado para nuvem**: Apenas eventos JSON
- ✅ **Sem armazenamento de imagens por padrão**: Apenas embeddings (vetores numéricos)
- ✅ **Processamento local**: Tudo roda no edge device
- ✅ **Idempotência**: Eventos têm UUID único para evitar duplicação
- ✅ **Offline-first**: Eventos ficam em fila local se internet cair

### Recomendações

- Use HTTPS para comunicação com Supabase
- Armazene `DEVICE_TOKEN` de forma segura
- Configure firewall no Mini PC
- Considere criptografia de disco para SQLite (opcional)

## 🐛 Troubleshooting

### RTSP não conecta

1. Verificar URL e credenciais no `config.yaml`
2. Testar URL com VLC: `vlc rtsp://...`
3. Verificar firewall/portas
4. Ver logs: `docker-compose logs` ou console

### Eventos não são enviados

1. Verificar `SUPABASE_INGEST_URL` e `DEVICE_TOKEN` no `.env`
2. Verificar status: `GET /stats`
3. Ver eventos pendentes no SQLite
4. Verificar logs de sync worker

### Detecção não funciona

1. Verificar se está em modo simulação (`SIMULATION=1`)
2. Para modo real, instalar dependências: `pip install mediapipe insightface`
3. Verificar qualidade de iluminação na câmera
4. Ajustar `PRESENCE_THRESHOLD` e `FACE_MIN_SIZE`

## 📚 Estrutura do Projeto

```
dulino-edge-vision/
├── app/
│   ├── main.py              # FastAPI app
│   ├── config.py            # Configurações
│   ├── logging.py            # Logging estruturado
│   ├── db/                   # SQLite models e repos
│   ├── rtsp/                 # RTSP reader
│   ├── vision/                # Vision pipeline
│   ├── pipeline/              # Pipelines de processamento
│   ├── sync/                # Sync worker
│   └── enroll/              # Enrollment service
├── supabase/                # Schema SQL e Edge Function
├── docker/                  # Docker files
├── scripts/                 # Scripts de execução
├── tests/                   # Testes
├── data/                    # SQLite database (gitignored)
├── .env.example            # Exemplo de variáveis
├── config.yaml.example     # Exemplo de config
└── requirements.txt        # Dependências Python
```

## 🚧 Próximos Passos (Pós-MVP)

- [ ] Suporte a GPU (CUDA/OpenVINO)
- [ ] Modelo real de head pose para engajamento
- [ ] Dashboard web local
- [ ] Métricas Prometheus
- [ ] Suporte a múltiplos modelos de embedding
- [ ] Compressão de embeddings (quantização)

## 📄 Licença

Este é um projeto MVP interno.

## 🤝 Contribuindo

Para questões e melhorias, abra uma issue ou pull request.

---

**Desenvolvido para processamento edge de vídeo com privacidade em primeiro lugar.**
