#!/usr/bin/env python3
"""
Harness principal do benchmark oclusão.

Modos:
  --mode offline   : probes = crops enroll (sem óculos) leave-one-out / cross-ID / multiperson sim
  --mode import_live: importa SUMMARYs FaceNet já medidos (óculos/dist) como evidência FaceNet
  --mode probes_dir : avalia pasta de probes JPG capturados (mesmos crops → todos os modelos)

Nunca inventa resultado físico.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
_POC = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from benchmark_occlusion_common import (  # noqa: E402
    BENCH_OUT,
    BENCH_ROOT,
    CROPS_SRC,
    LICENSE_NOTES,
    decide,
    embed_crop_model,
    ensure_bench_dirs,
    load_gallery,
    metrics_from_rows,
    save_json,
    utc_now,
)


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    for enc in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            continue
    return None


def run_offline(models: list[str]) -> dict:
    """Usa crops_aligned_v2 como probes sem óculos (mesmos pixels → todos os modelos)."""
    rows: list[dict] = []
    report: dict[str, Any] = {
        "mode": "offline_enroll_crops",
        "ts": utc_now(),
        "condition": "no_glasses",
        "note": "Probes = crops de enrollment alinhados; não cobre óculos físicos.",
        "by_model": {},
        "rows": [],
    }
    for model in models:
        gallery_full = load_gallery(model)
        if not gallery_full:
            report["by_model"][model] = {"status": "NÃO TESTADO", "reason": "empty_gallery"}
            continue
        model_rows: list[dict] = []
        # Cada crop como probe contra galeria leave-one-out (remove exatamente aquele template)
        for person_dir in sorted(CROPS_SRC.iterdir()):
            if not person_dir.is_dir():
                continue
            sid = person_dir.name
            for jpg in sorted(person_dir.glob("*.jpg")):
                img = cv2.imread(str(jpg))
                if img is None:
                    continue
                emb = embed_crop_model(img, model)
                # LOO: gallery without this exact pose file
                gal = []
                gdir = BENCH_ROOT / model / sid
                for npy in sorted((BENCH_ROOT / model).rglob("*.npy")):
                    if npy.parent.name == sid and npy.stem == jpg.stem:
                        continue
                    v = np.load(npy).astype(np.float32).reshape(-1)
                    v = v / (np.linalg.norm(v) + 1e-12)
                    gal.append((npy.parent.name, v))
                row = decide(
                    emb,
                    gal,
                    expected=sid,
                    model=model,
                    condition="no_glasses_loo",
                    distance_m=None,
                    meta={
                        "probe": str(jpg),
                        "pose": jpg.stem,
                        "bbox_w": None,
                        "bbox_h": None,
                        "quality": None,
                    },
                )
                model_rows.append(row)
                rows.append(row)
        # Cross-ID: lab01 crop vs gallery without lab01 → should be UNKNOWN or wrong
        for person_dir in sorted(CROPS_SRC.iterdir()):
            if not person_dir.is_dir():
                continue
            sid = person_dir.name
            jpg = person_dir / "front.jpg"
            if not jpg.exists():
                continue
            img = cv2.imread(str(jpg))
            if img is None:
                continue
            emb = embed_crop_model(img, model)
            gal_other = [(s, v) for s, v in gallery_full if s != sid]
            row = decide(
                emb,
                gal_other,
                expected="UNKNOWN",
                model=model,
                condition="cross_id_as_unknown",
                distance_m=None,
                meta={"probe": str(jpg), "excluded_self": sid},
            )
            model_rows.append(row)
            rows.append(row)
        report["by_model"][model] = metrics_from_rows(model_rows)
    report["rows"] = rows
    return report


def run_multiperson_sim(models: list[str]) -> dict:
    """Simula multi-pessoa: dois crops (lab01+lab02 front) matchados na galeria completa."""
    report: dict[str, Any] = {"mode": "multiperson_sim_enroll_fronts", "ts": utc_now(), "by_model": {}, "rows": []}
    fronts = {}
    for sid in ("lab01", "lab02"):
        p = CROPS_SRC / sid / "front.jpg"
        if p.exists():
            fronts[sid] = cv2.imread(str(p))
    if len(fronts) < 2:
        report["status"] = "NÃO TESTADO"
        report["reason"] = "need lab01+lab02 front crops"
        return report
    for model in models:
        gallery = load_gallery(model)
        mrows = []
        ids = set()
        for sid, img in fronts.items():
            if img is None:
                continue
            emb = embed_crop_model(img, model)
            row = decide(
                emb,
                gallery,
                expected=sid,
                model=model,
                condition="multiperson_sim",
                distance_m=2.0,
                meta={"probe_sid": sid},
            )
            mrows.append(row)
            if row["decision"] not in (None, "UNKNOWN"):
                ids.add(row["decision"])
            report["rows"].append(row)
        met = metrics_from_rows(mrows)
        met["identified_ids"] = sorted(ids)
        met["both_correct"] = ids == {"lab01", "lab02"} and all(r.get("correct") for r in mrows)
        report["by_model"][model] = met
    return report


def run_template_variants(models: list[str]) -> dict:
    """Compara galeria no_glasses vs with_glasses usando probes glasses se existirem."""
    report: dict[str, Any] = {
        "mode": "multi_template_glasses",
        "ts": utc_now(),
        "by_model": {},
        "rows": [],
        "status": None,
    }
    probe_dir = BENCH_OUT / "probes" / "glasses_degree"
    probes = list(probe_dir.glob("*_glasses.jpg")) if probe_dir.is_dir() else []
    if not probes:
        report["status"] = "NÃO TESTADO"
        report["reason"] = "Sem probes glasses_degree capturados (rode benchmark_occlusion_capture_probes.py)"
        return report
    for model in models:
        gal_a = load_gallery(model, "no_glasses")
        gal_b = load_gallery(model, "with_glasses")
        if not gal_a:
            report["by_model"][model] = {"status": "NÃO TESTADO", "reason": "no_glasses gallery empty"}
            continue
        mrows_a, mrows_b = [], []
        for jpg in probes:
            sid = jpg.stem.replace("_glasses", "")
            img = cv2.imread(str(jpg))
            if img is None:
                continue
            emb = embed_crop_model(img, model)
            ra = decide(emb, gal_a, expected=sid, model=model, condition="glasses_vs_no_glasses_gallery", distance_m=2.0, meta={"probe": str(jpg), "gallery_variant": "no_glasses"})
            rb = decide(emb, gal_b, expected=sid, model=model, condition="glasses_vs_with_glasses_gallery", distance_m=2.0, meta={"probe": str(jpg), "gallery_variant": "with_glasses"})
            mrows_a.append(ra)
            mrows_b.append(rb)
            report["rows"].extend([ra, rb])
        report["by_model"][model] = {
            "no_glasses_gallery": metrics_from_rows(mrows_a),
            "with_glasses_gallery": metrics_from_rows(mrows_b),
        }
    report["status"] = "OK"
    return report


def import_facenet_live_evidence() -> dict:
    """Importa evidências físicas FaceNet já coletadas (óculos/dist/unknown/multi)."""
    R = _POC / "results"
    sources = {
        "recognize_no_glasses": R / "aligned_v2" / "03_recognize.json",
        "glasses_dark": R / "aligned_v2" / "glasses" / "SUMMARY_glasses.json",
        "glasses_degree": R / "aligned_v2" / "glasses_type2_retry" / "SUMMARY_glasses_type2_retry.json",
        "glasses_degree_first": R / "aligned_v2" / "glasses_type2" / "SUMMARY_glasses_type2.json",
        "distance_1m": R / "aligned_v2" / "05_distance_1m.json",
        "distance_2m": R / "aligned_v2" / "06_distance_2m.json",
        "distance_3m": R / "aligned_v2" / "distance_3m" / "SUMMARY_3m.json",
        "distance_4m": R / "aligned_v2" / "distance_4m" / "SUMMARY_4m.json",
        "unknown": R / "aligned_v2" / "unknown_probe" / "SUMMARY_unknown.json",
        "multiperson": R / "aligned_v2" / "multiperson" / "SUMMARY_multiperson.json",
    }
    out: dict[str, Any] = {
        "mode": "import_facenet_live",
        "model": "facenet",
        "ts": utc_now(),
        "conditions": {},
        "note": "Evidência empírica FaceNet já medida no POC aligned_v2; não é ArcFace.",
    }
    for key, path in sources.items():
        d = _load_json(path)
        if not d:
            out["conditions"][key] = {"status": "NÃO TESTADO", "path": str(path)}
            continue
        samples = d.get("samples") or []
        # normalize to metrics
        norm_rows = []
        expected = d.get("expected") or "lab01"
        if key == "unknown":
            expected = "UNKNOWN"
        if key == "multiperson":
            out["conditions"][key] = {
                "status": d.get("result"),
                "achieved_streak": d.get("achieved_streak"),
                "raw_path": str(path),
                "note": "lab01+lab02 same frame; FaceNet match_all",
            }
            continue
        for s in samples:
            decision = s.get("decision")
            score = s.get("score") if s.get("score") is not None else s.get("top1_score")
            if expected == "UNKNOWN":
                correct = decision == "UNKNOWN"
                tp = correct
                fp = decision not in (None, "UNKNOWN")
                fn = False
            else:
                correct = decision == expected
                tp = correct
                fp = decision not in (None, "UNKNOWN", expected)
                fn = decision == "UNKNOWN"
            norm_rows.append(
                {
                    "decision": decision,
                    "score": score,
                    "margin": s.get("margin"),
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "unknown": decision == "UNKNOWN",
                    "correct": correct,
                }
            )
        met = metrics_from_rows(norm_rows)
        met["result"] = d.get("result")
        met["achieved_streak"] = d.get("achieved_streak")
        met["path"] = str(path)
        out["conditions"][key] = met
    return out


def run_probes_dir(models: list[str], probes_root: Path) -> dict:
    report: dict[str, Any] = {"mode": "probes_dir", "ts": utc_now(), "probes_root": str(probes_root), "by_model": {}, "rows": []}
    if not probes_root.is_dir():
        report["status"] = "NÃO TESTADO"
        report["reason"] = "probes dir missing"
        return report
    # expect probes_root/<condition>/<sid>_dXm.jpg or meta.json
    any_probe = False
    for cond_dir in sorted(probes_root.iterdir()):
        if not cond_dir.is_dir():
            continue
        for jpg in sorted(cond_dir.glob("*.jpg")):
            any_probe = True
            # parse: lab01_d2_glasses.jpg or lab01.jpg
            stem = jpg.stem
            parts = stem.split("_")
            sid = parts[0]
            distance_m = None
            for p in parts:
                if p.startswith("d") and p[1:].replace("p", "").isdigit():
                    distance_m = float(p[1:].replace("p", "."))
            img = cv2.imread(str(jpg))
            if img is None:
                continue
            for model in models:
                gallery = load_gallery(model)
                emb = embed_crop_model(img, model)
                expected = "UNKNOWN" if sid.upper() == "UNKNOWN" else sid
                row = decide(
                    emb,
                    gallery,
                    expected=expected,
                    model=model,
                    condition=cond_dir.name,
                    distance_m=distance_m,
                    meta={"probe": str(jpg)},
                )
                report["rows"].append(row)
    if not any_probe:
        report["status"] = "NÃO TESTADO"
        report["reason"] = "no jpg probes"
        return report
    for model in models:
        report["by_model"][model] = metrics_from_rows([r for r in report["rows"] if r["model"] == model])
    report["status"] = "OK"
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="facenet,arcface")
    ap.add_argument("--mode", default="all", choices=["all", "offline", "import_live", "templates", "multiperson", "probes_dir"])
    ap.add_argument("--probes-dir", type=Path, default=BENCH_OUT / "probes")
    args = ap.parse_args()
    ensure_bench_dirs()
    models = [m.strip() for m in args.models.split(",") if m.strip() and m.strip() != "adaface"]

    bundle: dict[str, Any] = {
        "ts": utc_now(),
        "threshold": 0.70,
        "margin": 0.10,
        "licenses": LICENSE_NOTES,
        "models_requested": models,
        "adaface": LICENSE_NOTES["adaface"],
        "sections": {},
    }

    if args.mode in ("all", "offline"):
        bundle["sections"]["offline"] = run_offline(models)
    if args.mode in ("all", "multiperson"):
        bundle["sections"]["multiperson_sim"] = run_multiperson_sim(models)
    if args.mode in ("all", "templates"):
        bundle["sections"]["multi_template"] = run_template_variants(models)
    if args.mode in ("all", "import_live"):
        bundle["sections"]["facenet_live_import"] = import_facenet_live_evidence()
    if args.mode in ("all", "probes_dir"):
        bundle["sections"]["probes_dir"] = run_probes_dir(models, args.probes_dir)

    out = BENCH_OUT / "runs" / f"benchmark_{utc_now().replace(':', '').replace('+', '')[:15]}.json"
    latest = BENCH_OUT / "SUMMARY_latest.json"
    save_json(out, bundle)
    save_json(latest, bundle)
    print(json.dumps({"ok": True, "out": str(out), "latest": str(latest), "sections": list(bundle["sections"].keys())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
