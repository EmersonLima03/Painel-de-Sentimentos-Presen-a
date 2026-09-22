#!/usr/bin/env python3
"""
Captura probes alinhados (product crop) para o benchmark.

Exemplos:
  python scripts/benchmark_occlusion_capture_probes.py --condition glasses_degree --student-id lab01 --distance-m 2 --webcam 2
  python scripts/benchmark_occlusion_capture_probes.py --condition no_glasses --student-id lab01 --distance-m 2
  python scripts/benchmark_occlusion_capture_probes.py --condition unknown --student-id UNKNOWN --distance-m 2

Salva JPG 112 alinhado em results/benchmark_occlusion/probes/<condition>/
NÃO grava banco / produção.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from benchmark_occlusion_common import (  # noqa: E402
    ALIGNMENT_MODE_PRODUCT,
    BENCH_OUT,
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    ensure_bench_dirs,
    quality_of_crop,
    save_json,
    select_primary_face,
    utc_now,
)
from poc_common import open_webcam  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", required=True, help="no_glasses|glasses_dark|glasses_degree|unknown|...")
    ap.add_argument("--student-id", required=True, help="lab01|lab02|UNKNOWN")
    ap.add_argument("--distance-m", type=float, default=2.0)
    ap.add_argument("--webcam", type=int, default=2)
    ap.add_argument("--n", type=int, default=5, help="número de capturas válidas")
    ap.add_argument("--timeout-s", type=float, default=60.0)
    args = ap.parse_args()

    ensure_bench_dirs()
    out_dir = BENCH_OUT / "probes" / args.condition
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        cap = open_webcam(args.webcam)
    except Exception as e:
        save_json(
            out_dir / f"CAPTURE_{args.student_id}_FAILED.json",
            {"status": "NÃO TESTADO", "reason": str(e), "ts": utc_now()},
        )
        print({"status": "NÃO TESTADO", "reason": str(e)})
        return 2

    saved = []
    t0 = time.time()
    print(f"[capture] condition={args.condition} id={args.student_id} d={args.distance_m}m — posicione-se")
    try:
        while len(saved) < args.n and (time.time() - t0) < args.timeout_s:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            faces = detect_faces_yunet(frame, score_th=0.65)
            face = select_primary_face(faces, frame_shape=frame.shape[:2])
            if face is None:
                continue
            try:
                crop, meta = aligned_crop(frame, face)
            except AlignmentError as e:
                print(" alignment_error", e)
                continue
            if meta.get("alignment_mode") != ALIGNMENT_MODE_PRODUCT:
                continue
            lab, q = quality_of_crop(crop)
            if lab == "poor" or q < 0.35:
                continue
            idx = len(saved) + 1
            tag = f"{args.student_id}_d{args.distance_m:g}_{args.condition}_{idx:02d}"
            if args.condition.startswith("glasses") and args.student_id.upper() != "UNKNOWN":
                # também salva alias para multi-template
                alias = out_dir / f"{args.student_id}_glasses.jpg"
                if not alias.exists():
                    cv2.imwrite(str(alias), crop)
            path = out_dir / f"{tag}.jpg"
            cv2.imwrite(str(path), crop)
            saved.append(
                {
                    "path": str(path),
                    "quality": round(float(q), 4),
                    "quality_label": lab,
                    "bbox_w": round(float(face["w"]), 1),
                    "bbox_h": round(float(face["h"]), 1),
                    "face_score": round(float(face.get("face_score") or 0), 3),
                    "alignment_mode": meta.get("alignment_mode"),
                    "n_faces_raw": len(faces),
                }
            )
            print(f"  saved {path.name} q={q:.3f} bbox={face['w']:.0f}x{face['h']:.0f}")
            time.sleep(0.35)
    finally:
        cap.release()

    meta = {
        "ts": utc_now(),
        "condition": args.condition,
        "student_id": args.student_id,
        "distance_m": args.distance_m,
        "webcam": args.webcam,
        "n_requested": args.n,
        "n_saved": len(saved),
        "alignment_mode": ALIGNMENT_MODE_PRODUCT,
        "samples": saved,
        "status": "OK" if len(saved) >= args.n else ("INCOMPLETE" if saved else "NÃO TESTADO"),
    }
    save_json(out_dir / f"CAPTURE_{args.student_id}.json", meta)
    print(meta["status"], "n=", len(saved))
    return 0 if meta["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
