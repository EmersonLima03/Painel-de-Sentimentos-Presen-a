# Dependências — baseline Fase 0

**Python:** 3.12.9  
**Venv:** `venv/`  
**Gerado:** 2026-07-23

## Core instalado (versões observadas)

| Pacote | Versão |
|--------|--------|
| fastapi | 0.136.3 |
| uvicorn | 0.49.0 |
| sqlalchemy | 2.0.50 |
| alembic | 1.18.4 |
| numpy | 1.26.4 |
| opencv-contrib-python | 4.10.0.84 |
| torch | 2.2.2 |
| torchvision | 0.17.2 |
| facenet-pytorch | 2.6.0 |
| mediapipe | 0.10.35 |
| faiss-cpu | 1.14.2 |
| onnxruntime | 1.26.0 |
| httpx | 0.28.1 |
| pydantic | 2.13.4 |
| PyYAML | 6.0.3 |
| structlog | 25.5.0 |
| cryptography | 48.0.0 |
| python-dotenv | 1.2.2 |
| pytest | 9.0.3 |

## Extras (não no core até decisão do spike)

| Arquivo | Uso |
|---------|-----|
| `requirements-emotion.txt` | FER / TensorFlow (legado) |
| `requirements-spike-hsemotion.txt` | venv isolado HSEmotion (Fase 0.5) |
| `requirements-spike-deepface.txt` | venv isolado DeepFace (Fase 0.5) |

**Regra:** não instalar HSEmotion/DeepFace no `venv` principal antes da decisão do spike.
