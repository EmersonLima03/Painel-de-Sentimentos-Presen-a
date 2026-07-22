# Evolução Presença — melhor dos 5 projetos GitHub

Seu produto **Presenca** (YuNet + FaceNet/FAISS + FastAPI) é a base correta. Os 5 repositórios foram usados só como **referência**; o código integrado está neste repo.

## O que entrou no Presenca

| Projeto | O que aproveitamos | Onde no Presenca |
|---------|-------------------|------------------|
| **Real-Time-Classroom** | Mini-XCEPTION (emoção), mapeamento FER→engajamento, DNN SSD fallback | `app/vision/emotion_engagement.py`, `dnn_detector.py`, `detector` auto/dnn |
| **Engagement-Recognition** | Rótulos engaged/disengaged (happy/neutral vs angry/sad…) | `emotion_engagement.py` |
| **AI-Based-Student** | Relatório diário de presença | `GET /reports/attendance/today` |
| **STUDENT-ATTENDANCE (LBPH)** | — | Não usado (LBPH inferior a embeddings) |
| **Driver-Monitoring** | Ideia YOLO distração | Futuro opcional; não no edge hoje |

## Configuração recomendada (sala ~30 alunos, 4 câmeras)

Edite `config.yaml`:

```yaml
device:
  default_camera_index: 2   # USB/Iriun conforme GET /cameras/devices

vision:
  detector: yunet           # ou auto (yunet → dnn → mediapipe)
  embedder: onnx            # mais leve no Ryzen se onnxruntime OK
  max_faces: 30
  engagement:
    backend: hybrid         # emotion | heuristic | hybrid
    model_version: eng-v1-emotion
    window_seconds: 10
    sampling_seconds: 5
```

## Primeira execução (“agora vai”)

```powershell
cd Presenca
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python scripts\download_models.py
pip install -r requirements-emotion.txt   # opcional, para emoção real

copy .env.example .env
# REAL=true, SIMULATION=false, DISABLE_RTSP=false

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Cadastro: `POST /enroll/webcam` ou UI `/debug/enroll`
- Presença: eventos `attendance_checkin`
- Engajamento: `engagement_window` com `model_version: eng-v1-emotion`
- Relatórios: `GET /reports/attendance/today`, `GET /reports/engagement/summary?room_id=DEV`

## Backends de engajamento

- **heuristic** — brilho/contraste (`eng-v0`), sem TensorFlow
- **emotion** — Mini-XCEPTION por ROI (precisa `tf-keras` + modelo em `data/models/`)
- **hybrid** (padrão) — emoção se rosto ≥ 40px; senão heurística

## RTSP Intelbras

Ative câmeras em `config.yaml` com `rtsp_url` e `enabled: true`. Uma URL por canal; `subtype=0` para stream principal.

## LGPD

Continue usando **embeddings** no edge + sync; não envie fotos brutas. Emoção roda só no ROI local, agregada em `engagement_window`.
