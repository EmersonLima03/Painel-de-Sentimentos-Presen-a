#!/usr/bin/env python3
"""
Benchmark oclusão/óculos — utilitários isolados do POC M2.

NÃO escreve em data/ do produto. NÃO altera app/vision.
ArcFace ONNX (w600k_r50) fica em modulo2_poc/models/ apenas.
"""
from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.request import urlretrieve

import cv2
import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
_POC = _SCRIPTS.parent
_REPO = _POC.parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from poc_common import (  # noqa: E402
    ALIGNMENT_MODE_PRODUCT,
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    embed_crop,
    ensure_dirs,
    get_facenet_embedder,
    match_gallery,
    quality_of_crop,
    select_primary_face,
)

RESULTS = _POC / "results"
BENCH_ROOT = RESULTS / "gallery_temp" / "benchmark_occlusion"
BENCH_OUT = RESULTS / "benchmark_occlusion"
CROPS_SRC = RESULTS / "crops_aligned_v2"
MODELS_POC = _POC / "models"
ARCFACE_ONNX = MODELS_POC / "w600k_r50.onnx"
_BUFFALO_ZIP_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"

THRESHOLD = 0.70
MARGIN = 0.10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_bench_dirs() -> None:
    ensure_dirs()
    for p in (
        BENCH_ROOT / "facenet",
        BENCH_ROOT / "arcface",
        BENCH_ROOT / "adaface",
        BENCH_OUT / "probes",
        BENCH_OUT / "runs",
        MODELS_POC,
    ):
        p.mkdir(parents=True, exist_ok=True)


def ensure_arcface_onnx_in_poc() -> Path:
    """Baixa w600k_r50.onnx SOMENTE para modulo2_poc/models/ (não toca data/)."""
    if ARCFACE_ONNX.exists() and ARCFACE_ONNX.stat().st_size > 1_000_000:
        return ARCFACE_ONNX
    MODELS_POC.mkdir(parents=True, exist_ok=True)
    zip_path = MODELS_POC / "buffalo_l.zip"
    print(f"[arcface] downloading buffalo_l.zip -> {MODELS_POC} (POC only)...")
    urlretrieve(_BUFFALO_ZIP_URL, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        found = None
        for name in zf.namelist():
            if name.endswith("w600k_r50.onnx"):
                found = name
                break
        if not found:
            raise RuntimeError("w600k_r50.onnx not found in buffalo_l.zip")
        zf.extract(found, MODELS_POC)
        extracted = MODELS_POC / found
        if extracted != ARCFACE_ONNX:
            if ARCFACE_ONNX.exists():
                ARCFACE_ONNX.unlink()
            extracted.replace(ARCFACE_ONNX)
    try:
        zip_path.unlink(missing_ok=True)
    except Exception:
        pass
    if not ARCFACE_ONNX.exists():
        raise RuntimeError("failed to place w600k_r50.onnx in POC models/")
    print(f"[arcface] ready: {ARCFACE_ONNX} ({ARCFACE_ONNX.stat().st_size} bytes)")
    return ARCFACE_ONNX


class PocArcFaceEmbedder:
    """ArcFace w600k_r50 via ORT — modelo apenas em modulo2_poc/models/."""

    def __init__(self) -> None:
        import onnxruntime as ort

        path = ensure_arcface_onnx_in_poc()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 8
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            str(path), opts, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self.dim = 512
        self.model_version = "poc-onnx-w600k_r50-512d"

    def embed(self, face_bgr: np.ndarray) -> np.ndarray:
        if face_bgr is None or face_bgr.size == 0:
            raise ValueError("empty face")
        if len(face_bgr.shape) == 2:
            face_bgr = cv2.cvtColor(face_bgr, cv2.COLOR_GRAY2BGR)
        face = cv2.resize(face_bgr, (112, 112), interpolation=cv2.INTER_LINEAR)
        face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB).astype(np.float32)
        face = (face - 127.5) / 128.0
        blob = np.transpose(face, (2, 0, 1))[np.newaxis, ...]
        out = self._session.run(None, {self._input_name: blob})[0]
        emb = np.asarray(out, dtype=np.float32).flatten()
        n = float(np.linalg.norm(emb) + 1e-12)
        return emb / n


_arcface: Optional[PocArcFaceEmbedder] = None


def get_arcface_embedder() -> PocArcFaceEmbedder:
    global _arcface
    if _arcface is None:
        _arcface = PocArcFaceEmbedder()
    return _arcface


