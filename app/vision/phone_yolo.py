"""
Detecção opcional de celular (YOLO) no frame completo.

Desligado por padrão. Se ultralytics/pesos não estiverem disponíveis,
retorna lista vazia sem falhar o pipeline.

Não baixar conf sem diagnóstico — last_debug expõe amostras para calibração.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_model = None
_model_failed = False
_last_debug: Dict[str, Any] = {
    "provider": "yolo",
    "status": "not_run",
    "detections": [],
}

# COCO class id for cell phone
_CELL_PHONE_CLASS = 67


def get_phone_detector_debug() -> Dict[str, Any]:
    return dict(_last_debug)


def _bbox_plausible(
    w: int,
    h: int,
    *,
    max_tall_ratio: float,
    max_wide_ratio: float,
) -> bool:
    """Rejeita garrafa/térmico (alto/estreito); aceita celular deitado no peito (largo)."""
    if w < 8 or h < 8:
        return False
    if h / float(w) > max_tall_ratio:
        return False
    if w / float(h) > max_wide_ratio:
        return False
    return True


def _torso_roi(person: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
    px, py, pw, ph = person
    return (
        int(px + pw * 0.06),
        int(py + ph * 0.18),
        max(16, int(pw * 0.88)),
        max(16, int(ph * 0.50)),
    )


def _iou_xywh(a: Tuple[int, ...], b: Tuple[int, ...]) -> float:
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _person_has_nearby_phone(
    phones: List[Tuple[int, int, int, int, float]],
    person: Tuple[float, float, float, float],
    *,
    iou_min: float = 0.08,
) -> bool:
    roi = _torso_roi(person)
    for ph in phones:
        if _iou_xywh(ph, roi) >= iou_min:
            return True
        pcx = ph[0] + ph[2] / 2.0
        pcy = ph[1] + ph[3] / 2.0
        px, py, pw, phh = person
        if px <= pcx <= px + pw and py + phh * 0.12 <= pcy <= py + phh * 0.72:
            return True
    return False


def _infer_phones_on_image(
    model,
    image: np.ndarray,
    *,
    conf_thr: float,
    max_tall_ratio: float,
    max_wide_ratio: float,
    source: str,
) -> Tuple[List[Tuple[int, int, int, int, float]], List[dict], List[dict]]:
    results = model.predict(image, verbose=False, conf=conf_thr)
    out: List[Tuple[int, int, int, int, float]] = []
    dets_debug: List[dict] = []
    rejected: List[dict] = []
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
            w, h = x2 - x1, y2 - y1
            bbox = [x1, y1, w, h]
            entry = {
                "class_id": cls_id,
                "class_name": "cell phone",
                "confidence": round(conf, 3),
                "bbox": bbox,
                "height_width_ratio": round(h / max(w, 1), 3),
                "width_height_ratio": round(w / max(h, 1), 3),
                "source": source,
            }
            if not _bbox_plausible(
                w, h, max_tall_ratio=max_tall_ratio, max_wide_ratio=max_wide_ratio
            ):
                entry["reject_reason"] = "aspect_ratio_unlikely_phone"
                rejected.append(entry)
                continue
            out.append((x1, y1, w, h, conf))
            dets_debug.append(entry)
    return out, dets_debug, rejected


def detect_phones(
    frame: np.ndarray,
    person_boxes: Optional[Dict[str, Tuple[float, float, float, float]]] = None,
) -> List[Tuple[int, int, int, int, float]]:
    """
    Retorna lista de (x, y, w, h, conf) para celulares detectados.
    Sem modelo: []. Filtra bbox improvável (aspect ratio) para reduzir FP em garrafas.
    """
    global _model, _model_failed, _last_debug
    settings = get_settings()
    conf_thr = float(getattr(settings, "phone_yolo_conf_threshold", 0.42) or 0.42)
    max_tall = float(getattr(settings, "phone_yolo_max_height_width_ratio", 2.7) or 2.7)
    max_wide = float(getattr(settings, "phone_yolo_max_width_height_ratio", 4.0) or 4.0)
    torso_pass = bool(getattr(settings, "phone_yolo_torso_pass_enabled", True))
    torso_conf = float(getattr(settings, "phone_yolo_torso_conf_threshold", 0.30) or 0.30)
    fw = int(frame.shape[1]) if frame is not None else 0
    fh = int(frame.shape[0]) if frame is not None else 0
    _last_debug = {
        "provider": "yolo",
        "status": "disabled",
        "frame_width": fw,
        "frame_height": fh,
        "inference_width": None,
        "detections": [],
        "rejected_detections": [],
        "inference_ms": 0.0,
        "class_id": _CELL_PHONE_CLASS,
        "class_name": "cell phone",
        "conf_threshold": conf_thr,
        "max_height_width_ratio": max_tall,
        "max_width_height_ratio": max_wide,
        "torso_pass_enabled": torso_pass,
        "torso_conf_threshold": torso_conf,
    }
    if not getattr(settings, "phone_yolo_enabled", False):
        _last_debug["status"] = "disabled"
        _last_debug["reason"] = "phone_yolo_disabled"
        return []
    if _model_failed:
        _last_debug["status"] = "unavailable"
        _last_debug["reason"] = "model_failed"
        return []
    if frame is None:
        _last_debug["status"] = "error"
        _last_debug["reason"] = "no_frame"
        return []

    try:
        import time

        t0 = time.perf_counter()
        if _model is None:
            from ultralytics import YOLO

            path = getattr(settings, "phone_yolo_model_path", None) or "yolov8n.pt"
            _model = YOLO(path)
            logger.info("phone_yolo_loaded", path=path)
        out, dets_debug, rejected = _infer_phones_on_image(
            _model,
            frame,
            conf_thr=conf_thr,
            max_tall_ratio=max_tall,
            max_wide_ratio=max_wide,
            source="full_frame",
        )

        if torso_pass and person_boxes:
            ih, iw = frame.shape[:2]
            for _pid, pb in person_boxes.items():
                if _person_has_nearby_phone(out, pb):
                    continue
                rx, ry, rw, rh = _torso_roi(pb)
                x1, y1 = max(0, rx), max(0, ry)
                x2, y2 = min(iw, rx + rw), min(ih, ry + rh)
                crop = frame[y1:y2, x1:x2]
                if crop.size == 0 or crop.shape[0] < 24 or crop.shape[1] < 24:
                    continue
                ch, cw = crop.shape[:2]
                infer_img = crop
                scale = 1.0
                if max(cw, ch) < 280:
                    scale = 280.0 / max(cw, ch)
                    import cv2

                    infer_img = cv2.resize(
                        crop,
                        (max(24, int(cw * scale)), max(24, int(ch * scale))),
                        interpolation=cv2.INTER_LINEAR,
                    )
                torso_out, torso_dets, torso_rej = _infer_phones_on_image(
                    _model,
                    infer_img,
                    conf_thr=torso_conf,
                    max_tall_ratio=max_tall,
                    max_wide_ratio=max_wide,
                    source="torso_roi",
                )
                inv = 1.0 / scale
                for tx, ty, tw, th, tconf in torso_out:
                    fx = int(x1 + tx * inv)
                    fy = int(y1 + ty * inv)
                    fw_, fh_ = int(tw * inv), int(th * inv)
                    candidate = (fx, fy, fw_, fh_, tconf)
                    if any(_iou_xywh(candidate, existing) >= 0.35 for existing in out):
                        continue
                    out.append(candidate)
                    dets_debug.append(
                        {
                            "class_id": _CELL_PHONE_CLASS,
                            "class_name": "cell phone",
                            "confidence": round(tconf, 3),
                            "bbox": [fx, fy, fw_, fh_],
                            "source": "torso_roi",
                            "person_bbox": [int(v) for v in pb[:4]],
                        }
                    )
                rejected.extend(torso_rej)

        _last_debug = {
            "provider": "yolo",
            "status": "available",
            "frame_width": fw,
            "frame_height": fh,
            "inference_width": fw,
            "detections": dets_debug,
            "rejected_detections": rejected,
            "inference_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "class_id": _CELL_PHONE_CLASS,
            "class_name": "cell phone",
            "conf_threshold": conf_thr,
            "max_height_width_ratio": max_tall,
            "max_width_height_ratio": max_wide,
            "torso_pass_enabled": torso_pass,
            "torso_conf_threshold": torso_conf,
            "detections_count": len(out),
            "rejected_count": len(rejected),
        }
        return out
    except Exception as e:
        _model_failed = True
        logger.warning("phone_yolo_unavailable", error=str(e))
        _last_debug["status"] = "unavailable"
        _last_debug["reason"] = str(e)
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
