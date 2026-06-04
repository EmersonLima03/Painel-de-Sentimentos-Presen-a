"""Pipeline de visão: detecção YuNet + alinhamento + embedding ONNX em lote."""

from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

import numpy as np

from app.config import get_settings
from app.logging import get_logger
from app.vision.detector import FaceDetector, YuNetDetector, create_detector
from app.vision.embedder import FaceEmbedder
from app.vision.face_alignment import crop_aligned_face
from app.vision.face_filters import stabilize_face_detections
from app.vision.face_types import FaceDetectionResult
from app.vision.embedder import onnx_runtime_available

logger = get_logger(__name__)


class FacePipeline:
    """
    Detecção + alinhamento + embeddings ONNX.
    Presença consome o frame mais recente; embed em batch para N rostos.
    """

    def __init__(
        self,
        detector: Optional[FaceDetector] = None,
        embedder: Optional[FaceEmbedder] = None,
    ):
        settings = get_settings()
        self.detector = detector or create_detector()
        self.embedder = embedder or self._create_embedder()
        self.max_faces = int(getattr(settings, "vision_max_faces", 10) or 10)
        self.min_face_size = int(settings.face_min_size or 42)
        self.min_face_area_ratio = float(getattr(settings, "vision_min_face_area_ratio", 0.0015) or 0.0015)
        self.aspect_min = float(getattr(settings, "vision_face_aspect_min", 0.45) or 0.45)
        self.aspect_max = float(getattr(settings, "vision_face_aspect_max", 1.55) or 1.55)
        self.single_subject_mode = bool(getattr(settings, "vision_single_subject_mode", False))
        self._last_process_ts = 0.0
        self._processing = False
        self._lock = threading.Lock()

    @staticmethod
    def _create_embedder() -> FaceEmbedder:
        backend = (getattr(get_settings(), "vision_embedder_backend", None) or "").strip().lower()
        if backend in ("onnx", "arcface", "onnxruntime") and onnx_runtime_available():
            try:
                from app.vision.onnx_embedder import OnnxFaceEmbedder

                return OnnxFaceEmbedder()
            except Exception as e:
                logger.warning("onnx_embedder_init_failed", error=str(e))
        from app.vision.embedder import create_embedder

        return create_embedder()

    def _detect_with_landmarks_unlocked(self, frame: np.ndarray) -> List[FaceDetectionResult]:
        if isinstance(self.detector, YuNetDetector):
            raw = self.detector.detect_detailed(frame)
        else:
            raw = [
                FaceDetectionResult(bbox=b, score=1.0, landmarks=np.zeros((5, 2), dtype=np.float32))
                for b in self.detector.detect(frame)
            ]

        h, w = frame.shape[:2]
        bboxes = [d.bbox for d in raw]
        stable = stabilize_face_detections(
            bboxes,
            h,
            w,
            min_face_size=self.min_face_size,
            min_area_ratio=self.min_face_area_ratio,
            aspect_min=self.aspect_min,
            aspect_max=self.aspect_max,
            single_subject_mode=self.single_subject_mode,
            max_faces=self.max_faces,
        )
        stable_set = set(stable)
        out: List[FaceDetectionResult] = []
        for d in raw:
            if d.bbox in stable_set:
                out.append(d)
        return out[: self.max_faces]

    def detect_with_landmarks(self, frame: np.ndarray) -> List[FaceDetectionResult]:
        with self._lock:
            return self._detect_with_landmarks_unlocked(frame)

    def build_aligned_crops(
        self,
        frame: np.ndarray,
        detections: List[FaceDetectionResult],
    ) -> List[Tuple[FaceDetectionResult, np.ndarray]]:
        crops: List[Tuple[FaceDetectionResult, np.ndarray]] = []
        for det in detections:
            crop = crop_aligned_face(frame, det.bbox, det.landmarks, output_size=(112, 112))
            if crop is not None and crop.size > 0:
                crops.append((det, crop))
        return crops

    def _embed_detections_unlocked(
        self,
        frame: np.ndarray,
        detections: List[FaceDetectionResult],
    ) -> List[Tuple[FaceDetectionResult, Optional[np.ndarray]]]:
        pairs = self.build_aligned_crops(frame, detections)
        if not pairs:
            return [(d, None) for d in detections]

        rois = [c for _, c in pairs]
        if hasattr(self.embedder, "embed_batch"):
            embeddings = self.embedder.embed_batch(rois)  # type: ignore[attr-defined]
        else:
            embeddings = [self.embedder.embed(r) for r in rois]

        result: List[Tuple[FaceDetectionResult, Optional[np.ndarray]]] = []
        for (det, _), emb in zip(pairs, embeddings):
            result.append((det, emb))
        paired_ids = {id(d) for d, _ in pairs}
        for d in detections:
            if id(d) not in paired_ids:
                result.append((d, None))
        return result

    def embed_detections(
        self,
        frame: np.ndarray,
        detections: Optional[List[FaceDetectionResult]] = None,
    ) -> List[Tuple[FaceDetectionResult, Optional[np.ndarray]]]:
        with self._lock:
            if detections is None:
                detections = self._detect_with_landmarks_unlocked(frame)
            return self._embed_detections_unlocked(frame, detections)

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        skip_if_busy: bool = True,
    ) -> dict:
        """
        Um ciclo completo para presença/overlay pesado.
        skip_if_busy: ignora se o ciclo anterior ainda não terminou (frame skipping).
        """
        if skip_if_busy and self._processing:
            return {"skipped": True, "detections": [], "embedded": []}

        self._processing = True
        t0 = time.perf_counter()
        try:
            with self._lock:
                detections = self._detect_with_landmarks_unlocked(frame)
                embedded = self._embed_detections_unlocked(frame, detections)
            self._last_process_ts = time.time()
            return {
                "skipped": False,
                "detections": detections,
                "embedded": embedded,
                "elapsed_ms": (time.perf_counter() - t0) * 1000,
            }
        finally:
            self._processing = False

    def detect_only(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        return [d.bbox for d in self.detect_with_landmarks(frame)]
