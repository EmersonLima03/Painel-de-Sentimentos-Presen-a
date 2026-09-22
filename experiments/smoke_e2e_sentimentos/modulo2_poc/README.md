# Módulo 2 — POC isolado (Enrollment escalável)

**Status:** estudo + scaffold + **roteiro XWF-1080P** (lab). Não é cadastro definitivo.

## Proteções

- Não altera `app/vision/**`, `config.tri.yaml`, M1, M3, LXP, SyncWorker.
- Não sobrescreve `face_embeddings` / FAISS de produção.
- Sem `reload_matcher`, sem commit, sem pip global.

## Estratégia prioritária

**A — Enrollment guiado e automatizado** (`scripts/run_enroll_guided_a.py`).

## Câmeras

| Câmera | Papel |
|--------|--------|
| **XWF-1080P USB** | Lab / prova do mecanismo — ver `RUNBOOK_TESTES_XWF.md` |
| **VIP-5440-IA** | Hardware definitivo da sala — `PROTOCOL_CAMERA_VIP5440.md` (quando disponível) |

## UI visual (Enrollment Guiado A)

```powershell
cd experiments/smoke_e2e_sentimentos/modulo2_poc
..\..\..\venv\Scripts\python.exe scripts\ui_server.py --port 8765
```

Abrir: **http://127.0.0.1:8765/**

Playwright:

```powershell
cd ..\fase5b
$env:NODE_PATH=(Resolve-Path .\node_modules).Path
node ..\modulo2_poc\run_playwright_m2_ui.cjs
```

## Como rodar (scripts CLI XWF)

```powershell
cd experiments/smoke_e2e_sentimentos/modulo2_poc
python scripts\list_webcams.py
python scripts\run_enroll_guided_a.py --student-id lab01 --webcam 2 --preview
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01
```

Passo a passo completo: **`RUNBOOK_TESTES_XWF.md`**.

## Scripts

| Script | Uso |
|--------|-----|
| `list_webcams.py` | Descobrir índice USB |
| `run_enroll_guided_a.py` | Estratégia A (galeria TEMP FaceNet) |
| `run_recognize_probe.py` | Distância / pose / óculos / UNKNOWN |
| `run_multiperson_probe.py` | Multi-rosto no POC |
| `capture_distance_probe.py` | Bbox px × distância |
| `bench_gallery_offline.py` | Match offline TEMP |
| `bench_candidates_isolated.py` | Disponibilidade FaceNet/ArcFace/SFace |

## Galeria TEMP

`results/gallery_temp/facenet/<student_id>/*.npy` — **nunca** misturar ArcFace/SFace nesta pasta.
