#!/usr/bin/env python3
"""Benchmark offline de galeria TEMP — NÃO toca face_embeddings de produção.

Uso:
  python scripts/bench_gallery_offline.py
  python scripts/bench_gallery_offline.py --gallery results/gallery_temp

Espera estrutura opcional:
  gallery_temp/
    <student_id>/
      *.npy   # embedding L2-normalizado float32
  probes/
    <label>__<student_id_or_unknown>.npy
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
DEFAULT_GALLERY = RESULTS / "gallery_temp"
DEFAULT_PROBES = RESULTS / "probes"


def l2_normalize(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32).reshape(-1)
    n = float(np.linalg.norm(v) + 1e-12)
    return v / n


def load_gallery(gallery_dir: Path) -> list[tuple[str, np.ndarray]]:
    items: list[tuple[str, np.ndarray]] = []
    if not gallery_dir.is_dir():
        return items
    for person_dir in sorted(gallery_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        sid = person_dir.name
        for f in sorted(person_dir.glob("*.npy")):
            vec = l2_normalize(np.load(f))
            items.append((sid, vec))
    return items


def load_probes(probes_dir: Path) -> list[tuple[str, str, np.ndarray]]:
    """Retorna (probe_id, expected_student_or_UNKNOWN, vec)."""
    out: list[tuple[str, str, np.ndarray]] = []
    if not probes_dir.is_dir():
        return out
    for f in sorted(probes_dir.glob("*.npy")):
        stem = f.stem
        if "__" in stem:
            probe_id, expected = stem.split("__", 1)
        else:
            probe_id, expected = stem, "UNKNOWN"
        out.append((probe_id, expected, l2_normalize(np.load(f))))
    return out


def match(
    query: np.ndarray,
    gallery: list[tuple[str, np.ndarray]],
    threshold: float,
    margin: float,
) -> dict:
    if not gallery:
        return {
            "top1_id": None,
            "top1_score": None,
            "margin": None,
            "decision": "UNKNOWN",
            "reason": "empty_gallery",
        }
    scores = [(sid, float(np.dot(query, vec))) for sid, vec in gallery]
    scores.sort(key=lambda x: x[1], reverse=True)
    top1_id, top1_score = scores[0]
    competitor = None
    for sid, sc in scores[1:]:
        if sid != top1_id:
            competitor = sc
            break
    marg = None if competitor is None else top1_score - competitor
    ok_score = top1_score >= threshold
    ok_margin = True if marg is None else marg >= margin
    decision = "ID" if (ok_score and ok_margin) else "UNKNOWN"
    return {
        "top1_id": top1_id,
        "top1_score": round(top1_score, 6),
        "margin": None if marg is None else round(marg, 6),
        "decision": decision if decision == "UNKNOWN" else top1_id,
        "raw_decision": decision,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline gallery match (TEMP only)")
    ap.add_argument("--gallery", type=Path, default=DEFAULT_GALLERY)
    ap.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    ap.add_argument("--threshold", type=float, default=0.70, help="POC threshold (not production write)")
    ap.add_argument("--margin", type=float, default=0.10)
    ap.add_argument("--out", type=Path, default=RESULTS / "bench_gallery_offline.json")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    gallery = load_gallery(args.gallery)
    probes = load_probes(args.probes)

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "gallery_dir": str(args.gallery),
        "probes_dir": str(args.probes),
        "gallery_templates": len(gallery),
        "gallery_students": len({s for s, _ in gallery}),
        "probes": len(probes),
        "threshold": args.threshold,
        "margin": args.margin,
        "status": "OK" if gallery and probes else "NÃO TESTADO",
        "reason": None
        if gallery and probes
        else "Galeria TEMP e/ou probes vazios — adicione .npy sob results/gallery_temp e results/probes",
        "cases": [],
        "note": "Não lê nem escreve face_embeddings de produção.",
    }

    for probe_id, expected, vec in probes:
        m = match(vec, gallery, args.threshold, args.margin)
        decided = m["decision"]
        tp = fp = fn = unknown_ok = False
        if expected.upper() == "UNKNOWN":
            unknown_ok = decided == "UNKNOWN"
        else:
            if decided == expected:
                tp = True
            elif decided == "UNKNOWN":
                fn = True
            else:
                fp = True
        report["cases"].append(
            {
                "probe_id": probe_id,
                "expected": expected,
                **m,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "unknown_ok": unknown_ok,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(args.out), "reason": report["reason"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
