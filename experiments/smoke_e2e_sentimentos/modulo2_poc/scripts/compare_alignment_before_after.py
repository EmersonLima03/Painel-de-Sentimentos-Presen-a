#!/usr/bin/env python3
"""Compara evidências before (fallback) × after (product alignment) — só registro."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = RESULTS / "aligned_v2" / "COMPARE_before_after.json"


def _load(path: Path):
    if not path.exists():
        return None
    for enc in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            continue
    return None


def _score_stats(samples, key_score="score"):
    vals = []
    for s in samples or []:
        v = s.get(key_score)
        if v is None:
            v = s.get("top1_score")
        if isinstance(v, (int, float)):
            vals.append(float(v))
    if not vals:
        return None
    return {
        "n": len(vals),
        "min": round(min(vals), 6),
        "max": round(max(vals), 6),
        "mean": round(sum(vals) / len(vals), 6),
    }


def main() -> int:
    before = {
        "alignment_mode": "fallback_crop_resize_112",
        "gallery": "gallery_temp/facenet",
        "enroll": _load(RESULTS / "enroll_ui_lab01.json"),
        "unknown": _load(RESULTS / "unknown_probe" / "SUMMARY_xwf2.json"),
        "distance_1m": _load(RESULTS / "distance_probe" / "SUMMARY_1m.json"),
        "distance_2m": _load(RESULTS / "distance_probe" / "SUMMARY_2m_retry.json")
        or _load(RESULTS / "distance_probe" / "SUMMARY_2m_playwright.json")
        or _load(RESULTS / "distance_probe" / "SUMMARY_2m.json"),
        "bridge": _load(RESULTS / "bridge_latest.json"),
    }
    after_dir = RESULTS / "aligned_v2"
    enroll_after = _load(RESULTS / "enroll_ui_lab01_aligned_v2.json")
    suite_enroll = _load(after_dir / "02_enroll.json")
    if suite_enroll and (suite_enroll.get("n_samples") or 0) >= 4:
        enroll_after = {
            "student_id": "lab01",
            "gallery_version": "facenet_aligned_v2",
            "alignment_mode": "product_crop_aligned_face",
            "samples": suite_enroll.get("samples") or [],
            "n_captures": suite_enroll.get("n_samples"),
            "source": "aligned_v2/02_enroll.json",
        }
    after = {
        "alignment_mode": "product_crop_aligned_face",
        "gallery": "gallery_temp/facenet_aligned_v2",
        "enroll": enroll_after,
        "suite": _load(after_dir / "SUMMARY.json"),
        "recognize": _load(after_dir / "03_recognize.json"),
        "unknown": _load(after_dir / "04_unknown.json"),
        "distance_1m": _load(after_dir / "05_distance_1m.json"),
        "distance_2m": _load(after_dir / "06_distance_2m.json"),
        "bridge": _load(RESULTS / "bridge_aligned_v2_latest.json"),
        "smoke_alignment": _load(RESULTS / "smoke_alignment_once.json"),
    }

    unk_after = after["unknown"] or {}
    unk_interpreted = unk_after.get("interpreted_result") or unk_after.get("result")

    comparison = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": "Registro factual before×after — sem julgar melhoria/piora automaticamente.",
        "before": {
            "alignment_mode": before["alignment_mode"],
            "gallery": before["gallery"],
            "enroll_n_samples": len((before["enroll"] or {}).get("samples") or []),
            "unknown_decision": (before["unknown"] or {}).get("decision"),
            "unknown_score": (before["unknown"] or {}).get("top1_score"),
            "unknown_result": (before["unknown"] or {}).get("result"),
            "d1_result": (before["distance_1m"] or {}).get("result"),
            "d1_scores": _score_stats((before["distance_1m"] or {}).get("samples")),
            "d2_result": (before["distance_2m"] or {}).get("result"),
            "d2_scores": _score_stats((before["distance_2m"] or {}).get("samples")),
            "bridge_safe": ((before["bridge"] or {}).get("summary") or {}).get("bridge_safe"),
            "bridge_max_score_delta": ((before["bridge"] or {}).get("summary") or {}).get("max_score_abs_delta"),
        },
        "after": {
            "alignment_mode": after["alignment_mode"],
            "gallery": after["gallery"],
            "enroll_n_samples": len((after["enroll"] or {}).get("samples") or []),
            "enroll_alignment_modes": [
                s.get("alignment_mode") for s in ((after["enroll"] or {}).get("samples") or [])
            ],
            "smoke_alignment_ok": (after["smoke_alignment"] or {}).get("ok"),
            "recognize_result": (after["recognize"] or {}).get("result"),
            "recognize_scores": _score_stats((after["recognize"] or {}).get("samples")),
            "unknown_result_raw": unk_after.get("result"),
            "unknown_interpreted": unk_interpreted,
            "unknown_reason": unk_after.get("reason"),
            "unknown_scores": _score_stats(unk_after.get("samples")),
            "d1_result": (after["distance_1m"] or {}).get("result"),
            "d1_scores": _score_stats((after["distance_1m"] or {}).get("samples")),
            "d2_result": (after["distance_2m"] or {}).get("result"),
            "d2_scores": _score_stats((after["distance_2m"] or {}).get("samples")),
            "bridge_safe": ((after["bridge"] or {}).get("summary") or {}).get("bridge_safe"),
            "bridge_max_score_delta": ((after["bridge"] or {}).get("summary") or {}).get("max_score_abs_delta"),
        },
        "deltas": {},
    }

    for key in ("d1_scores", "d2_scores"):
        b = comparison["before"].get(key)
        a = comparison["after"].get(key)
        if b and a and b.get("mean") is not None and a.get("mean") is not None:
            comparison["deltas"][f"{key}_mean_after_minus_before"] = round(a["mean"] - b["mean"], 6)

    rec = comparison["after"].get("recognize_scores")
    if rec and comparison["before"].get("d1_scores"):
        # referência: recognize after vs d1 before (aprox. mesma distância curta) — só registro
        comparison["deltas"]["recognize_after_mean_minus_d1_before_mean"] = round(
            rec["mean"] - comparison["before"]["d1_scores"]["mean"], 6
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT), "deltas": comparison["deltas"], "before_d1": comparison["before"]["d1_scores"], "after_d1": comparison["after"]["d1_scores"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
