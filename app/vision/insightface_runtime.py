"""Sessão compartilhada InsightFace (detecção + embedding em um passe)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)

BBox = Tuple[int, int, int, int]
FaceHit = Tuple[BBox, np.ndarray, float]

_runtime: Optional["InsightFaceRuntime"] = None


class InsightFaceRuntime:
    """buffalo_l: melhor para vários rostos e distâncias médias em CPU."""

    def __init__(self, det_size: Tuple[int, int] = (960, 960)):
        try:
            from insightface.app import FaceAnalysis
        except ImportError as e:
            raise RuntimeError(
                "InsightFace não instalado. Rode: pip install insightface onnxruntime"
            ) from e

        self.det_size = det_size
        self.app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        self.app.prepare(ctx_id=-1, det_size=det_size)
        self._last_frame_id: Optional[int] = None
        self._embedding_by_bbox: Dict[BBox, np.ndarray] = {}
        logger.info(
            "insightface_runtime_ready",
            det_size=det_size,
            model="buffalo_l",
        )

    def analyze(self, frame: np.ndarray, min_det_score: float = 0.45) -> List[FaceHit]:
        """Detecta rostos e embeddings no frame inteiro (1 inferência)."""
        import cv2

        if frame is None or frame.size == 0:
            self._clear_cache(None)
            return []

        if len(frame.shape) == 2:
            img = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        else:
            img = frame

        faces = self.app.get(img)
        hits: List[FaceHit] = []
        cache: Dict[BBox, np.ndarray] = {}

        for f in faces:
            score = float(getattr(f, "det_score", 0.0) or 0.0)
            if score < min_det_score:
                continue
            x1, y1, x2, y2 = f.bbox.astype(int).tolist()
            w, h = max(1, x2 - x1), max(1, y2 - y1)
            bbox: BBox = (x1, y1, w, h)
            emb = np.asarray(f.normed_embedding, dtype=np.float32)
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            cache[bbox] = emb
            hits.append((bbox, emb, score))

        hits.sort(key=lambda t: t[2], reverse=True)
        self._last_frame_id = id(frame)
        self._embedding_by_bbox = cache
        return hits

    def _clear_cache(self, frame_id: Optional[int]) -> None:
        self._last_frame_id = frame_id
        self._embedding_by_bbox = {}

    def get_cached_embedding(
        self,
        frame: Optional[np.ndarray],
        bbox: Optional[BBox],
    ) -> Optional[np.ndarray]:
        if frame is None or bbox is None:
            return None
        if id(frame) != self._last_frame_id:
            return None
        emb = self._embedding_by_bbox.get(bbox)
        if emb is not None:
            return emb.astype(np.float32)
        # IoU fallback (bbox pode ter 1–2 px de diferença após crop/refine)
        bx, by, bw, bh = bbox
        best_key = None
        best_iou = 0.0
        for (kx, ky, kw, kh) in self._embedding_by_bbox:
            iou = _bbox_iou((bx, by, bw, bh), (kx, ky, kw, kh))
            if iou > best_iou:
                best_iou = iou
                best_key = (kx, ky, kw, kh)
        if best_key and best_iou >= 0.5:
            return self._embedding_by_bbox[best_key].astype(np.float32)
        return None


def _bbox_iou(a: BBox, b: BBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def get_insightface_runtime(det_size: Tuple[int, int] = (960, 960)) -> InsightFaceRuntime:
    global _runtime
    if _runtime is None or _runtime.det_size != det_size:
        _runtime = InsightFaceRuntime(det_size=det_size)
    return _runtime


def reset_insightface_runtime() -> None:
    global _runtime
    _runtime = None
