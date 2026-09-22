#!/usr/bin/env python3
"""Diagnóstico SOMENTE LEITURA — timeout F4 na fase front.

Não altera thresholds, modelos nem produto.
Instrumenta webcam + gates do mesmo pipeline (poc_common / enrollment_pipeline).

  python scripts/f4_diagnose_front_timeout.py --webcam 2 --seconds 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
ROOT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from enrollment_pipeline import (  # noqa: E402
    CaptureSession,
    _count_strong_faces,
    process_frame_bgr,
)
from poc_common import (  # noqa: E402
    ALIGNMENT_MODE_PRODUCT,
    CAM_WEB,
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    estimate_face_yaw,
    open_webcam,
    pose_for_phase,
    quality_of_crop,
    select_primary_face,
)

OUT = ROOT / "results" / "enrollment_escalavel" / "f4" / "DIAGNOSE_FRONT.json"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def probe_camera(index: int) -> dict[str, Any]:
    info: dict[str, Any] = {"index": index, "open_ok": False}
    t0 = time.time()
    try:
        cap = open_webcam(index)
        info["open_ok"] = True
        info["open_elapsed_s"] = round(time.time() - t0, 3)
        info["cam_web_config"] = {
            "default_index": CAM_WEB.get("index"),
            "width_req": CAM_WEB.get("width"),
            "height_req": CAM_WEB.get("height"),
        }
        # Actual props
        import cv2

        info["prop_width"] = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        info["prop_height"] = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        info["prop_fps"] = cap.get(cv2.CAP_PROP_FPS)

        reads = []
        black = 0
        for i in range(30):
            t1 = time.time()
            ok, frame = cap.read()
            dt = time.time() - t1
            if not ok or frame is None:
                reads.append({"i": i, "ok": False, "read_s": round(dt, 4)})
                continue
            mean = float(frame.mean())
            if mean < 8.0:
                black += 1
            reads.append(
                {
                    "i": i,
                    "ok": True,
                    "read_s": round(dt, 4),
                    "shape": list(frame.shape),
                    "mean": round(mean, 2),
                }
            )
        cap.release()
        ok_reads = [r for r in reads if r.get("ok")]
        info["reads_ok"] = len(ok_reads)
        info["reads_fail"] = len(reads) - len(ok_reads)
        info["black_frames"] = black
        info["sample_shapes"] = list({tuple(r["shape"]) for r in ok_reads})
        if ok_reads:
            info["mean_read_s"] = round(float(np.mean([r["read_s"] for r in ok_reads])), 4)
            info["mean_pixel"] = round(float(np.mean([r["mean"] for r in ok_reads])), 2)
        info["reads_head"] = reads[:5]
        info["reads_tail"] = reads[-3:]
    except Exception as e:
        info["open_ok"] = False
        info["error"] = str(e)
        info["open_elapsed_s"] = round(time.time() - t0, 3)
        info["traceback"] = traceback.format_exc()[-800:]
    return info


def diagnose_frame(frame: np.ndarray, *, min_quality: float = 0.55) -> dict[str, Any]:
    """Espelha gates do enrollment_pipeline.process_frame_bgr (front) com motivos explícitos."""
    h, w = frame.shape[:2]
    out: dict[str, Any] = {
        "frame_received": True,
        "resolution": [h, w],
        "reject_stage": None,
        "reject_reason": None,
    }
    t0 = time.time()
    try:
        faces = detect_faces_yunet(frame, score_th=0.72)
    except Exception as e:
        out["reject_stage"] = "yunet"
        out["reject_reason"] = str(e)
        out["detect_s"] = round(time.time() - t0, 4)
        return out
    out["detect_s"] = round(time.time() - t0, 4)
    out["n_faces_raw"] = len(faces)
    out["n_faces_strong"] = _count_strong_faces(faces)

    if out["n_faces_strong"] > 1:
        out["reject_stage"] = "multi_face"
        out["reject_reason"] = f"strong_faces={out['n_faces_strong']}"
        return out

    face = select_primary_face(
        faces, min_face_score=0.55, frame_shape=(h, w), prev=None
    )
    if face is None:
        out["reject_stage"] = "no_face"
        out["reject_reason"] = "select_primary_face returned None"
        out["face_scores"] = [
            round(float(f.get("face_score") or f.get("det_score") or 0), 3) for f in faces
        ]
        return out

    out["bbox"] = {
        "x": round(float(face["x"]), 1),
        "y": round(float(face["y"]), 1),
        "w": round(float(face["w"]), 1),
        "h": round(float(face["h"]), 1),
    }
    out["face_score"] = round(float(face.get("face_score") or 0), 4)
    lms = face.get("landmarks") or []
    out["landmarks_count"] = len(lms)
    out["landmarks_valid"] = len(lms) >= 5

    try:
        crop, align_meta = aligned_crop(frame, face)
        out["alignment_ok"] = align_meta.get("alignment_mode") == ALIGNMENT_MODE_PRODUCT
        out["alignment_mode"] = align_meta.get("alignment_mode")
    except AlignmentError as e:
        out["alignment_ok"] = False
        out["reject_stage"] = "alignment"
        out["reject_reason"] = str(e)
        return out

    if not out["alignment_ok"]:
        out["reject_stage"] = "alignment"
        out["reject_reason"] = f"mode={out.get('alignment_mode')}"
        return out

    lab, q = quality_of_crop(crop)
    out["quality"] = round(float(q), 4)
    out["quality_label"] = lab
    quality_ok = q >= min_quality and lab != "poor"
    if not quality_ok:
        out["reject_stage"] = "quality"
        out["reject_reason"] = f"q={q:.3f} lab={lab} min={min_quality}"
        return out

    yaw = estimate_face_yaw(lms)
    out["yaw"] = None if yaw is None else round(float(yaw), 4)
    pose = pose_for_phase("front", yaw)
    out["pose_ok"] = bool(pose["ok"])
    out["pose_hint"] = pose.get("hint")
    out["pose_bucket"] = pose.get("bucket")
    if not pose["ok"]:
        out["reject_stage"] = "pose_front"
        out["reject_reason"] = pose.get("hint") or "pose not ok"
        return out

    out["reject_stage"] = None
    out["reject_reason"] = None
    out["would_increment_hold"] = True
    return out


def run_loop(webcam: int, seconds: float) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ts": _ts(),
        "webcam": webcam,
        "seconds": seconds,
        "camera_probe": probe_camera(webcam),
        "path_compare": {
            "f4_harness": "open_webcam → process_frame_bgr (CaptureSession) — SEM browser /frame",
            "aligned_v2_pass": "ui_server._loop → cap.read → same poc_common gates; stable_needed=18",
            "f3_mobile": "browser getUserMedia → POST /api/aluno/session/frame → decode_jpeg → process_frame_bgr",
            "f4_does_NOT_use_browser_frame_endpoint": True,
            "stable_needed_f3_pipeline": 12,
            "stable_needed_ui_server_lab": 18,
            "min_quality_both": 0.55,
            "yunet_score_th_both": 0.72,
        },
        "frames": [],
        "reject_histogram": {},
        "process_frame_bgr_spotcheck": [],
        "harness_timeout_analysis": {},
    }

    if not report["camera_probe"].get("open_ok"):
        report["probable_cause"] = "camera_open_failed"
        return report

    # Timed processing loop (mirrors f4 enroll loop structure)
    try:
        cap = open_webcam(webcam)
    except Exception as e:
        report["probable_cause"] = "camera_reopen_failed"
        report["reopen_error"] = str(e)
        return report

    cs = CaptureSession(
        session_id="diag",
        campaign_id="diag",
        roster_student_id="diag",
        display_name="Diag",
        class_label="diag",
    )
    cs.set_phase("front")

    t_end = time.time() + seconds
    n_read_ok = 0
    n_read_fail = 0
    n_process = 0
    reject_counter: Counter[str] = Counter()
    hold_max = 0
    first_process_s: Optional[float] = None
    frames_log: list[dict[str, Any]] = []

    # Simulate F4 budget: open already spent time; note remaining like timeout
    t_loop0 = time.time()
    while time.time() < t_end:
        ok, frame = cap.read()
        if not ok or frame is None:
            n_read_fail += 1
            if len(frames_log) < 40:
                frames_log.append(
                    {
                        "t": round(time.time() - t_loop0, 3),
                        "frame_received": False,
                        "reject_stage": "cap_read",
                        "reject_reason": "ok=False or frame=None",
                    }
                )
            time.sleep(0.05)
            continue
        n_read_ok += 1

        t_p0 = time.time()
        detail = diagnose_frame(frame)
        detail["diagnose_s"] = round(time.time() - t_p0, 4)
        detail["t"] = round(time.time() - t_loop0, 3)

        # Also call real process_frame_bgr (same as F4) and record ui
        t_p1 = time.time()
        try:
            ui = process_frame_bgr(cs, frame)
            pf_s = round(time.time() - t_p1, 4)
            if first_process_s is None:
                first_process_s = pf_s
            n_process += 1
            detail["process_frame_ui_code"] = ui.get("ui_code")
            detail["process_frame_status"] = ui.get("status_human")
            detail["enrollment_phase"] = ui.get("phase")
            detail["hold_stable"] = cs.stable
            detail["hold_needed"] = cs.stable_needed
            detail["hold_pct"] = ui.get("stable_pct")
            hold_max = max(hold_max, cs.stable)
            detail["process_frame_s"] = pf_s
        except Exception as e:
            detail["process_frame_error"] = str(e)
            detail["process_frame_traceback"] = traceback.format_exc()[-500:]

        stage = detail.get("reject_stage") or (
            "hold_progress" if detail.get("would_increment_hold") else "ok_gates"
        )
        if detail.get("process_frame_ui_code") == "holding":
            stage = "holding"
        if detail.get("process_frame_ui_code") == "captured":
            stage = "captured"
        reject_counter[stage] += 1

        if len(frames_log) < 80:
            frames_log.append(detail)
        time.sleep(0.03)

    cap.release()

    report["frames"] = frames_log
    report["reject_histogram"] = dict(reject_counter)
    report["loop_stats"] = {
        "n_read_ok": n_read_ok,
        "n_read_fail": n_read_fail,
        "n_process_frame_calls": n_process,
        "first_process_frame_s": first_process_s,
        "hold_max_reached": hold_max,
        "stable_needed": cs.stable_needed,
        "final_phase": cs.phase,
        "samples": [s["step"] for s in cs.samples],
        "loop_elapsed_s": round(time.time() - t_loop0, 3),
    }

    # Harness timeout analysis (from F4_E2E_SUMMARY pattern)
    report["harness_timeout_analysis"] = {
        "f4_summary_observation": {
            "phases_seen_empty": True,
            "retries_ui_empty": True,
            "last_phase": "front",
            "samples_partial_empty": True,
            "interpretation": (
                "phases_seen só incrementa APÓS process_frame_bgr retornar. "
                "Lista vazia + samples vazios implica: (A) cap.read falhou sempre no loop, "
                "ou (B) process_frame_bgr nunca retornou a tempo / loop não rodou, "
                "ou (C) open_webcam+settle consumiram quase todo o timeout de 25s."
            ),
        },
        "f4_timeout_includes": [
            "claim + mark_in_progress",
            "open_webcam (8 reads de warm-up)",
            "settle_s sleep",
            "THEN while loop until timeout from t0 at function start",
        ],
        "bug_or_design_note": (
            "enroll_person_usb marca t0 ANTES de open_webcam; com --timeout 25, "
            "open_webcam lento (DSHOW) pode deixar poucos segundos (ou 0) para o loop."
        ),
    }

    # Probable cause
    if n_read_ok == 0:
        report["probable_cause"] = "cap_read_fail_in_loop"
        report["probable_detail"] = "Nenhum frame lido com sucesso no loop diagnóstico"
    elif n_process == 0:
        report["probable_cause"] = "process_frame_never_called_or_crashed"
    elif hold_max == 0 and reject_counter.get("no_face", 0) == n_read_ok:
        report["probable_cause"] = "no_face_every_frame"
        report["probable_detail"] = "YuNet/select_primary não viu rosto — câmera sem pessoa ou índice errado (preview de outro device)"
    elif hold_max == 0 and "quality" in reject_counter:
        report["probable_cause"] = "quality_gate_reject"
    elif hold_max == 0 and "pose_front" in reject_counter:
        report["probable_cause"] = "pose_front_reject"
    elif hold_max == 0 and "alignment" in reject_counter:
        report["probable_cause"] = "alignment_reject"
    elif 0 < hold_max < cs.stable_needed:
        report["probable_cause"] = "hold_never_reached_stable_needed"
        report["probable_detail"] = f"hold_max={hold_max} < stable_needed={cs.stable_needed}"
    elif cs.samples:
        report["probable_cause"] = "pipeline_can_capture_front_ok"
        report["probable_detail"] = "Diagnóstico conseguiu capturar — F4 timeout provavelmente harness/budget/tempo ou ausência de pessoa na tentativa anterior"
    else:
        top = reject_counter.most_common(3)
        report["probable_cause"] = "gates_rejecting"
        report["probable_detail"] = f"top_rejects={top}"

    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webcam", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--also-scan", action="store_true", help="probe indices 0,1,2")
    args = ap.parse_args()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    full: dict[str, Any] = {"ts": _ts(), "primary_webcam": args.webcam}

    if args.also_scan:
        full["camera_scan"] = [probe_camera(i) for i in (0, 1, 2)]

    full["diagnosis"] = run_loop(args.webcam, args.seconds)
    OUT.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(
        {
            "wrote": str(OUT),
            "probable_cause": full["diagnosis"].get("probable_cause"),
            "probable_detail": full["diagnosis"].get("probable_detail"),
            "reject_histogram": full["diagnosis"].get("reject_histogram"),
            "loop_stats": full["diagnosis"].get("loop_stats"),
            "camera_open": full["diagnosis"].get("camera_probe", {}).get("open_ok"),
            "open_elapsed_s": full["diagnosis"].get("camera_probe", {}).get("open_elapsed_s"),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
