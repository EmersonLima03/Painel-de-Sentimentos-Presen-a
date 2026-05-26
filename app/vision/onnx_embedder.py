"""Embedder facial via ONNX Runtime (CPU), sem PyTorch no hot path."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
import zipfile

import cv2
import numpy as np

from app.logging import get_logger
from app.vision.embedder import FaceEmbedder

logger = get_logger(__name__)

_MODEL_NAME = "w600k_r50.onnx"
_BUFFALO_ZIP_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
_EMBED_DIM = 512
_INPUT_SIZE = (112, 112)


def _ensure_onnx_model() -> Path:
    cache_dir = Path(__file__).resolve().parent.parent.parent / "data" / "onnx_models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_path = cache_dir / _MODEL_NAME
    if model_path.exists():
        return model_path

    import urllib.request

    zip_path = cache_dir / "buffalo_l.zip"
    logger.info("onnx_model_downloading", url=_BUFFALO_ZIP_URL)
    urllib.request.urlretrieve(_BUFFALO_ZIP_URL, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith(_MODEL_NAME):
                zf.extract(name, cache_dir)
                extracted = cache_dir / name
                if not extracted.exists():
                    extracted = cache_dir / Path(name).name
                if extracted.exists() and extracted != model_path:
                    extracted.replace(model_path)
                break
    try:
        zip_path.unlink(missing_ok=True)
    except Exception:
        pass
    if not model_path.exists():
        raise RuntimeError(f"{_MODEL_NAME} not found inside buffalo_l.zip")
    logger.info("onnx_model_ready", path=str(model_path))
    return model_path


class OnnxFaceEmbedder(FaceEmbedder):
    """ArcFace w600k_r50 via onnxruntime (512D, CPUExecutionProvider)."""

    def __init__(self):
        self._session = None
        self._input_name: Optional[str] = None
        self._model_path: Optional[Path] = None
        self.dim = _EMBED_DIM
        self.model_version = "onnx-w600k_r50-512d-v1"
        logger.info("embedder_initialized", type="onnx_lazy", dim=self.dim)

    def _ensure_session(self):
        if self._session is not None:
            return
        import onnxruntime as ort

        self._model_path = _ensure_onnx_model()
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = 8
        sess_options.inter_op_num_threads = 2
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(
            str(self._model_path),
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name
        logger.info("onnx_session_ready", path=str(self._model_path))

    def _preprocess(self, face_bgr: np.ndarray) -> np.ndarray:
        if face_bgr is None or face_bgr.size == 0:
            raise ValueError("empty face")
        if len(face_bgr.shape) == 2:
            face_bgr = cv2.cvtColor(face_bgr, cv2.COLOR_GRAY2BGR)
        face = cv2.resize(face_bgr, _INPUT_SIZE, interpolation=cv2.INTER_LINEAR)
        face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB).astype(np.float32)
        face = (face - 127.5) / 128.0
        return np.transpose(face, (2, 0, 1))[np.newaxis, ...]

    def embed(
        self,
        face_roi: np.ndarray,
        *,
        frame: Optional[np.ndarray] = None,
        bbox: Optional[tuple] = None,
    ) -> Optional[np.ndarray]:
        try:
            self._ensure_session()
            blob = self._preprocess(face_roi)
            out = self._session.run(None, {self._input_name: blob})[0]
            emb = np.asarray(out, dtype=np.float32).flatten()
            norm = np.linalg.norm(emb) + 1e-12
            return emb / norm
        except Exception as e:
            logger.warning("onnx_embedding_failed", error=str(e))
            return None

    def embed_batch(self, face_rois: List[np.ndarray]) -> List[Optional[np.ndarray]]:
        if not face_rois:
            return []
        try:
            self._ensure_session()
            blobs = np.concatenate([self._preprocess(f) for f in face_rois], axis=0)
            outs = self._session.run(None, {self._input_name: blobs})[0]
            results: List[Optional[np.ndarray]] = []
            for row in outs:
                emb = np.asarray(row, dtype=np.float32).flatten()
                norm = np.linalg.norm(emb) + 1e-12
                results.append(emb / norm)
            return results
        except Exception as e:
            logger.warning("onnx_batch_embedding_failed", error=str(e), count=len(face_rois))
            return [self.embed(f) for f in face_rois]

    def get_embedding_dim(self) -> int:
        return self.dim

    def get_model_version(self) -> str:
        return self.model_version
