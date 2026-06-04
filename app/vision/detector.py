"""Detector de faces (pluggable)."""

import threading

import cv2
import numpy as np
from typing import List, Optional, Tuple
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

# Par detector+embedder InsightFace (criados juntos)
_insightface_pair: Optional[Tuple["FaceDetector", "object"]] = None


class FaceDetector:
    """Interface para detector de faces."""

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detecta faces no frame.

        Retorna: Lista de (x, y, w, h) bounding boxes.
        """
        raise NotImplementedError


class SimulationDetector(FaceDetector):
    """Detector simulado para testes."""

    def __init__(self, max_faces: int = 12):
        self.frame_count = 0
        self.max_faces = max_faces

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Gera detecções simuladas."""
        self.frame_count += 1

        if self.frame_count % 3 == 0:
            h, w = frame.shape[:2]
            num_faces = min(np.random.randint(3, 11), self.max_faces)
            faces = []
            for _ in range(num_faces):
                x = np.random.randint(0, max(1, w - 100))
                y = np.random.randint(0, max(1, h - 100))
                face_w = np.random.randint(40, 120)
                face_h = np.random.randint(40, 120)
                faces.append((x, y, face_w, face_h))
            return faces
        return []


class OpenCVHaarDetector(FaceDetector):
    """Detector usando OpenCV Haar Cascades."""

    def __init__(self):
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        if self.face_cascade.empty():
            raise RuntimeError("Failed to load Haar cascade")

        logger.info("detector_initialized", type="opencv_haar")

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(40, 40),
        )
        return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]


class MediaPipeDetector(FaceDetector):
    """MediaPipe Tasks API — short_range (perto) ou full_range (várias distâncias)."""

    MODELS = {
        "short_range": (
            "blaze_face_short_range.tflite",
            "https://storage.googleapis.com/mediapipe-models/face_detector/"
            "blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
        ),
        "full_range": (
            "blaze_face_full_range.tflite",
            "https://storage.googleapis.com/mediapipe-models/face_detector/"
            "blaze_face_full_range/float16/1/blaze_face_full_range.tflite",
        ),
    }

    def __init__(
        self,
        variant: str = "full_range",
        min_detection_confidence: float = 0.45,
        min_score: float = 0.4,
        max_faces: int = 16,
    ):
        if variant not in self.MODELS:
            variant = "full_range"
        self.variant = variant
        self.min_score = min_score
        self.max_faces = max_faces
        filename, url = self.MODELS[variant]
        self._model_filename = filename
        self._model_url = url

        try:
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.vision.core import image as mp_image

            self._vision = vision
            self._mp_image = mp_image
        except ImportError as e:
            raise RuntimeError("MediaPipe not installed") from e

        model_path = self._get_model_path()
        try:
            from mediapipe.tasks.python.core import base_options as mp_base_options

            opts = vision.FaceDetectorOptions(
                base_options=mp_base_options.BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                min_detection_confidence=min_detection_confidence,
                min_suppression_threshold=0.3,
            )
            self.face_detector = vision.FaceDetector.create_from_options(opts)
            logger.info(
                "detector_initialized",
                type="mediapipe",
                variant=variant,
                max_faces=max_faces,
            )
        except Exception as e:
            self.face_detector = vision.FaceDetector.create_from_model_path(model_path)
            logger.warning("mediapipe_options_fallback", error=str(e), variant=variant)

    def _get_model_path(self) -> str:
        from pathlib import Path
        import urllib.request

        cache_dir = Path(__file__).resolve().parent.parent.parent / "data" / "mediapipe_models"
        cache_dir.mkdir(parents=True, exist_ok=True)
        model_path = cache_dir / self._model_filename

        if model_path.exists():
            return str(model_path)

        try:
            logger.info("mediapipe_model_downloading", path=str(model_path), url=self._model_url)
            urllib.request.urlretrieve(self._model_url, model_path)
            logger.info("mediapipe_model_downloaded", path=str(model_path))
            return str(model_path)
        except Exception as e:
            logger.warning("mediapipe_model_download_failed", error=str(e), path=str(model_path))
            raise RuntimeError(
                f"Failed to download MediaPipe face model: {e}. "
                f"Manually download {self._model_url} to {model_path}"
            ) from e

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if not rgb_frame.flags["C_CONTIGUOUS"]:
            rgb_frame = np.ascontiguousarray(rgb_frame)
        mp_image = self._mp_image.Image(
            image_format=self._mp_image.ImageFormat.SRGB,
            data=rgb_frame,
        )
        try:
            result = self.face_detector.detect(mp_image)
        except RuntimeError as e:
            logger.warning("mediapipe_detect_failed", variant=self.variant, error=str(e))
            return []

        scored: List[Tuple[float, Tuple[int, int, int, int]]] = []
        if result.detections:
            for detection in result.detections:
                score = float(detection.categories[0].score) if detection.categories else 0.0
                if score < self.min_score:
                    continue
                bbox = detection.bounding_box
                x = int(bbox.origin_x)
                y = int(bbox.origin_y)
                face_w = int(bbox.width)
                face_h = int(bbox.height)
                scored.append((score, (x, y, face_w, face_h)))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [b for _, b in scored[: self.max_faces]]


