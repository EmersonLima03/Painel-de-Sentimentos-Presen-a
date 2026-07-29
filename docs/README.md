# Documentação — Dulino Edge Vision (Presença)

Ponto de entrada oficial da documentação do projeto.

## Visão geral

**Dulino Edge Vision** é um sistema **edge** (local) de visão computacional para salas de aula: captura frames de câmera, reconhece presença facial e estima **sinais visuais observáveis** (indicadores visuais de acompanhamento, expressão aparente, celular, sonolência aparente, clima coletivo). Observação assistida da dinâmica da sala — não é diagnóstico de sentimento nem avaliação de aluno.

| Público | Uso |
|---------|-----|
| Escola / coordenação | Acompanhar presença e indicadores agregados da aula |
| Operação técnica | Instalar, configurar câmeras, monitorar saúde |
| Produto / engenharia | Evoluir módulos sem misturar analytics com presença |

**Posicionamento técnico:** FastAPI + SQLite no dispositivo; vídeo **não** é enviado à nuvem por padrão; eventos JSON podem ir a um ingest (Supabase/LXP) quando configurado.

### Aviso ético (obrigatório)

Indicadores são **estimativas a partir de sinais visuais**. **Não** constituem diagnóstico emocional, psicológico ou médico, nem comprovação de aprendizagem.

| Conceito | O que é | O que **não** é |
|----------|---------|-----------------|
| **Presença** | Identidade facial + check-in | Engajamento ou humor |
| **Atenção visual estimada** | Orientação da cabeça / olhar aproximado | Interesse real ou capacidade cognitiva |
| **Expressão aparente** | Classe normalizada (positiva/neutra/negativa/…) | “Aluno triste/feliz/deprimido” |
| **Comportamento observável** | Celular visível, possível/provável interação, sonolência aparente | Confirmação automática de uso de celular |

## Estado atual (honesto)

**Checkpoint jul/2026 (branch `feat/painel-de-sentimentos`):** ver [ESTAGIO_ATUAL.md](ESTAGIO_ATUAL.md) — oclusão vs cabeça baixa calibrada em [CALIBRACAO_OCLUSAO_VS_CABECA_BAIXA.md](CALIBRACAO_OCLUSAO_VS_CABECA_BAIXA.md).

| Módulo | Estado | Modo típico | Validação | Observações |
|--------|--------|-------------|-----------|-------------|
| Presença (YuNet + FaceNet) | Funcional no runtime | produção (legado) | Testes + uso local | Thresholds congelados `presence-yaml-2026-07-23` |
| Cadastro facial | Funcional no runtime | — | Manual / API | Embeddings locais |
| Reconhecimento simultâneo | Funcional no runtime | — | Testes dedup/margin | FAISS ou linear |
| Dedup / sessões | Funcional no runtime | — | Testes | Isolado de analytics |
| Modo demo | Funcional e validado em demo | `RUNTIME_MODE=demo` | 54 testes incl. E2E | 8 alunos fictícios; DB separado |
| RTSP Intelbras | Bloqueado por hardware/credencial | `rtsp` | Pendente | Placeholder `PASSWORD` |
| Offline (vídeo/pasta) | Parcialmente funcional | `offline` | Pendente corpus | Sem labels ≠ validação real |
| Observation quality | Funcional no runtime RTSP | debug | Testes + webcam | Conectado; sem validação científica |
| Landmarks / facial_features | Funcional (MediaPipe Tasks Face Landmarker) | debug | Testes + webcam | EAR/boca/yaw/pitch/roll reais |
| Expressão FER | Funcional (ONNX ferplus; TF opcional) | debug | Testes + webcam | Health check real; não é diagnóstico |
| Atenção / sonolência | Funcional temporal | debug | Testes + webcam | Depende de landmarks |
| Celular YOLO | Funcional (ultralytics yolov8n) | debug | Testes + webcam | Nunca `confirmed` automático |
| WebSocket RTSP | Funcional | — | Testes manuais | `live_tracks`, summary, métricas ~1 Hz |
| Dashboard / debug | Funcional | — | Manual | null ≠ zero; `/debug/vision` |
| Expressão FER | Experimental | debug/shadow | Testes; latência real se modelo OK | **não aprovado p/ produção** |
| Atenção / sonolência | Experimental | debug | Testes temporais | Thresholds configuráveis |
| Celular | Indisponível explícito (YOLO off) | debug | Testes status | Sem YOLO no core |
| Clima da turma | Parcialmente funcional | — | Pendente | Agregado; sem nota individual |
| Dashboard React `/dashboard` | Funcional e validado em demo | production (UI) | typecheck+build | |
| `/debug/vision` | Funcional | — | Manual | localhost + auth |
| `/dashboard-legacy` | Funcional (legado) | — | Manual | Presença/câmeras |
| API v1 + WebSocket | Funcional e validado em demo | — | Testes HTTP/WS | |
| Persistência demo | Funcional em demo | — | Testes | `data/demo/dulino_edge_demo.db` |
| Migration 005 | Experimental | gated | Testes em temp | Não aplicar no prod por default |
| LXP | Mock / outbox | disabled ou demo | Testes | Sem `HttpLXPClient` |

Tags Git de rollback: `baseline-fase-0`, `pre-spike-sanitized` (**não apagar**).

## Início rápido

```powershell
# Backend
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Demo (sem câmera)
$env:RUNTIME_MODE="demo"
uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend (dashboard educacional)
cd frontend
npm install
npm run typecheck
npm run build
cd ..

# Testes
pytest tests -q
```

| URL | Função |
|-----|--------|
| http://127.0.0.1:8000/dashboard | Dashboard educacional (React) |
| http://127.0.0.1:8000/debug/vision | Debug técnico |
| http://127.0.0.1:8000/dashboard-legacy | Painel legado |
| http://127.0.0.1:8000/docs | OpenAPI |

Webcam local: ver [OPERATIONS.md](OPERATIONS.md) (índice OpenCV; neste ambiente o índice `0` pode ser preto e o `1` a webcam real).

## Navegação

| Documento | Conteúdo |
|-----------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Arquitetura, pipelines, módulos, repositório |
| [OPERATIONS.md](OPERATIONS.md) | Instalação, config, execução, backup |
| [API.md](API.md) | REST v1, WebSocket, schemas |
| [TESTING.md](TESTING.md) | Testes automatizados e manuais |
| [SECURITY_PRIVACY.md](SECURITY_PRIVACY.md) | LGPD, ética, segurança |
| [ROADMAP.md](ROADMAP.md) | Pendências, decisões, próximos passos |
| [MODULAR_CLASSROOM_SCENARIOS.md](MODULAR_CLASSROOM_SCENARIOS.md) | Levantamento de cenários reais além do P0 (somente documentação) |
| [LESSON_CONTEXT_CONFIGURATION.md](LESSON_CONTEXT_CONFIGURATION.md) | Modelo conceitual de configuração modular da aula |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Problemas e soluções |
