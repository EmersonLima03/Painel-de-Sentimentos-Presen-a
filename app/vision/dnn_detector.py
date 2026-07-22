"""
Detector DNN OpenCV SSD (Real-Time-Classroom-Monitoring-System / OpenCV samples).
Complementa YuNet em salas com rostos médios/distantes.
"""

from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

from app.logging import get_logger
from app.vision.detector import FaceDetector

logger = get_logger(__name__)

_DNN_MEAN = (104.0, 177.0, 123.0)
_DNN_SIZE = (300, 300)


class OpenCVDnnFaceDetector(FaceDetector):
    def __init__(self, conf_threshold: float = 0.35, max_faces: int = 30):
        base = Path(__file__).resolve().parents[2] / "data" / "opencv_models"
        pb = base / "opencv_face_detector_uint8.pb"
        pbtxt = base / "opencv_face_detector.pbtxt"
        if not pb.is_file() or not pbtxt.is_file():
            raise FileNotFoundError(
                "Modelos DNN ausentes. Rode: python scripts/download_models.py"
            )
        self.net = cv2.dnn.readNetFromTensorflow(str(pb), str(pbtxt))
        self.conf_threshold = conf_threshold
        self.max_faces = max_faces
        logger.info("detector_initialized", type="opencv_dnn_ssd")

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        ih, iw = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(
            cv2.resize(frame, _DNN_SIZE),
            scalefactor=1.0,
            size=_DNN_SIZE,
            mean=_DNN_MEAN,
            swapRB=False,
            crop=False,
        )
        self.net.setInput(blob)
        out = self.net.forward()
        boxes = []
        if out is None or len(out.shape) < 4:
            return boxes
        for i in range(out.shape[2]):
            conf = float(out[0, 0, i, 2])
            if conf < self.conf_threshold:
                continue
            x1 = int(out[0, 0, i, 3] * iw)
            y1 = int(out[0, 0, i, 4] * ih)
            x2 = int(out[0, 0, i, 5] * iw)
            y2 = int(out[0, 0, i, 6] * ih)
            w, h = x2 - x1, y2 - y1
            if w >= 18 and h >= 18:
                boxes.append((x1, y1, w, h, conf))
        boxes.sort(key=lambda b: b[4], reverse=True)
        return [(x, y, w, h) for x, y, w, h, _ in boxes[: self.max_faces]]
