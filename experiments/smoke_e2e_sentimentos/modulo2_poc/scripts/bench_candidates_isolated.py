#!/usr/bin/env python3
"""Compara candidatos de embedding de forma ISOLADA (sem alterar produto).

Baseline FaceNet / Challenger ArcFace ONNX / Challenger SFace:
  - Só executa se pesos + deps estiverem disponíveis LOCALMENTE no POC.
  - NÃO baixa buffalo_l automaticamente (licença comercial InsightFace).
  - NÃO altera app/vision, config, DB de produção.

Saída: results/bench_candidates_isolated.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MODELS = ROOT / "models"


def _try_import_cv2():
    try:
        import cv2  # noqa: F401
        import numpy as np  # noqa: F401

        return True, None
    except Exception as e:
        return False, str(e)


def probe_facenet() -> dict:
    """Somente verifica se facenet_pytorch está importável — sem inferência se sem imagem."""
    try:
        import facenet_pytorch  # noqa: F401

        return {
            "candidate": "FaceNet (facenet_pytorch)",
            "status": "DISPONÍVEL_IMPORT",
            "inference": "NÃO TESTADO",
            "reason": "Sem corpus de crops no POC; import OK no ambiente atual",
        }
    except Exception as e:
        return {
            "candidate": "FaceNet (facenet_pytorch)",
            "status": "NÃO TESTADO",
            "inference": "NÃO TESTADO",
            "reason": f"Import falhou ou não instalado neste interpretador: {e}",
        }


def probe_arcface_onnx() -> dict:
    """Não baixa pesos. Exige models/w600k_r50.onnx no POC + onnxruntime."""
    model = MODELS / "w600k_r50.onnx"
    try:
        import onnxruntime as ort  # noqa: F401
    except Exception as e:
        return {
            "candidate": "ArcFace ONNX w600k_r50",
            "status": "NÃO TESTADO",
            "inference": "NÃO TESTADO",
            "reason": f"onnxruntime indisponível: {e}",
            "license_note": "Pesos buffalo_l: uso comercial requer licença InsightFace (ver relatório).",
        }
    if not model.exists():
        return {
            "candidate": "ArcFace ONNX w600k_r50",
            "status": "NÃO TESTADO",
            "inference": "NÃO TESTADO",
            "reason": f"Modelo ausente em {model} (download manual + revisão de licença comercial obrigatória)",
            "license_note": "Código InsightFace MIT; pesos pretrained research-only sem licença comercial.",
        }
    try:
        import onnxruntime as ort

        t0 = time.perf_counter()
        sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        load_ms = (time.perf_counter() - t0) * 1000
        return {
            "candidate": "ArcFace ONNX w600k_r50",
            "status": "MODELO_CARREGADO",
            "inference": "NÃO TESTADO",
            "load_ms": round(load_ms, 2),
            "inputs": [i.name for i in sess.get_inputs()],
            "reason": "Sessão ORT OK; sem crops de teste → métricas FP/TP NÃO TESTADAS",
            "license_note": "Confirmar licença comercial antes de uso empresarial.",
        }
    except Exception as e:
        return {
            "candidate": "ArcFace ONNX w600k_r50",
            "status": "NÃO TESTADO",
            "inference": "NÃO TESTADO",
            "reason": str(e),
        }


def probe_sface() -> dict:
    model = MODELS / "face_recognition_sface_2021dec.onnx"
    ok, err = _try_import_cv2()
    if not ok:
        return {
            "candidate": "OpenCV SFace",
            "status": "NÃO TESTADO",
            "inference": "NÃO TESTADO",
            "reason": f"OpenCV indisponível: {err}",
            "license_note": "OpenCV Zoo SFace: Apache-2.0 (modelo/directory).",
        }
    if not model.exists():
        return {
            "candidate": "OpenCV SFace",
            "status": "NÃO TESTADO",
            "inference": "NÃO TESTADO",
            "reason": f"ONNX ausente em {model}. Baixar do OpenCV Zoo sob Apache-2.0 se autorizado.",
            "license_note": "https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface",
        }
    try:
        import cv2

        t0 = time.perf_counter()
        net = cv2.FaceRecognizerSF.create(str(model), "")
        load_ms = (time.perf_counter() - t0) * 1000
        return {
            "candidate": "OpenCV SFace",
            "status": "MODELO_CARREGADO",
            "inference": "NÃO TESTADO",
            "load_ms": round(load_ms, 2),
            "reason": "FaceRecognizerSF OK; sem crops → métricas NÃO TESTADAS",
            "handle": str(type(net)),
            "license_note": "Apache-2.0 (OpenCV Zoo SFace).",
        }
    except Exception as e:
        return {
            "candidate": "OpenCV SFace",
            "status": "NÃO TESTADO",
            "inference": "NÃO TESTADO",
            "reason": str(e),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=RESULTS / "bench_candidates_isolated.json")
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "scope": "isolated_poc",
        "product_untouched": True,
        "candidates": [
            probe_facenet(),
            probe_arcface_onnx(),
            probe_sface(),
        ],
        "comparative_doc_only": ["InsightFace full", "DeepFace", "CompreFace"],
        "metrics_tp_fp_fn": "NÃO TESTADO",
        "note": "Sem corpus → não inventar superioridade de modelo.",
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "n": len(report["candidates"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
