#!/usr/bin/env python3
"""
Opção A — auditoria de ponte matcher (somente leitura / em memória).

Carrega embeddings TEMP já existentes em results/gallery_temp/facenet_aligned_v2/
(ou --gallery), consulta FAISSMatcher do produto em memória e compara com match_gallery do POC.

REGRAS:
- NÃO escreve no banco / face_embeddings
- NÃO chama reload_matcher
- NÃO altera app/vision/**, config, thresholds, Debug Vision, M1/M3/LXP
- Evidência apenas em results/bridge_*.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.smoke_e2e_sentimentos.modulo2_poc.scripts.poc_common import (  # noqa: E402
    CROPS_ACTIVE,
    GALLERY_ACTIVE,
    RESULTS,
    embed_crop,
    ensure_dirs,
    load_gallery_facenet,
    match_gallery,
)
from app.vision.matcher import FAISSMatcher, competitor_margin_from_topk  # noqa: E402

# Thresholds experimentais do POC (não alterar produto / TRI).
THRESHOLD = 0.70
MARGIN = 0.10
DIM = 512


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _decide_poc(query: np.ndarray, gallery: list[tuple[str, np.ndarray]]) -> dict[str, Any]:
    m = match_gallery(query, gallery, THRESHOLD, MARGIN)
    return {
        "student_id_expected_context": None,
        "top1": m.get("top1_id"),
        "score": m.get("top1_score"),
        "margin": m.get("margin"),
        "threshold": THRESHOLD,
        "margin_req": MARGIN,
        "decision": m.get("decision"),
        "raw": m.get("raw"),
        "path": "poc_match_gallery",
    }


def _decide_faiss(query: np.ndarray, matcher: FAISSMatcher) -> dict[str, Any]:
    """Espelha find_match do produto, expondo top1/score/margin mesmo em UNKNOWN."""
    topk = matcher.find_match_topk_extended(query, k=15)
    if not topk:
        return {
            "top1": None,
            "score": None,
            "margin": None,
            "threshold": THRESHOLD,
            "margin_req": MARGIN,
            "decision": "UNKNOWN",
            "raw": "UNKNOWN",
            "path": "product_FAISSMatcher",
            "find_match_return": None,
        }

    top1_id, top1_sim = topk[0]
    marg, _, _ = competitor_margin_from_topk(topk)
    hit = matcher.find_match(query, threshold=THRESHOLD, k=15, margin=MARGIN)
    if hit is None:
        decision = "UNKNOWN"
        raw = "UNKNOWN"
        find_ret = None
    else:
        decision = hit[0]
        raw = "ID"
        find_ret = {"student_id": hit[0], "score": float(hit[1])}

    return {
        "top1": top1_id,
        "score": round(float(top1_sim), 6),
        "margin": None if marg is None else round(float(marg), 6),
        "threshold": THRESHOLD,
        "margin_req": MARGIN,
        "decision": decision,
        "raw": raw,
        "path": "product_FAISSMatcher",
        "find_match_return": find_ret,
        "topk_preview": [{"student_id": s, "score": round(float(sc), 6)} for s, sc in topk[:5]],
    }


def _diff_row(poc: dict[str, Any], faiss: dict[str, Any]) -> dict[str, Any]:
    score_poc = poc.get("score")
    score_faiss = faiss.get("score")
    score_delta = None
    if score_poc is not None and score_faiss is not None:
        score_delta = round(float(score_faiss) - float(score_poc), 8)

    marg_poc = poc.get("margin")
    marg_faiss = faiss.get("margin")
    margin_delta = None
    if marg_poc is not None and marg_faiss is not None:
        margin_delta = round(float(marg_faiss) - float(marg_poc), 8)

    same_top1 = poc.get("top1") == faiss.get("top1")
    same_decision = poc.get("decision") == faiss.get("decision")
    same_raw = poc.get("raw") == faiss.get("raw")

    return {
        "same_top1": same_top1,
        "same_decision": same_decision,
        "same_raw": same_raw,
        "score_delta_faiss_minus_poc": score_delta,
        "margin_delta_faiss_minus_poc": margin_delta,
        "score_abs_delta": None if score_delta is None else abs(score_delta),
        "bridge_ok_row": bool(same_top1 and same_decision and same_raw and (score_delta is None or abs(score_delta) < 1e-4)),
    }


def _run_probe(
    name: str,
    query: np.ndarray,
    gallery: list[tuple[str, np.ndarray]],
    matcher: FAISSMatcher,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    poc = _decide_poc(query, gallery)
    faiss_r = _decide_faiss(query, matcher)
    diff = _diff_row(poc, faiss_r)
    return {
        "probe": name,
        "meta": meta or {},
        "poc": poc,
        "faiss": faiss_r,
        "diff": diff,
    }


def _load_named_gallery(gallery_root: Path | None = None) -> list[tuple[str, str, np.ndarray]]:
    """Retorna (student_id, pose_stem, vec) a partir dos .npy."""
    root = gallery_root or GALLERY_ACTIVE
    out: list[tuple[str, str, np.ndarray]] = []
    if not root.is_dir():
        return out
    for person in sorted(root.iterdir()):
        if not person.is_dir():
            continue
        for f in sorted(person.glob("*.npy")):
            v = np.load(f).astype(np.float32).reshape(-1)
            n = float(np.linalg.norm(v) + 1e-12)
            out.append((person.name, f.stem, v / n))
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Bridge FAISSMatcher vs POC match_gallery (TEMP only)")
    ap.add_argument(
        "--gallery",
        type=Path,
        default=GALLERY_ACTIVE,
        help="Dir da galeria TEMP (default: facenet_aligned_v2)",
    )
    ap.add_argument("--tag", type=str, default="aligned_v2", help="Sufixo no nome do JSON de saída")
    args = ap.parse_args()

    ensure_dirs()
    named = _load_named_gallery(args.gallery)
    gallery = [(sid, vec) for sid, _, vec in named]
    stamp = _utc_stamp()
    out_path = RESULTS / f"bridge_{args.tag}_{stamp}.json"
    latest_path = RESULTS / f"bridge_{args.tag}_latest.json"

    report: dict[str, Any] = {
        "audit": "option_a_bridge_matcher_temp",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "rules": {
            "db_write": False,
            "face_embeddings_write": False,
            "reload_matcher": False,
            "product_files_modified": False,
            "alignment_fix": True,
            "scope": "modulo2_poc harness only; FAISSMatcher in-memory",
        },
        "params": {
            "threshold": THRESHOLD,
            "margin": MARGIN,
            "gallery_dir": str(args.gallery),
            "dim": DIM,
            "faiss_index": "IndexFlatIP",
        },
        "gallery": {
            "n_templates": len(named),
            "student_ids": sorted({sid for sid, _, _ in named}),
            "templates": [{"student_id": sid, "pose": pose, "dim": int(vec.shape[0])} for sid, pose, vec in named],
        },
        "probes": [],
        "summary": {},
    }

    if not gallery:
        report["summary"] = {"error": "empty_gallery_temp", "bridge_safe": False}
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"ok": False, "out": str(out_path), "error": "empty_gallery"}, ensure_ascii=False))
        return 2

    # FAISSMatcher real do produto, apenas em memória (sem DB).
    matcher = FAISSMatcher(list(gallery), dim=DIM)

    probes: list[dict[str, Any]] = []

    # 1) Cada embedding da galeria como probe (mesmo vetor / self-match).
    for sid, pose, vec in named:
        probes.append(
            _run_probe(
                f"gallery_self::{sid}::{pose}",
                vec,
                gallery,
                matcher,
                meta={"source": "gallery_npy", "student_id": sid, "pose": pose, "mode": "self_in_gallery"},
            )
        )

    # 2) Leave-one-out: remove o próprio template da galeria/índice.
    for i, (sid, pose, vec) in enumerate(named):
        gallery_loo = [(s, v) for j, (s, _, v) in enumerate(named) if j != i]
        matcher_loo = FAISSMatcher(list(gallery_loo), dim=DIM)
        probes.append(
            _run_probe(
                f"gallery_loo::{sid}::{pose}",
                vec,
                gallery_loo,
                matcher_loo,
                meta={
                    "source": "gallery_npy",
                    "student_id": sid,
                    "pose": pose,
                    "mode": "leave_one_out",
                    "gallery_n": len(gallery_loo),
                },
            )
        )

    # 3) Re-embed dos crops alinhados v2 (mesmos probes de face quando existem).
    crop_dir = CROPS_ACTIVE / "lab01"
    if not crop_dir.is_dir():
        # fallback de evidência: crops legados (não misturar na galeria v2)
        crop_dir = Path()  # skip
    if crop_dir.is_dir():
        for jpg in sorted(crop_dir.glob("*.jpg")):
            img = cv2.imread(str(jpg))
            if img is None:
                probes.append(
                    {
                        "probe": f"crop_reembed::{jpg.stem}",
                        "meta": {"source": "crop_jpg", "error": "imread_failed", "path": str(jpg)},
                        "poc": None,
                        "faiss": None,
                        "diff": {"bridge_ok_row": False},
                    }
                )
                continue
            emb = embed_crop(img)
            probes.append(
                _run_probe(
                    f"crop_reembed::{jpg.stem}",
                    emb,
                    gallery,
                    matcher,
                    meta={"source": "crop_jpg_reembed_facenet", "path": str(jpg), "student_id": "lab01", "pose": jpg.stem},
                )
            )

    # 4) Probe sintético UNKNOWN (vetor ortogonal aproximado / aleatório L2).
    rng = np.random.default_rng(42)
    unknown_vec = rng.normal(size=(DIM,)).astype(np.float32)
    unknown_vec /= float(np.linalg.norm(unknown_vec) + 1e-12)
    probes.append(
        _run_probe(
            "synthetic_unknown_random",
            unknown_vec,
            gallery,
            matcher,
            meta={"source": "synthetic_l2_random", "seed": 42, "expected_decision": "UNKNOWN"},
        )
    )

    report["probes"] = probes

    n = len(probes)
    ok_rows = sum(1 for p in probes if (p.get("diff") or {}).get("bridge_ok_row"))
    score_deltas = [
        (p.get("diff") or {}).get("score_abs_delta")
        for p in probes
        if (p.get("diff") or {}).get("score_abs_delta") is not None
    ]
    decision_mismatches = [
        p["probe"]
        for p in probes
        if p.get("poc") and p.get("faiss") and p["poc"].get("decision") != p["faiss"].get("decision")
    ]
    top1_mismatches = [
        p["probe"]
        for p in probes
        if p.get("poc") and p.get("faiss") and p["poc"].get("top1") != p["faiss"].get("top1")
    ]
    max_score_delta = max(score_deltas) if score_deltas else 0.0
    mean_score_delta = float(sum(score_deltas) / len(score_deltas)) if score_deltas else 0.0

    same_results = ok_rows == n and not decision_mismatches and not top1_mismatches
    # Ponte segura se decisões idênticas e deltas numéricos desprezíveis (< 1e-4).
    bridge_safe = (not decision_mismatches) and (not top1_mismatches) and (max_score_delta < 1e-4)

    report["summary"] = {
        "n_probes": n,
        "n_bridge_ok_rows": ok_rows,
        "same_results": same_results,
        "max_score_abs_delta": round(float(max_score_delta), 8),
        "mean_score_abs_delta": round(float(mean_score_delta), 8),
        "decision_mismatches": decision_mismatches,
        "top1_mismatches": top1_mismatches,
        "bridge_safe": bridge_safe,
        "notes": [
            "Comparação em memória: mesmos embeddings TEMP; FAISSMatcher sem DB.",
            "Threshold/margin = POC experimental 0.70 / 0.10 (não TRI).",
            "Galeria alinhada com product crop_aligned_face (facenet_aligned_v2).",
        ],
    }

    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out_path),
                "latest": str(latest_path),
                "summary": report["summary"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