class YuNetDetector(FaceDetector):
    """YuNet (OpenCV DNN): vários rostos e distâncias ~10–300 px; roda bem em CPU/Windows."""

    _MODEL_URL = (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx"
    )

    def __init__(
        self,
        score_threshold: float = 0.55,
        nms_threshold: float = 0.35,
        max_faces: int = 16,
    ):
        model_path = self._get_model_path()
        self.max_faces = max_faces
        self.score_threshold = score_threshold
        self.detector = cv2.FaceDetectorYN.create(
            str(model_path),
            "",
            (320, 320),
            score_threshold,
            nms_threshold,
            max_faces,
        )
        # YuNet/OpenCV DNN não é thread-safe: presença + detect_only + engajamento compartilham esta instância
        self._lock = threading.Lock()
        logger.info("detector_initialized", type="yunet", max_faces=max_faces)

    def _get_model_path(self) -> str:
        from pathlib import Path
        import urllib.request

        cache_dir = Path(__file__).resolve().parent.parent.parent / "data" / "opencv_models"
        cache_dir.mkdir(parents=True, exist_ok=True)
        model_path = cache_dir / "face_detection_yunet_2023mar.onnx"
        if model_path.exists():
            return str(model_path)
        logger.info("yunet_model_downloading", url=self._MODEL_URL)
        urllib.request.urlretrieve(self._MODEL_URL, model_path)
        logger.info("yunet_model_downloaded", path=str(model_path))
        return str(model_path)

    def detect_detailed(self, frame: np.ndarray) -> List:
        """Detecção com bbox, score e 5 landmarks (YuNet)."""
        from app.vision.face_types import FaceDetectionResult

        if frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        if h < 2 or w < 2:
            return []

        # Cópia contígua evita assertion inputs[0].data == outputs[0].data em uso concorrente/in-place
        inp = np.ascontiguousarray(frame.copy())

        with self._lock:
            self.detector.setInputSize((w, h))
            try:
                _, faces = self.detector.detect(inp)
            except cv2.error as e:
                logger.warning("yunet_detect_failed", error=str(e))
                return []

        if faces is None or len(faces) == 0:
            return []
        out: List[FaceDetectionResult] = []
        # Não impor piso 0.55: câmeras DVR/teto costumam scores 0.35–0.55 em rostos válidos
        min_keep_score = max(0.35, float(self.score_threshold))
        for row in faces:
            x, y, fw, fh = int(row[0]), int(row[1]), int(row[2]), int(row[3])
            score = float(row[14]) if len(row) > 14 else float(row[4])
            if fw <= 0 or fh <= 0 or score < min_keep_score:
                continue
            lm = row[4:14].reshape(5, 2).astype(np.float32) if len(row) >= 14 else np.zeros((5, 2), dtype=np.float32)
            out.append(FaceDetectionResult(bbox=(x, y, fw, fh), score=score, landmarks=lm))
        out.sort(key=lambda d: d.score, reverse=True)
        return out[: self.max_faces]

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        return [d.bbox for d in self.detect_detailed(frame)]


