#!/usr/bin/env python3
"""Reconhecimento / distancia / UNKNOWN / oculos / pose — galeria TEMP FaceNet.

Exemplos:
  python scripts/run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01
  python scripts/run_recognize_probe.py --webcam 2 --distance-m 2 --expected UNKNOWN
  python scripts/run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --glasses yes --pose front
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from poc_common import (
    RESULTS,
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    embed_crop,
    ensure_dirs,
    load_gallery_facenet,
    match_gallery,
    open_webcam,
    quality_of_crop,
)

LOG = RESULTS / "xwf_recognize_log.csv"


def append_log(row: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    write_header = not LOG.exists() or LOG.stat().st_size == 0
    with LOG.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "ts",
                "distance_m",
                "pose",
                "glasses",
                "expected",
                "decision",
                "top1_id",
                "top1_score",
                "margin",
                "quality",
                "bbox_w",
                "bbox_h",
                "frame_w",
                "frame_h",
                "n_faces",
                "threshold_exp",
                "margin_exp",
                "notes",
            ],
        )
        if write_header:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webcam", type=int, default=2)
    ap.add_argument("--distance-m", type=float, required=True)
    ap.add_argument("--expected", type=str, required=True, help="student_id esperado ou UNKNOWN")
    ap.add_argument("--pose", type=str, default="front")
    ap.add_argument("--glasses", type=str, default="no")
    ap.add_argument("--threshold", type=float, default=0.70, help="Experimental POC (nao grava producao)")
    ap.add_argument("--margin", type=float, default=0.10, help="Experimental POC")
    ap.add_argument("--settle-s", type=float, default=1.5)
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    ensure_dirs()
    gallery = load_gallery_facenet()
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "distance_m": args.distance_m,
        "expected": args.expected,
        "pose": args.pose,
        "glasses": args.glasses,
        "gallery_templates": len(gallery),
        "threshold_experimental": args.threshold,
        "margin_experimental": args.margin,
        "status": "NAO_TESTADO",
    }
    if not gallery and args.expected.upper() != "UNKNOWN":
        report["reason"] = "Galeria TEMP vazia — rode run_enroll_guided_a.py antes"
        path = RESULTS / f"recognize_d{args.distance_m}_{args.pose}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "reason": report["reason"]}, ensure_ascii=True))
        return 1

    try:
        cap = open_webcam(args.webcam)
    except Exception as e:
        report["reason"] = str(e)
        print(json.dumps({"status": "NAO_TESTADO", "reason": str(e)}, ensure_ascii=True))
        return 1

    import cv2

    time.sleep(args.settle_s)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        report["reason"] = "Falha ao capturar frame"
        print(json.dumps(report, ensure_ascii=True))
        return 1

    h, w = frame.shape[:2]
    faces = detect_faces_yunet(frame)
    report["frame_w"] = w
    report["frame_h"] = h
    report["n_faces"] = len(faces)
    if not faces:
        report["status"] = "SEM_FACE"
        report["decision"] = "UNKNOWN"
        path = RESULTS / f"recognize_d{args.distance_m}_{args.pose}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "n_faces": 0}, ensure_ascii=True))
        return 2

    face = faces[0]
    try:
        crop, align_meta = aligned_crop(frame, face)
    except AlignmentError as e:
        report["status"] = "ALIGNMENT_FAIL"
        report["alignment_error"] = str(e)
        report["decision"] = "UNKNOWN"
        path = RESULTS / f"recognize_d{args.distance_m}_{args.pose}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "error": str(e)}, ensure_ascii=True))
        return 3
    qlabel, q = quality_of_crop(crop)
    emb = embed_crop(crop)
    m = match_gallery(emb, gallery, args.threshold, args.margin)
    decision = m["decision"]
    report.update(
        {
            "status": "OK",
            "quality": round(q, 4),
            "quality_label": qlabel,
            "bbox_w": round(face["w"], 1),
            "bbox_h": round(face["h"], 1),
            "alignment_mode": align_meta.get("alignment_mode"),
            **m,
        }
    )
    # avaliacao vs expected
    exp = args.expected
    if exp.upper() == "UNKNOWN":
        report["unknown_ok"] = decision == "UNKNOWN"
        report["fp"] = decision != "UNKNOWN"
    else:
        report["tp"] = decision == exp
        report["fn"] = decision == "UNKNOWN"
        report["fp"] = decision not in (exp, "UNKNOWN")

    append_log(
        {
            "ts": report["ts"],
            "distance_m": args.distance_m,
            "pose": args.pose,
            "glasses": args.glasses,
            "expected": exp,
            "decision": decision,
            "top1_id": m.get("top1_id"),
            "top1_score": m.get("top1_score"),
            "margin": m.get("margin"),
            "quality": report["quality"],
            "bbox_w": report["bbox_w"],
            "bbox_h": report["bbox_h"],
            "frame_w": w,
            "frame_h": h,
            "n_faces": len(faces),
            "threshold_exp": args.threshold,
            "margin_exp": args.margin,
            "notes": "xwf_poc",
        }
    )

    if args.preview:
        x, y, bw, bh = map(int, (face["x"], face["y"], face["w"], face["h"]))
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
        cv2.putText(
            frame,
            f"{decision} s={m.get('top1_score')} m={m.get('margin')}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )
        cv2.imshow("m2_recognize_poc", frame)
        cv2.waitKey(1500)
        cv2.destroyAllWindows()

    out = RESULTS / f"recognize_d{args.distance_m}_{args.pose}_{args.glasses}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": decision,
                "top1_score": m.get("top1_score"),
                "margin": m.get("margin"),
                "bbox": [report["bbox_w"], report["bbox_h"]],
                "out": str(out),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
