#!/usr/bin/env python3
"""Probe de distância: anota tamanho aproximado do bbox facial.

Não altera produto. Opcionalmente lê um frame de arquivo (recomendado) ou webcam index.

Exemplos:
  python scripts/capture_distance_probe.py --image path/to/frame.jpg --distance-m 2.0
  python scripts/capture_distance_probe.py --webcam 0 --distance-m 1.0 --dry-run

Detecção: tenta OpenCV YuNet se modelo local existir; senão marca NÃO TESTADO.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
LOG_CSV = ROOT / "manifests" / "camera_vip5440_log.csv"
# Caminho somente LEITURA do YuNet do projeto (não modifica)
# ROOT = .../modulo2_poc → parents[2] = repo Presenca
REPO_YUNET = ROOT.parents[2] / "data" / "opencv_models" / "face_detection_yunet_2023mar.onnx"


def detect_faces_yunet(frame, model_path: Path):
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(model_path), "", (w, h), 0.7, 0.3, 5000)
    detector.setInputSize((w, h))
    _, faces = detector.detect(frame)
    if faces is None:
        return []
    out = []
    for f in faces:
        x, y, bw, bh = map(float, f[:4])
        out.append({"x": x, "y": y, "w": bw, "h": bh, "area": bw * bh, "score": float(f[-1])})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, default=None)
    ap.add_argument("--webcam", type=int, default=None)
    ap.add_argument("--distance-m", type=float, required=True)
    ap.add_argument("--zona", type=str, default="centro")
    ap.add_argument("--pose", type=str, default="front")
    ap.add_argument("--oculos", type=str, default="no")
    ap.add_argument("--iluminacao", type=str, default="normal")
    ap.add_argument("--dry-run", action="store_true", help="Não grava CSV")
    ap.add_argument("--out-json", type=Path, default=RESULTS / "capture_distance_probe_last.json")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "distance_m": args.distance_m,
        "zona": args.zona,
        "status": "NÃO TESTADO",
        "faces": [],
        "reason": None,
    }

    try:
        import cv2
    except Exception as e:
        report["reason"] = f"OpenCV indisponível: {e}"
        args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0

    frame = None
    if args.image:
        frame = cv2.imread(str(args.image))
        if frame is None:
            report["reason"] = f"Falha ao ler imagem {args.image}"
            args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False))
            return 0
    elif args.webcam is not None:
        cap = cv2.VideoCapture(args.webcam)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            report["reason"] = f"Webcam index {args.webcam} sem frame"
            args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False))
            return 0
    else:
        report["reason"] = "Informe --image ou --webcam. Sem captura = NAO TESTADO."
        args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))
        return 0

    if not REPO_YUNET.exists():
        report["reason"] = f"YuNet não encontrado em {REPO_YUNET} (somente leitura)"
        args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0

    faces = detect_faces_yunet(frame, REPO_YUNET)
    report["faces"] = faces
    report["status"] = "OK" if faces else "SEM_FACE"
    report["frame_shape"] = list(frame.shape)
    report["reason"] = None if faces else "Nenhuma face detectada neste frame"

    if not args.dry_run and faces:
        LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
        write_header = not LOG_CSV.exists() or LOG_CSV.stat().st_size == 0
        with LOG_CSV.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(
                    [
                        "ts",
                        "altura_camera_m",
                        "inclinacao_aprox_graus",
                        "distancia_aluno_m",
                        "zona",
                        "iluminacao",
                        "n_pessoas",
                        "pose",
                        "oculos",
                        "resolucao_stream",
                        "bbox_w_px",
                        "bbox_h_px",
                        "face_area_px",
                        "detectou",
                        "reconheceu",
                        "score",
                        "margin",
                        "observacao",
                    ]
                )
            best = max(faces, key=lambda x: x["area"])
            h, w_img = frame.shape[:2]
            w.writerow(
                [
                    report["ts"],
                    "",
                    "",
                    args.distance_m,
                    args.zona,
                    args.iluminacao,
                    len(faces),
                    args.pose,
                    args.oculos,
                    f"{w_img}x{h}",
                    round(best["w"], 1),
                    round(best["h"], 1),
                    round(best["area"], 1),
                    "sim",
                    "N/A",
                    "",
                    "",
                    "probe_poc",
                ]
            )

    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "n_faces": len(faces), "out": str(args.out_json)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