class InsightFaceDetector(FaceDetector):
    """Detecção multi-rosto longa distância (InsightFace buffalo_l)."""

    def __init__(self, runtime, max_faces: int = 16, min_det_score: float = 0.45):
        self.runtime = runtime
        self.max_faces = max_faces
        self.min_det_score = min_det_score
        logger.info("detector_initialized", type="insightface", max_faces=max_faces)

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        hits = self.runtime.analyze(frame, min_det_score=self.min_det_score)
        return [bbox for bbox, _, _ in hits[: self.max_faces]]


def get_insightface_pair():
    """Retorna (detector, embedder) já acoplados."""
    global _insightface_pair
    return _insightface_pair


def _build_insightface_pair():
    from app.vision.insightface_runtime import get_insightface_runtime
    from app.vision.embedder import InsightFaceEmbedder

    settings = get_settings()
    det_size = int(getattr(settings, "vision_insightface_det_size", 960) or 960)
    size = (det_size, det_size)
    runtime = get_insightface_runtime(det_size=size)
    max_faces = int(getattr(settings, "vision_max_faces", 16) or 16)
    min_score = float(getattr(settings, "vision_insightface_min_det_score", 0.45) or 0.45)
    detector = InsightFaceDetector(runtime, max_faces=max_faces, min_det_score=min_score)
    embedder = InsightFaceEmbedder(runtime)
    return detector, embedder


def create_detector() -> FaceDetector:
    """Factory para criar detector baseado em configuração."""
    global _insightface_pair
    settings = get_settings()
    max_faces = int(getattr(settings, "vision_max_faces", 16) or 16)

    if settings.simulation:
        logger.info("using_simulation_detector")
        return SimulationDetector(max_faces=max_faces)

    backend = (getattr(settings, "vision_detector_backend", None) or "full_range").strip().lower()

    if settings.real or (not settings.simulation and settings.cameras):
        if backend == "insightface":
            try:
                _insightface_pair = _build_insightface_pair()
                logger.info("using_realtime_detector", type="insightface")
                return _insightface_pair[0]
            except Exception as e:
                logger.warning("insightface_detector_failed", error=str(e), fallback="yunet")
                backend = "yunet"

        if backend in ("yunet", "yu-net"):
            try:
                yunet_thr = float(
                    getattr(settings, "vision_yunet_score_threshold", 0.62) or 0.62
                )
                detector = YuNetDetector(
                    score_threshold=yunet_thr,
                    max_faces=max_faces,
                )
                logger.info("using_realtime_detector", type="yunet")
                return detector
            except Exception as e:
                logger.warning("yunet_failed", error=str(e), fallback="mediapipe_short_range")
                backend = "short_range"

        variant = "full_range" if backend in ("full_range", "full", "long") else "short_range"
        if backend == "short_range":
            variant = "short_range"
        try:
            min_conf = float(getattr(settings, "vision_mediapipe_min_confidence", 0.45) or 0.45)
            detector = MediaPipeDetector(
                variant=variant,
                min_detection_confidence=min_conf,
                max_faces=max_faces,
            )
            logger.info("using_realtime_detector", type="mediapipe", variant=variant)
            return detector
        except Exception as e:
            logger.warning("mediapipe_failed", error=str(e), fallback="opencv_haar")
            try:
                return OpenCVHaarDetector()
            except Exception as e2:
                logger.error("opencv_haar_failed", error=str(e2), fallback="simulation")
                return SimulationDetector(max_faces=max_faces)

    return SimulationDetector(max_faces=max_faces)
