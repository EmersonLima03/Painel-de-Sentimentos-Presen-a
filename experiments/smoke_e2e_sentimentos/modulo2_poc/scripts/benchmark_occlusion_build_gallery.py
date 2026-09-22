#!/usr/bin/env python3
"""Constrói galerias benchmark_occlusion a partir de crops_aligned_v2 (sem misturar modelos)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from benchmark_occlusion_common import (  # noqa: E402
    BENCH_ROOT,
    CROPS_SRC,
    embed_crop_model,
    ensure_bench_dirs,
    save_json,
    utc_now,
)


def build_for_model(model: str) -> dict:
    out_root = BENCH_ROOT / model
    out_root.mkdir(parents=True, exist_ok=True)
    catalog = {"model": model, "ts": utc_now(), "students": {}, "alignment_note": "crops from crops_aligned_v2 (product_crop_aligned_face)"}
    if not CROPS_SRC.is_dir():
        catalog["error"] = "crops_aligned_v2 missing"
        return catalog
    for person_dir in sorted(CROPS_SRC.iterdir()):
        if not person_dir.is_dir():
            continue
        sid = person_dir.name
        dest = out_root / sid
        dest.mkdir(parents=True, exist_ok=True)
        samples = []
        for jpg in sorted(person_dir.glob("*.jpg")):
            img = cv2.imread(str(jpg))
            if img is None:
                continue
            emb = embed_crop_model(img, model)
            npy = dest / f"{jpg.stem}.npy"
            np.save(npy, emb)
            # also copy crop reference (already aligned 112)
            cv2.imwrite(str(dest / f"{jpg.stem}.jpg"), img)
            samples.append({"pose": jpg.stem, "npy": str(npy), "dim": int(emb.shape[0])})
        catalog["students"][sid] = {"n": len(samples), "samples": samples}
    return catalog


def build_variants() -> dict:
    """
    no_glasses: front + lateral_right + lateral_left sem óculos
    with_glasses: same + template glasses se existir probe
    """
    from benchmark_occlusion_common import BENCH_OUT

    report = {"ts": utc_now(), "variants": {}}
    poses_base = ["front", "lateral_right", "lateral_left"]
    for model in ("facenet", "arcface"):
        src = BENCH_ROOT / model
        if not src.is_dir():
            continue
        for sid_dir in sorted(src.iterdir()):
            if not sid_dir.is_dir():
                continue
            sid = sid_dir.name
            dest_a = BENCH_ROOT / "variants" / "no_glasses" / model / sid
            dest_b = BENCH_ROOT / "variants" / "with_glasses" / model / sid
            dest_a.mkdir(parents=True, exist_ok=True)
            dest_b.mkdir(parents=True, exist_ok=True)
            for pose in poses_base:
                npy = sid_dir / f"{pose}.npy"
                if npy.exists():
                    emb = np.load(npy)
                    np.save(dest_a / f"{pose}.npy", emb)
                    np.save(dest_b / f"{pose}.npy", emb)
            gpath = BENCH_OUT / "probes" / "glasses_degree" / f"{sid}_glasses.jpg"
            if gpath.exists():
                img = cv2.imread(str(gpath))
                if img is not None:
                    emb = embed_crop_model(img, model)
                    np.save(dest_b / "glasses_normal.npy", emb)
                    cv2.imwrite(str(dest_b / "glasses_normal.jpg"), img)
    report["variants"]["no_glasses"] = "built"
    report["variants"]["with_glasses"] = "built_if_probe_exists"
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="facenet,arcface", help="facenet,arcface (adaface skipped)")
    args = ap.parse_args()
    ensure_bench_dirs()
    models = [m.strip() for m in args.models.split(",") if m.strip() and m.strip() != "adaface"]
    catalogs = {}
    for model in models:
        print(f"[build] {model}…")
        catalogs[model] = build_for_model(model)
        print(catalogs[model].get("students"))
    catalogs["variants"] = build_variants()
    out = BENCH_ROOT / "BUILD_CATALOG.json"
    save_json(out, catalogs)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
