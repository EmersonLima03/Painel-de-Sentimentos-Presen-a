#!/usr/bin/env python3
"""F4 — E2E físico lab (USB) do Enrollment Escalável A.

Usa o MESMO CaptureSession / poc_common da F3 (sem alterar pipeline).
Alimenta frames da webcam → process_frame_bgr (equivalente ao JPEG do celular).

  python scripts/f4_e2e_lab_physical.py --webcam 2

Não grava produção. Não chama reload_matcher.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
ROOT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from enrollment_pipeline import (  # noqa: E402
    CAMPAIGN_GALLERY,
    CAPTURE_STORE,
    ack_glasses,
    process_frame_bgr,
)
from enrollment_store import (  # noqa: E402
    DEFAULT_DB_PATH,
    EnrollmentStore,
    ROSTER_COMPLETED,
)
from poc_common import (  # noqa: E402
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    embed_crop,
    ensure_dirs,
    match_gallery,
    open_webcam,
    quality_of_crop,
)

OUT_DIR = ROOT / "results" / "enrollment_escalavel" / "f4"
SCHOOL_ID = "escola_demo_presenca"
CLASS_ID = "turma_familia_lab"
THRESHOLD = 0.70
MARGIN = 0.10


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_campaign_gallery_by_name(campaign_id: str) -> list[tuple[str, np.ndarray]]:
    root = CAMPAIGN_GALLERY / campaign_id
    items: list[tuple[str, np.ndarray]] = []
    if not root.is_dir():
        return items
    for person in sorted(root.iterdir()):
        if not person.is_dir():
            continue
        meta_path = person / "enroll_meta.json"
        name = person.name
        if meta_path.is_file():
            try:
                name = json.loads(meta_path.read_text(encoding="utf-8")).get(
                    "display_name", name
                )
            except Exception:
                pass
        for f in sorted(person.glob("*.npy")):
            if f.name.startswith("_"):
                continue
            v = np.load(f).astype(np.float32).reshape(-1)
            n = float(np.linalg.norm(v) + 1e-12)
            items.append((name, v / n))
    return items


def enroll_person_usb(
    store: EnrollmentStore,
    camp: dict[str, Any],
    display_name: str,
    *,
    webcam: int,
    glasses: Optional[bool],
    timeout_s: float,
    settle_s: float,
) -> dict[str, Any]:
    """Claim + start + feed webcam frames until completed or timeout.

    Timeout budget starts ONLY after open_webcam succeeds and settle completes.
    """
    code = next(
        r["claim_code"]
        for r in camp["claim_sheet"]
        if r["display_name"] == display_name
    )
    report: dict[str, Any] = {
        "display_name": display_name,
        "claim_code_used": True,
        "started_at": _ts(),
        "webcam": webcam,
        "phases_seen": [],
        "retries_ui": [],
        "samples": [],
        "status": "IN_PROGRESS",
        "camera_open_elapsed_s": None,
        "enrollment_elapsed_s": None,
    }
    claimed = store.claim(
        campaign_token=camp["campaign_token"],
        claim_code=code,
        client_ip="127.0.0.1",
    )
    if not hasattr(claimed, "session_token"):
        report["status"] = "FAIL"
        report["error"] = getattr(claimed, "error", "claim_failed")
        return report
    token = claimed.session_token
    info = store.mark_in_progress(token)
    camp_info = store.get_campaign(info["campaign_id"])
    cs = CAPTURE_STORE.create(
        session_id=info["session_id"],
        campaign_id=info["campaign_id"],
        roster_student_id=info["roster_student_id"],
        display_name=info["display_name"],
        class_label=(camp_info or {}).get("class_label", ""),
    )

    t_cam0 = time.time()
    try:
        cap = open_webcam(webcam)
    except Exception as e:
        report["status"] = "NAO_TESTADO"
        report["error"] = f"webcam: {e}"
        report["camera_open_elapsed_s"] = round(time.time() - t_cam0, 3)
        return report

    # Confirm at least one valid frame after open_webcam warm-up
    frame_ok = False
    for _ in range(5):
        ok, frame = cap.read()
        if ok and frame is not None and float(frame.mean()) >= 8.0:
            frame_ok = True
            break
        time.sleep(0.05)
    if not frame_ok:
        try:
            cap.release()
        except Exception:
            pass
        report["status"] = "FAIL"
        report["error"] = "camera_open_ok_but_no_valid_frame"
        report["camera_open_elapsed_s"] = round(time.time() - t_cam0, 3)
        return report

    time.sleep(settle_s)
    report["camera_open_elapsed_s"] = round(time.time() - t_cam0, 3)

    # --- enrollment timer starts ONLY after camera is ready ---
    t_enroll0 = time.time()
    print(f"\n=== Enrollment físico: {display_name} ===")
    print(
        f"  camera_open_elapsed_s={report['camera_open_elapsed_s']} | "
        f"enrollment timeout={timeout_s}s (após câmera pronta)"
    )
    print("Siga as instruções: frente / direita / esquerda / validação.")

    last_phase = None
    glasses_done = False
    try:
        while time.time() - t_enroll0 < timeout_s:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            ui = process_frame_bgr(cs, frame)
            phase = ui.get("phase")
            if phase != last_phase:
                print(f"  → fase: {phase} | {ui.get('status_human')}")
                report["phases_seen"].append(
                    {
                        "phase": phase,
                        "t": round(time.time() - t_enroll0, 2),
                        "status": ui.get("status_human"),
                    }
                )
                last_phase = phase
            code_ui = ui.get("ui_code")
            if code_ui in ("adjust", "pose", "alignment", "no_face", "multi_face"):
                if not report["retries_ui"] or report["retries_ui"][-1] != code_ui:
                    report["retries_ui"].append(code_ui)

            if phase == "glasses_ask" and not glasses_done:
                use = glasses
                if use is None:
                    use = False
                    print("  → óculos: NÃO (default; use --glasses-mae/--glasses-dulin para SIM)")
                else:
                    print(f"  → óculos: {'SIM' if use else 'NÃO'}")
                ui = ack_glasses(cs, bool(use))
                report["glasses_wanted"] = bool(use)
                glasses_done = True
                phase = ui.get("phase")
                last_phase = phase
                report["phases_seen"].append(
                    {
                        "phase": phase,
                        "t": round(time.time() - t_enroll0, 2),
                        "status": ui.get("status_human"),
                    }
                )

            if ui.get("completed"):
                store.complete_enrollment(token)
                report["status"] = "PASS"
                report["enrollment_elapsed_s"] = round(time.time() - t_enroll0, 2)
                report["samples"] = list(cs.samples)
                report["sample_steps"] = [s["step"] for s in cs.samples]
                report["gallery_dir"] = str(cs.gallery_dir())
                report["product_db_written"] = False
                print(
                    f"  ✓ concluído enrollment_elapsed_s={report['enrollment_elapsed_s']} "
                    f"— steps={report['sample_steps']}"
                )
                return report
            time.sleep(0.03)
    finally:
        try:
            cap.release()
        except Exception:
            pass

    report["status"] = "FAIL"
    report["enrollment_elapsed_s"] = round(time.time() - t_enroll0, 2)
    report["error"] = "timeout_sem_completed"
    report["last_phase"] = cs.phase
    report["samples_partial"] = [s["step"] for s in cs.samples]
    return report


def probe_recognize(
    gallery: list[tuple[str, np.ndarray]],
    *,
    webcam: int,
    label: str,
    settle_s: float,
) -> dict[str, Any]:
    out: dict[str, Any] = {"label": label, "status": "NAO_TESTADO"}
    try:
        cap = open_webcam(webcam)
    except Exception as e:
        out["error"] = str(e)
        return out
    import cv2

    time.sleep(settle_s)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        out["error"] = "sem_frame"
        return out
    faces = detect_faces_yunet(frame, score_th=0.72)
    if not faces:
        out["status"] = "FAIL"
        out["error"] = "no_face"
        return out
    # primary face
    face = max(faces, key=lambda f: float(f.get("face_score") or f.get("det_score") or 0))
    try:
        crop, meta = aligned_crop(frame, face)
    except AlignmentError as e:
        out["status"] = "FAIL"
        out["alignment_error"] = str(e)
        return out
    qlab, q = quality_of_crop(crop)
    emb = embed_crop(crop)
    match = match_gallery(emb, gallery, THRESHOLD, MARGIN)
    out.update(
        {
            "status": "PASS" if match["decision"] == label else "FAIL",
            "expected": label,
            "decision": match["decision"],
            "top1_id": match["top1_id"],
            "top1_score": match["top1_score"],
            "margin": match["margin"],
            "quality": round(q, 4),
            "quality_label": qlab,
            "alignment_mode": meta.get("alignment_mode"),
            "n_faces": len(faces),
        }
    )
    return out


def probe_unknown(gallery: list[tuple[str, np.ndarray]], *, webcam: int, settle_s: float) -> dict[str, Any]:
    """Pessoa na câmera NÃO deve bater nas identidades da campanha (ou score abaixo)."""
    out = probe_recognize(gallery, webcam=webcam, label="__force_unknown__", settle_s=settle_s)
    # reinterpret: UNKNOWN decision is PASS for this probe
    if out.get("decision") == "UNKNOWN":
        out["status"] = "PASS"
        out["expected"] = "UNKNOWN"
    elif out.get("status") != "NAO_TESTADO":
        out["status"] = "FAIL"
        out["expected"] = "UNKNOWN"
        out["note"] = "Rosto na câmera foi identificado — use pessoa fora da galeria ou tape o rosto"
    out["label"] = "UNKNOWN_probe"
    return out


def probe_multiperson(gallery: list[tuple[str, np.ndarray]], *, webcam: int, settle_s: float) -> dict[str, Any]:
    out: dict[str, Any] = {"label": "multiperson", "status": "NAO_TESTADO", "faces": []}
    try:
        cap = open_webcam(webcam)
    except Exception as e:
        out["error"] = str(e)
        return out
    time.sleep(settle_s)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        out["error"] = "sem_frame"
        return out
    faces = detect_faces_yunet(frame, score_th=0.6)
    out["n_detected"] = len(faces)
    ids = []
    for i, face in enumerate(faces):
        try:
            crop, meta = aligned_crop(frame, face)
        except AlignmentError as e:
            out["faces"].append({"idx": i, "error": str(e)})
            continue
        emb = embed_crop(crop)
        m = match_gallery(emb, gallery, THRESHOLD, MARGIN)
        entry = {
            "idx": i,
            "decision": m["decision"],
            "top1_score": m["top1_score"],
            "alignment_mode": meta.get("alignment_mode"),
        }
        out["faces"].append(entry)
        if m["decision"] != "UNKNOWN":
            ids.append(m["decision"])
    unique = sorted(set(ids))
    out["identities_found"] = unique
    if len(faces) >= 2 and len(unique) >= 2:
        out["status"] = "PASS"
    elif len(faces) < 2:
        out["status"] = "NAO_TESTADO"
        out["note"] = "Menos de 2 rostos no frame — posicione Dulin+Mae juntos"
    else:
        out["status"] = "FAIL"
        out["note"] = "2+ rostos mas identidades distintas insuficientes"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="F4 E2E lab physical")
    ap.add_argument("--webcam", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=180.0, help="segundos por pessoa")
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--glasses-dulin", action="store_true")
    ap.add_argument("--glasses-mae", action="store_true")
    ap.add_argument("--auto", action="store_true", help="sem input(); countdown e tenta enrollment")
    ap.add_argument("--skip-enroll", action="store_true", help="só reconhecimento (requer campanha prévia)")
    ap.add_argument("--campaign-id", type=str, default="")
    ap.add_argument("--skip-recognize", action="store_true")
    args = ap.parse_args()

    ensure_dirs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = OUT_DIR / "poc_enrollment_f4.db"
    store = EnrollmentStore(db, hmac_secret="f4-physical-hmac")

    summary: dict[str, Any] = {
        "phase": "F4",
        "ts": _ts(),
        "webcam": args.webcam,
        "mode": "auto" if args.auto else "interactive",
        "threshold": THRESHOLD,
        "margin": MARGIN,
        "product_db_written": False,
        "reload_matcher": False,
        "enrollments": {},
        "recognition": {},
        "verdict_poc": "NÃO CONCLUÍDO",
    }

    def pause(msg: str) -> None:
        if args.auto:
            print(msg)
            print("  (auto) aguardando 5s…")
            time.sleep(5.0)
        else:
            input(msg)

    if args.skip_enroll and args.campaign_id:
        campaign_id = args.campaign_id
        camp = store.get_campaign(campaign_id) or {"campaign_id": campaign_id}
    else:
        camp = store.create_campaign(school_id=SCHOOL_ID, class_group_id=CLASS_ID)
        campaign_id = camp["campaign_id"]
        summary["campaign_id"] = campaign_id
        summary["campaign_token_len"] = len(camp["campaign_token"])
        print(f"Campanha {campaign_id}")
        print("Claim sheet (gestor):")
        for row in camp["claim_sheet"]:
            print(f"  {row['display_name']}: {row['claim_code']}")

        for name, glasses_flag in (
            ("Dulin", args.glasses_dulin),
            ("Mae", args.glasses_mae),
        ):
            pause(f"\nPressione ENTER quando {name} estiver na câmera (webcam {args.webcam})… ")
            rep = enroll_person_usb(
                store,
                camp,
                name,
                webcam=args.webcam,
                glasses=True if glasses_flag else False,
                timeout_s=args.timeout,
                settle_s=args.settle,
            )
            summary["enrollments"][name] = rep
            (OUT_DIR / "F4_E2E_PARTIAL.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    gallery = load_campaign_gallery_by_name(campaign_id)
    summary["gallery_templates"] = len(gallery)
    summary["gallery_identities"] = sorted({sid for sid, _ in gallery})

    if not args.skip_recognize and gallery:
        for name in ("Dulin", "Mae"):
            if summary.get("enrollments", {}).get(name, {}).get("status") != "PASS":
                if not args.skip_enroll:
                    summary["recognition"][name] = {
                        "status": "SKIPPED",
                        "reason": "enrollment_nao_pass",
                    }
                    continue
            pause(f"\nPressione ENTER para reconhecer {name} sozinho(a) na câmera… ")
            summary["recognition"][name] = probe_recognize(
                gallery, webcam=args.webcam, label=name, settle_s=args.settle
            )
            print(" ", summary["recognition"][name])

        pause("\nPressione ENTER para UNKNOWN (pessoa NÃO cadastrada ou tape o rosto cadastrado)… ")
        summary["recognition"]["UNKNOWN"] = probe_unknown(
            gallery, webcam=args.webcam, settle_s=args.settle
        )
        print(" ", summary["recognition"]["UNKNOWN"])

        pause("\nPressione ENTER com Dulin+Mae no mesmo frame (multi-pessoa)… ")
        summary["recognition"]["multiperson"] = probe_multiperson(
            gallery, webcam=args.webcam, settle_s=args.settle
        )
        print(" ", summary["recognition"]["multiperson"])
    elif not gallery:
        summary["recognition"]["note"] = "galeria vazia — enrollment nao produziu templates"

    # Progress from store
    if not args.skip_enroll:
        prog = store.get_roster_progress(campaign_id)
        summary["gestor_progress"] = {
            "completed": prog["completed"],
            "total": prog["total"],
            "items": [
                {"display_name": i["display_name"], "status": i["status"]}
                for i in prog["items"]
            ],
        }

    # Verdict
    en_ok = all(
        summary.get("enrollments", {}).get(n, {}).get("status") == "PASS"
        for n in ("Dulin", "Mae")
    )
    rec = summary.get("recognition", {})
    rec_ok = (
        rec.get("Dulin", {}).get("status") == "PASS"
        and rec.get("Mae", {}).get("status") == "PASS"
        and rec.get("UNKNOWN", {}).get("status") == "PASS"
    )
    multi = rec.get("multiperson", {}).get("status")
    if en_ok and rec_ok and multi == "PASS":
        summary["verdict_poc"] = "PASS"
    elif en_ok and rec_ok:
        summary["verdict_poc"] = "PASS COM RESSALVAS"
        summary["verdict_note"] = f"multi-pessoa={multi}"
    elif en_ok:
        summary["verdict_poc"] = "PASS COM RESSALVAS"
        summary["verdict_note"] = "enrollment OK; reconhecimento incompleto/falhou"
    else:
        summary["verdict_poc"] = "NÃO CONCLUÍDO"

    summary["vip_5440"] = "VALIDAÇÃO PENDENTE"
    summary["producao"] = "FORA DO ESCOPO"

    out_path = OUT_DIR / "F4_E2E_SUMMARY.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + json.dumps({"wrote": str(out_path), "verdict_poc": summary["verdict_poc"]}, ensure_ascii=False))
    return 0 if summary["verdict_poc"] in ("PASS", "PASS COM RESSALVAS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
