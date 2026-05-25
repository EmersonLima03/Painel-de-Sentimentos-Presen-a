# Teste: 8–10 pessoas em fila (1 câmera)

Objetivo: validar **vários rostos** na mesma imagem, em **distâncias diferentes**, antes de escalar para sala com 4 câmeras e ~40 alunos.

## 1. Dependências (uma vez)

O padrão do projeto é **YuNet + FaceNet** (funciona no Windows sem compilar nada).

Na primeira execução o YuNet baixa `face_detection_yunet_2023mar.onnx` (~230 KB) para `data/opencv_models/`.

**Opcional (Linux / PC com compilador C++):** `pip install insightface onnxruntime` e no YAML use `detector: insightface`, `embedder: insightface`.

## 2. Configuração (.env)

```env
SIMULATION=0
REAL=1
ENABLE_DEBUG_SNAPSHOT=1
ENABLE_DEBUG_UI=1
PRESENCE_ALWAYS_ON=1
```

O `config.yaml` já está com:

- `vision.detector: yunet`
- `vision.embedder: facenet`
- `vision.max_faces: 16`

## 3. Subir o servidor

```powershell
.\scripts\run_dev.ps1
```

Confira no `/health`:

- `detector_backend`: `yunet`
- `embedder_backend`: `facenet`

## 4. Montagem do teste físico

1. Câmera **1080p**, altura ~2 m, olhando para a fila (não de cima).
2. **8–10 pessoas** em linha: 2 perto, 4 no meio, 2 mais longe (~3–4 m se a sala permitir).
3. Luz **na frente** dos rostos (evitar janela atrás).
4. Cadastre cada pessoa na **mesma distância** em que ficará no teste (`/debug/enroll` ou `/enroll/webcam`).

## 5. O que olhar

| URL | O que ver |
|-----|-----------|
| `/debug/viewer` | Caixas em todos os rostos; nomes estáveis |
| `/debug/overlay_matches` | Campo `faces` ≈ número de pessoas visíveis |
| `/health` | `matcher_embeddings` > 0 após cadastro |

**Passou:** detecta ≥ 80% das pessoas visíveis e não troca nomes entre vizinhos.  
**Falhou:** muitos `faces: 0` ou caixa no tronco → aproximar fila ou subir `insightface_det_size` para `1280` (mais lento).

## 6. Ajustes rápidos (config.yaml)

| Sintoma | Ajuste |
|---------|--------|
| Não acha rostos longe | Aproximar fila ou câmera com zoom; testar `detector: insightface` no Linux |
| Muito lento no mini PC | `sampling_seconds: 2.5` |
| Nome troca entre dois alunos | `match_margin: 0.12` |
| Descarta rosto pequeno | `min_face_size: 14` |

## 7. Próximo passo (sala 40 alunos)

- 4 câmeras com **zoom** em faixas da sala (não uma câmera para os 40).
- Manter `max_faces: 16` por câmera.
- Mini PC com **16–32 GB RAM**; GPU opcional depois.