def embed_crop_model(crop: np.ndarray, model: str) -> np.ndarray:
    model = model.lower()
    if model == "facenet":
        return embed_crop(crop)
    if model == "arcface":
        return get_arcface_embedder().embed(crop)
    if model == "adaface":
        raise RuntimeError("AdaFace NÃO TESTADO neste POC (licença pesos / dataset)")
    raise ValueError(f"unknown model: {model}")


def load_gallery(model: str, variant: str = "default") -> list[tuple[str, np.ndarray]]:
    """
    variant:
      default → benchmark_occlusion/<model>/<sid>/*.npy
      no_glasses → .../variants/no_glasses/<model>/
      with_glasses → .../variants/with_glasses/<model>/
    """
    if variant == "default":
        root = BENCH_ROOT / model
    else:
        root = BENCH_ROOT / "variants" / variant / model
    items: list[tuple[str, np.ndarray]] = []
    if not root.is_dir():
        return items
    for person in sorted(root.iterdir()):
        if not person.is_dir():
            continue
        for f in sorted(person.glob("*.npy")):
            v = np.load(f).astype(np.float32).reshape(-1)
            n = float(np.linalg.norm(v) + 1e-12)
            items.append((person.name, v / n))
    return items


def decide(
    query: np.ndarray,
    gallery: list[tuple[str, np.ndarray]],
    *,
    expected: str,
    model: str,
    condition: str,
    distance_m: Optional[float],
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    m = match_gallery(query, gallery, THRESHOLD, MARGIN)
    decision = m.get("decision")
    expected_u = (expected or "").upper()
    if expected_u == "UNKNOWN":
        tp = decision == "UNKNOWN"
        fp = decision not in (None, "UNKNOWN")
        fn = False
        correct = tp
    else:
        tp = decision == expected
        fp = decision not in (None, "UNKNOWN", expected)
        fn = decision == "UNKNOWN"
        correct = tp
    row = {
        "ts": utc_now(),
        "model": model,
        "condition": condition,
        "distance_m": distance_m,
        "expected": expected,
        "top1": m.get("top1_id"),
        "score": m.get("top1_score"),
        "margin": m.get("margin"),
        "decision": decision,
        "raw": m.get("raw"),
        "threshold": THRESHOLD,
        "margin_req": MARGIN,
        "n_templates": len(gallery),
        "alignment_mode": ALIGNMENT_MODE_PRODUCT,
        "correct": correct,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "unknown": decision == "UNKNOWN",
    }
    if meta:
        row.update(meta)
    return row


def metrics_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "status": "NÃO TESTADO"}
    scores = [float(r["score"]) for r in rows if r.get("score") is not None]
    margins = [float(r["margin"]) for r in rows if r.get("margin") is not None]
    n = len(rows)
    tp = sum(1 for r in rows if r.get("tp"))
    fp = sum(1 for r in rows if r.get("fp"))
    fn = sum(1 for r in rows if r.get("fn"))
    unk = sum(1 for r in rows if r.get("unknown"))
    correct = sum(1 for r in rows if r.get("correct"))
    # max consecutive correct
    streak = max_streak = 0
    for r in rows:
        if r.get("correct"):
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {
        "n": n,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "unknown": unk,
        "correct_rate": round(correct / n, 4) if n else None,
        "unknown_rate": round(unk / n, 4) if n else None,
        "score_min": round(min(scores), 6) if scores else None,
        "score_mean": round(sum(scores) / len(scores), 6) if scores else None,
        "score_max": round(max(scores), 6) if scores else None,
        "margin_min": round(min(margins), 6) if margins else None,
        "margin_mean": round(sum(margins) / len(margins), 6) if margins else None,
        "margin_max": round(max(margins), 6) if margins else None,
        "max_consecutive_correct": max_streak,
    }


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


LICENSE_NOTES = {
    "facenet": {
        "code": "facenet-pytorch / InceptionResnetV1 — verificar pacote; uso já no produto",
        "weights": "vggface2 via facenet-pytorch (já usado no POC/produto)",
        "poc_status": "TESTADO",
    },
    "arcface": {
        "code": "InsightFace MIT",
        "weights": "buffalo_l / w600k_r50 — InsightFace: non-commercial research only; comercial exige licença (recognition-oss-pack@insightface.ai)",
        "poc_status": "TESTADO_SOMENTE_PESQUISA_POC",
        "commercial_ready": False,
    },
    "adaface": {
        "code": "mk-minchul/AdaFace — MIT",
        "weights": "WebFace4M/12M — seguir licença do dataset de treino; HF CVLFace: 'follow the license of the training dataset'; código≠pesos≠uso comercial",
        "poc_status": "NÃO TESTADO",
        "reason": "Sem segurança suficiente sobre licença comercial dos pesos; não baixar neste POC",
        "commercial_ready": False,
    },
}
