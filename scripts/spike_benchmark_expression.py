"""
Benchmark de provider de expressão (offline).
Macro-F1 / balanced accuracy somente com --labels (revisão humana).
Sem labels: latência, memória, falhas, inconclusive, flicker, concordância.
"""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np


def _load_frames(input_dir: Path) -> List[np.ndarray]:
    files = sorted(list(input_dir.glob("*.jpg")) + list(input_dir.glob("*.png")))
    frames = []
    for f in files:
        img = cv2.imread(str(f))
        if img is not None:
            frames.append(img)
    return frames


def _detect_faces(frame: np.ndarray):
    try:
        from app.vision.detector import create_detector

        det = create_detector()
        return det.detect(frame) or []
    except Exception:
        return []


def _crops(frame, boxes):
    out = []
    h, w = frame.shape[:2]
    for b in boxes:
        x, y, bw, bh = [int(v) for v in b[:4]]
        x2, y2 = min(w, x + bw), min(h, y + bh)
        x, y = max(0, x), max(0, y)
        if x2 > x and y2 > y:
            out.append(frame[y:y2, x:x2])
    return out


def _flicker_rate(labels: List[str]) -> float:
    if len(labels) < 2:
        return 0.0
    changes = sum(1 for i in range(1, len(labels)) if labels[i] != labels[i - 1])
    return changes / (len(labels) - 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--labels", default="", help="JSON map file->normalized_label (human review)")
    args = p.parse_args()

    from app.vision.expressions import create_expression_provider

    provider = create_expression_provider(args.provider)
    frames = _load_frames(Path(args.input))
    labels_map: Dict[str, str] = {}
    if args.labels:
        labels_map = json.loads(Path(args.labels).read_text(encoding="utf-8"))

    latencies = []
    preds_labels = []
    inconclusive = 0
    failures = 0
    y_true = []
    y_pred = []

    tracemalloc.start()
    for idx, frame in enumerate(frames):
        boxes = _detect_faces(frame)
        crops = _crops(frame, boxes) or [frame]
        t0 = time.perf_counter()
        try:
            preds = provider.predict_batch(crops[:1])
        except Exception:
            failures += 1
            preds = []
        dt = (time.perf_counter() - t0) * 1000.0
        latencies.append(dt)
        if not preds:
            inconclusive += 1
            preds_labels.append("inconclusive")
            continue
        pr = preds[0]
        preds_labels.append(pr.label)
        if not pr.is_conclusive or pr.label == "inconclusive":
            inconclusive += 1
        # supervised only with labels
        key = f"frame_{idx:05d}.jpg"
        if key in labels_map:
            y_true.append(labels_map[key])
            y_pred.append(pr.label)

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    latencies_sorted = sorted(latencies) or [0.0]
    def pct(arr, q):
        if not arr:
            return 0.0
        i = int(round((q / 100.0) * (len(arr) - 1)))
        return float(arr[i])

    report = {
        "provider": args.provider,
        "model_name": getattr(provider, "model_name", ""),
        "model_version": getattr(provider, "model_version", ""),
        "n_frames": len(frames),
        "latency_ms_p50": pct(latencies_sorted, 50),
        "latency_ms_p95": pct(latencies_sorted, 95),
        "latency_ms_mean": float(sum(latencies) / max(1, len(latencies))),
        "peak_memory_mb": peak / (1024 * 1024),
        "failures": failures,
        "inconclusive_rate": inconclusive / max(1, len(frames)),
        "flicker_rate": _flicker_rate(preds_labels),
        "label_histogram": dict(Counter(preds_labels)),
        "disclaimer": "Inter-model agreement is NOT accuracy. Macro-F1 only with human labels.",
        "supervised": None,
    }

    if y_true:
        # métricas supervisionadas simples
        classes = sorted(set(y_true) | set(y_pred))
        f1s = []
        recalls = []
        for c in classes:
            tp = sum(1 for a, b in zip(y_true, y_pred) if a == c and b == c)
            fp = sum(1 for a, b in zip(y_true, y_pred) if a != c and b == c)
            fn = sum(1 for a, b in zip(y_true, y_pred) if a == c and b != c)
            prec = tp / max(1, tp + fp)
            rec = tp / max(1, tp + fn)
            f1 = 2 * prec * rec / max(1e-9, prec + rec)
            f1s.append(f1)
            recalls.append(rec)
        report["supervised"] = {
            "macro_f1": float(sum(f1s) / max(1, len(f1s))),
            "balanced_accuracy": float(sum(recalls) / max(1, len(recalls))),
            "n_labeled": len(y_true),
        }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
