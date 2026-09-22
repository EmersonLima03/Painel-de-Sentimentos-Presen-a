#!/usr/bin/env python3
"""Probe multi-pessoa no POC (nao altera single_subject_mode do produto).

Detecta TODOS os rostos YuNet no frame e, se houver galeria TEMP, tenta match 1:N por rosto.

  python scripts/run_multiperson_probe.py --webcam 2 --n-expected 2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webcam", type=int, default=2)
    ap.add_argument("--n-expected", type=int, default=0, help="Quantidade de pessoas esperadas (0=so observar)")
    ap.add_argument("--threshold", type=float, default=0.70)
    ap.add_argument("--margin", type=float, default=0.10)
    ap.add_argument("--settle-s", type=float, default=1.0)
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    ensure_dirs()
    gallery = load_gallery_facenet()
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "n_expected": args.n_expected,
        "gallery_templates": len(gallery),
        "single_subject_mode_product": "NAO_ALTERADO",
        "status": "NAO_TESTADO",
        "faces": [],
    }
    try:
        cap = open_webcam(args.webcam)
    except Exception as e:
        report["reason"] = str(e)
        out = RESULTS / "multiperson_last.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "NAO_TESTADO", "reason": str(e)}, ensure_ascii=True))
        return 1

    import cv2

    time.sleep(args.settle_s)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        report["reason"] = "Sem frame"
        print(json.dumps(report, ensure_ascii=True))
        return 1

    faces = detect_faces_yunet(frame, score_th=0.6)
    report["n_detected"] = len(faces)
    report["frame_shape"] = list(frame.shape)
    for i, face in enumerate(faces):
        try:
            crop, align_meta = aligned_crop(frame, face)
        except AlignmentError as e:
            report["faces"].append(
                {
                    "idx": i,
                    "bbox_w": round(face["w"], 1),
                    "bbox_h": round(face["h"], 1),
                    "alignment_error": str(e),
                    "decision": "UNKNOWN",
                    "valid_for_product_fidelity": False,
                }
            )
            continue
        qlabel, q = quality_of_crop(crop)
        entry = {
            "idx": i,
            "bbox_w": round(face["w"], 1),
            "bbox_h": round(face["h"], 1),
            "det_score": round(face["det_score"], 4),
            "quality": round(q, 4),
            "quality_label": qlabel,
            "alignment_mode": align_meta.get("alignment_mode"),
            "valid_for_product_fidelity": align_meta.get("alignment_mode") == "product_crop_aligned_face",
        }
        if gallery:
            emb = embed_crop(crop)
            m = match_gallery(emb, gallery, args.threshold, args.margin)
            entry.update(m)
        else:
            entry["decision"] = "N/A_sem_galeria"
        report["faces"].append(entry)
        if args.preview:
            x, y, w, h = map(int, (face["x"], face["y"], face["w"], face["h"]))
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(
                frame,
                f"#{i} {entry.get('decision', '')}",
                (x, max(20, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

    report["status"] = "OK"
    if args.n_expected:
        report["count_match_expected"] = len(faces) == args.n_expected

    if args.preview:
        cv2.imshow("m2_multiperson_poc", frame)
        cv2.waitKey(2000)
        cv2.destroyAllWindows()

    out = RESULTS / f"multiperson_n{args.n_expected or 'obs'}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"status": "OK", "n_detected": len(faces), "out": str(out)},
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
