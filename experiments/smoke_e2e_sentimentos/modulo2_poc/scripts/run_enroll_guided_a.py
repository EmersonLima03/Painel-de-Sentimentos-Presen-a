#!/usr/bin/env python3
"""Estrategia A — enrollment guiado/automatizado (POC isolado).

Salva SOMENTE em results/gallery_temp/facenet_aligned_v2/<student_id>/
Nao grava face_embeddings de producao. Nao chama reload_matcher.

Exemplo:
  python scripts/run_enroll_guided_a.py --student-id lab01 --student-name "Aluno Lab" --webcam 2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import numpy as np

from poc_common import (
    ALIGNMENT_MODE_PRODUCT,
    CROPS_ACTIVE,
    GALLERY_ACTIVE,
    RESULTS,
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    embed_crop,
    ensure_dirs,
    estimate_face_yaw,
    open_webcam,
    quality_of_crop,
)

STEPS = [
    {
        "id": "front",
        "prompt": "Posicione o rosto DE FRENTE para a camera. Mantenha estavel.",
        "required": True,
    },
    {
        "id": "yaw_right",
        "prompt": "Vire levemente a cabeca para a DIREITA e mantenha.",
        "required": True,
    },
    {
        "id": "yaw_left",
        "prompt": "Vire levemente a cabeca para a ESQUERDA e mantenha. (amostra opcional se --third)",
        "required": False,
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--student-id", required=True)
    ap.add_argument("--student-name", default="")
    ap.add_argument("--webcam", type=int, default=2, help="Index USB (XWF costuma ser 2)")
    ap.add_argument("--min-quality", type=float, default=0.55, help="Gate experimental do POC (nao e threshold de producao)")
    ap.add_argument("--stable-frames", type=int, default=8, help="Frames consecutivos com qualidade OK")
    ap.add_argument("--third", action="store_true", help="Forca terceira amostra (esquerda)")
    ap.add_argument("--timeout-s", type=float, default=45.0)
    ap.add_argument("--preview", action="store_true", help="Janela OpenCV (fechar com q apos captura)")
    args = ap.parse_args()

    ensure_dirs()
    out_dir = GALLERY_ACTIVE / args.student_id
    out_dir.mkdir(parents=True, exist_ok=True)
    crop_dir = CROPS_ACTIVE / args.student_id
    crop_dir.mkdir(parents=True, exist_ok=True)

    session = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "strategy": "A_guided_automated",
        "student_id": args.student_id,
        "student_name": args.student_name,
        "webcam": args.webcam,
        "min_quality_experimental": args.min_quality,
        "stable_frames": args.stable_frames,
        "gallery_root": str(out_dir),
        "crops_root": str(crop_dir),
        "gallery_version": "facenet_aligned_v2",
        "alignment_mode": ALIGNMENT_MODE_PRODUCT,
        "product_db_written": False,
        "samples": [],
        "status": "IN_PROGRESS",
    }

    try:
        cap = open_webcam(args.webcam)
    except Exception as e:
        session["status"] = "NAO_TESTADO"
        session["reason"] = str(e)
        path = RESULTS / f"enroll_{args.student_id}.json"
        path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": session["status"], "reason": session["reason"]}, ensure_ascii=True))
        return 1

    import cv2

    steps = [s for s in STEPS if s["required"] or args.third]
    print("=== Estrategia A — Enrollment guiado (POC) ===")
    print(f"Aluno: {args.student_id} | webcam={args.webcam} | min_quality={args.min_quality}")
    print("Galeria TEMP apenas. Producao NAO sera alterada.")
    print("Pressione Ctrl+C para abortar.\n")

    try:
        for step in steps:
            print(f"\n>> {step['prompt']}")
            print("   Aguardando qualidade adequada...")
            stable = 0
            t0 = time.time()
            best = None
            frames_seen = 0
            while time.time() - t0 < args.timeout_s:
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                frames_seen += 1
                faces = detect_faces_yunet(frame, score_th=0.65)
                if not faces:
                    stable = 0
                    if args.preview:
                        cv2.putText(frame, "Sem rosto", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        cv2.imshow("m2_enroll_poc", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break
                    continue
                face = faces[0]
                try:
                    crop, align_meta = aligned_crop(frame, face)
                except AlignmentError as e:
                    stable = 0
                    if frames_seen % 15 == 0:
                        print(f"   alignment_error: {e}")
                    continue
                if align_meta.get("alignment_mode") != ALIGNMENT_MODE_PRODUCT:
                    stable = 0
                    continue
                label, q = quality_of_crop(crop)
                yaw = estimate_face_yaw(face.get("landmarks") or [])
                msg = f"{step['id']} q={q:.2f} ({label}) face={int(face['w'])}x{int(face['h'])}px align={align_meta['alignment_mode']}"
                if q >= args.min_quality and label != "poor":
                    stable += 1
                    best = {
                        "frame": frame,
                        "face": face,
                        "crop": crop,
                        "q": q,
                        "label": label,
                        "align_meta": align_meta,
                        "yaw": yaw,
                    }
                    msg += f" stable={stable}/{args.stable_frames}"
                else:
                    stable = 0
                    best = None
                if args.preview:
                    x, y, w, h = map(int, (face["x"], face["y"], face["w"], face["h"]))
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0) if stable else (0, 165, 255), 2)
                    cv2.putText(frame, msg, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    cv2.imshow("m2_enroll_poc", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                else:
                    if frames_seen % 15 == 0:
                        print("  ", msg)
                if stable >= args.stable_frames and best is not None:
                    print(f"   Captura VALIDA ({step['id']}) qualidade={best['q']:.3f} align={best['align_meta']['alignment_mode']}")
                    emb = embed_crop(best["crop"])
                    npy_path = out_dir / f"{step['id']}.npy"
                    jpg_path = crop_dir / f"{step['id']}.jpg"
                    np.save(npy_path, emb)
                    cv2.imwrite(str(jpg_path), best["crop"])
                    session["samples"].append(
                        {
                            "step": step["id"],
                            "quality": round(float(best["q"]), 4),
                            "quality_label": best["label"],
                            "bbox_w": round(float(best["face"]["w"]), 1),
                            "bbox_h": round(float(best["face"]["h"]), 1),
                            "yaw": None if best["yaw"] is None else round(float(best["yaw"]), 4),
                            "alignment_mode": best["align_meta"]["alignment_mode"],
                            "align_bbox": best["align_meta"].get("bbox"),
                            "landmarks_ok": True,
                            "npy": str(npy_path),
                            "crop": str(jpg_path),
                            "valid_for_product_fidelity": True,
                            "frames_seen": frames_seen,
                            "elapsed_s": round(time.time() - t0, 2),
                        }
                    )
                    break
            else:
                print(f"   Qualidade insuficiente / timeout no passo {step['id']}")
                session["samples"].append(
                    {
                        "step": step["id"],
                        "status": "REJECTED_OR_TIMEOUT",
                        "frames_seen": frames_seen,
                    }
                )
                if step["required"]:
                    session["status"] = "FAIL_REQUIRED_SAMPLE"
                    break
    except KeyboardInterrupt:
        session["status"] = "ABORTED"
    finally:
        cap.release()
        if args.preview:
            cv2.destroyAllWindows()

    ok_samples = [s for s in session["samples"] if "npy" in s]
    if session["status"] == "IN_PROGRESS":
        session["status"] = "OK" if len(ok_samples) >= 2 else "INCOMPLETE"
    session["n_ok_samples"] = len(ok_samples)
    session["note"] = "Numero final de amostras recomendado = resultado empirico; nao presumir."

    out_json = RESULTS / f"enroll_{args.student_id}_aligned_v2.json"
    out_json.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": session["status"], "n_ok": len(ok_samples), "out": str(out_json), "alignment_mode": ALIGNMENT_MODE_PRODUCT}, ensure_ascii=True))
    return 0 if session["status"] == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
