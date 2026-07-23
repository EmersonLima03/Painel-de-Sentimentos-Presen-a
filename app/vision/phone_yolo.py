"""
Detecção opcional de celular (YOLO).

Desligado por padrão. Se ultralytics/pesos não estiverem disponíveis,
retorna lista vazia sem falhar o pipeline.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_model = None
_model_failed = False

# COCO class id for cell phone
_CELL_PHONE_CLASS = 67


def detect_phones(frame: np.ndarray) -> List[Tuple[int, int, int, int, float]]:
    """
    Retorna lista de (x, y, w, h, conf) para celulares detectados.
    Sem modelo: [].
    """
    global _model, _model_failed
    settings = get_settings()
    if not getattr(settings, "phone_yolo_enabled", False):
        return []
    if _model_failed:
        return []

    try:
        if _model is None:
            from ultralytics import YOLO

            path = getattr(settings, "phone_yolo_model_path", None) or "yolov8n.pt"
            _model = YOLO(path)
            logger.info("phone_yolo_loaded", path=path)
        results = _model.predict(frame, verbose=False, conf=0.35)
        out: List[Tuple[int, int, int, int, float]] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id = int(box.cls[0]) if box.cls is not None else -1
                if cls_id != _CELL_PHONE_CLASS:
                    continue
                xyxy = box.xyxy[0].tolist()
                x1, y1, x2, y2 = [int(v) for v in xyxy]
                conf = float(box.conf[0]) if box.conf is not None else 0.0
                out.append((x1, y1, x2 - x1, y2 - y1, conf))
        return out
    except Exception as e:
        _model_failed = True
        logger.warning("phone_yolo_unavailable", error=str(e))
        return []


def phone_near_face(
    phone_boxes: List[Tuple[int, int, int, int, float]],
    face_boxes: List[Tuple],
    iou_thresh: float = 0.05,
) -> bool:
    """Heurística grosseira: celular sobreposto/perto de face → possível interação."""
    if not phone_boxes or not face_boxes:
        return False

    def iou(a, b):
        ax, ay, aw, ah = a[:4]
        bx, by, bw, bh = b[:4]
        ax2, ay2 = ax + aw, ay + ah
        bx2, by2 = bx + bw, by + bh
        ix1, iy1 = max(ax, bx), max(ay, by)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter <= 0:
            # proximidade por centro
            acx, acy = ax + aw / 2, ay + ah / 2
            bcx, bcy = bx + bw / 2, by + bh / 2
            dist = ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5
            return 1.0 if dist < max(aw, ah, bw, bh) * 1.2 else 0.0
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    for p in phone_boxes:
        for f in face_boxes:
            if iou(p, f) >= iou_thresh:
                return True
    return False
