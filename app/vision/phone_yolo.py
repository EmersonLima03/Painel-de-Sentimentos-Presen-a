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

# Estabilidade temporal bruta (zona orelha) — hits por chave espacial quantizada
_ear_stability: Dict[str, int] = {}
# Hold de detecção: YOLO pisca — manter última detecção válida (bbox contínua no overlay)
_last_kept_phones: List[Tuple[int, int, int, int, float]] = []
_last_kept_dets: List[dict] = []
_last_kept_ts: float = 0.0
_PHONE_DETECT_HOLD_SECONDS = 3.0

# COCO class id for cell phone
_CELL_PHONE_CLASS = 67


def get_phone_detector_debug() -> Dict[str, Any]:
    return dict(_last_debug)


def reset_ear_stability_for_tests() -> None:
    """Limpa acumulador de estabilidade (apenas testes)."""
    global _last_kept_phones, _last_kept_dets, _last_kept_ts
    _ear_stability.clear()
    _last_kept_phones = []
    _last_kept_dets = []
    _last_kept_ts = 0.0


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


def _ear_stability_key(
    phone: Tuple[int, int, int, int, float],
    person: Tuple[float, float, float, float],
) -> str:
    x, y, w, h, _conf = phone
    px, py, _pw, _ph = person
    return (
        f"{int(px / 20)}_{int(py / 20)}_"
        f"{int((x + w / 2.0) / 15)}_{int((y + h / 2.0) / 15)}"
    )


def _wrist_near_phone(
    phone: Tuple[int, int, int, int, float],
    person: Tuple[float, float, float, float],
    wrists: Optional[Dict[str, List[Tuple[float, float]]]],
    person_id: Optional[str] = None,
) -> bool:
    if not wrists:
        return False
    px, py, pw, ph = person
    diag = max(1.0, (pw**2 + ph**2) ** 0.5)
    pcx = phone[0] + phone[2] / 2.0
    pcy = phone[1] + phone[3] / 2.0
    candidates: List[Tuple[float, float]] = []
    if person_id and person_id in wrists:
        candidates = list(wrists.get(person_id) or [])
    else:
        for ws in wrists.values():
            candidates.extend(ws or [])
    for wpt in candidates:
        if wpt is None:
            continue
        dist = ((pcx - float(wpt[0])) ** 2 + (pcy - float(wpt[1])) ** 2) ** 0.5 / diag
        if dist <= 0.28:
            return True
    return False


def _in_ear_zone_geometry(
    phone: Tuple[int, int, int, int, float],
    person: Tuple[float, float, float, float],
) -> bool:
    x, y, w, h, _conf = phone
    px, py, pw, ph = person
    if pw < 8 or ph < 8:
        return False
    pcx = x + w / 2.0
    pcy = y + h / 2.0
    area_ratio = max(1.0, float(w * h)) / max(1.0, float(pw * ph))
    if area_ratio > 0.055:
        return False
    if pcy > py + ph * 0.35:
        return False
    return pcx < px + pw * 0.28 or pcx > px + pw * 0.72


def _context_reject_reason(
    phone: Tuple[int, int, int, int, float],
    person: Tuple[float, float, float, float],
    *,
    wrist_near: bool = False,
    stable_hits: int = 0,
) -> Optional[str]:
    """
    Rejeições geométricas relativas à pessoa (garrafa/térmico e zona de orelha/fone).

    ear_region_implausible exige combinação (não rejeita todo objeto perto da orelha):
    bbox pequena + sem punho + zona orelha/cabeça + geometria incompatível + falta de estabilidade.
    Celular real encostado à orelha (tamanho/aspecto, conf, punho ou estabilidade) passa.
    """
    x, y, w, h, conf = phone
    px, py, pw, ph = person
    if pw < 8 or ph < 8:
        return None
    pcx = x + w / 2.0
    pcy = y + h / 2.0
    hw = h / max(w, 1)
    phone_area = max(1.0, float(w * h))
    person_area = max(1.0, float(pw * ph))
    area_ratio = phone_area / person_area
    in_ear = _in_ear_zone_geometry(phone, person)
    width_frac = w / max(pw, 1.0)
    tall_vs_body = h >= ph * 0.18
    very_tall_vs_body = h >= ph * 0.28

    # Contrato (docs/TROUBLESHOOTING + momento em que D/eventos funcionavam):
    # celular vertical real em close-up NÃO é rejeitado só por altura relativa;
    # garrafa/térmico fino ou conf fraca continua rejeitado.
    # NÃO usar "bottle_column" agressivo — gerava FN em celular real na mão/rosto.
    thin_tall = width_frac <= 0.135 and hw >= 1.80
    keep_vertical_phone = (
        1.15 <= hw <= 2.40
        and width_frac >= 0.10
        and 0.015 <= area_ratio <= 0.11
        and w >= 26
        and h <= ph * 0.38
        and not (thin_tall and float(conf) < 0.62 and not wrist_near)
        and (
            wrist_near
            or float(conf) >= 0.50  # alinhado ao hold temporal / fase estável
        )
    )

    if not keep_vertical_phone:
        if not in_ear:
            if hw >= 1.55 and tall_vs_body:
                return "bottle_like_relative_height"
            if hw >= 1.35 and very_tall_vs_body:
                return "bottle_like_relative_height"
        elif hw >= 1.9 and h >= ph * 0.40:
            return "bottle_like_relative_height"

    if in_ear:
        if wrist_near:
            return None

        phone_like = (
            area_ratio >= 0.030
            and 1.15 <= hw <= 2.45
            and float(conf) >= 0.48
            and w >= 22
            and h >= 38
        )
        if phone_like and (stable_hits >= 2 or float(conf) >= 0.62 or area_ratio >= 0.038):
            return None

        small = area_ratio <= 0.038
        tiny = area_ratio <= 0.025
        incompatible_geom = hw < 1.0 or hw > 2.55 or (w < 18 and h < 26)
        weak_conf = float(conf) < 0.55
        unstable = int(stable_hits) < 2

        if small and (tiny or incompatible_geom) and (weak_conf or unstable):
            return "ear_region_implausible"
        if tiny and unstable and weak_conf:
            return "ear_region_implausible"
        if small and incompatible_geom and unstable and float(conf) < 0.65:
            return "ear_region_implausible"

    # Objeto alto lateral no tronco (térmico na mão lateral) — conf fraca.
    # Mantém limiar documentado (não endurecer sem amostras; evita FN em celular lateral).
    if hw >= 1.7 and conf < 0.55 and (pcx < px + pw * 0.22 or pcx > px + pw * 0.78):
        return "implausible_lateral_tall_object"

    return None


def _filter_phones_with_person_context(
    phones: List[Tuple[int, int, int, int, float]],
    dets_debug: List[dict],
    rejected: List[dict],
    person_boxes: Optional[Dict[str, Tuple[float, float, float, float]]],
    wrists: Optional[Dict[str, List[Tuple[float, float]]]] = None,
) -> List[Tuple[int, int, int, int, float]]:
    if not person_boxes or not phones:
        return phones
    kept: List[Tuple[int, int, int, int, float]] = []
    kept_debug: List[dict] = []
    seen_keys: set = set()
    for i, ph in enumerate(phones):
        reason = None
        best_key: Optional[str] = None
        for pid, pb in person_boxes.items():
            wrist_near = _wrist_near_phone(ph, pb, wrists, pid)
            key = _ear_stability_key(ph, pb)
            stable = int(_ear_stability.get(key, 0))
            reason = _context_reject_reason(
                ph, pb, wrist_near=wrist_near, stable_hits=stable
            )
            if reason is None and _in_ear_zone_geometry(ph, pb):
                best_key = key
            if reason:
                break
        entry = dets_debug[i] if i < len(dets_debug) else {
            "bbox": list(ph[:4]),
            "confidence": ph[4],
            "class_name": "cell phone",
        }
        if reason:
            rej = dict(entry)
            rej["reject_reason"] = reason
            rejected.append(rej)
            continue
        if best_key is not None:
            _ear_stability[best_key] = int(_ear_stability.get(best_key, 0)) + 1
            seen_keys.add(best_key)
        kept.append(ph)
        kept_debug.append(entry)
    for k in list(_ear_stability.keys()):
        if k not in seen_keys:
            _ear_stability[k] = max(0, int(_ear_stability[k]) - 1)
            if _ear_stability[k] <= 0:
                del _ear_stability[k]
    dets_debug[:] = kept_debug
    return kept


def _torso_roi(person: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
    """ROI peito + laterais (mão com celular costuma ficar fora do peito estreito)."""
    px, py, pw, ph = person
    return (
        int(px - pw * 0.08),
        int(py + ph * 0.10),
        max(16, int(pw * 1.16)),
        max(16, int(ph * 0.62)),
    )


def _upper_phone_roi(person: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
    """ROI cabeça/ombros — celular na mão perto do rosto (fora do peito puro)."""
    px, py, pw, ph = person
    return (
        int(px - pw * 0.06),
        int(py - ph * 0.04),
        max(16, int(pw * 1.12)),
        max(16, int(ph * 0.48)),
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
    results = model.predict(image, verbose=False, conf=conf_thr, classes=[_CELL_PHONE_CLASS])
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
    wrists: Optional[Dict[str, List[Tuple[float, float]]]] = None,
) -> List[Tuple[int, int, int, int, float]]:
    """
    Retorna lista de (x, y, w, h, conf) para celulares detectados.
    Sem modelo: []. Filtra bbox improvável (aspect ratio) para reduzir FP em garrafas.
    wrists opcional: evita rejeitar celular real na orelha quando há punho próximo.
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
            import cv2

            def _roi_pass(
                roi_fn,
                *,
                source: str,
                conf: float,
            ) -> None:
                nonlocal out, dets_debug, rejected
                for _pid, pb in person_boxes.items():
                    if _person_has_nearby_phone(out, pb):
                        continue
                    rx, ry, rw, rh = roi_fn(pb)
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
                        infer_img = cv2.resize(
                            crop,
                            (max(24, int(cw * scale)), max(24, int(ch * scale))),
                            interpolation=cv2.INTER_LINEAR,
                        )
                    roi_out, _roi_dets, roi_rej = _infer_phones_on_image(
                        _model,
                        infer_img,
                        conf_thr=conf,
                        max_tall_ratio=max_tall,
                        max_wide_ratio=max_wide,
                        source=source,
                    )
                    inv = 1.0 / scale
                    for tx, ty, tw, th, tconf in roi_out:
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
                                "source": source,
                                "person_bbox": [int(v) for v in pb[:4]],
                            }
                        )
                    rejected.extend(roi_rej)

            # Peito (já existente) + faixa superior (celular perto do rosto).
            _roi_pass(_torso_roi, source="torso_roi", conf=torso_conf)
            _roi_pass(_upper_phone_roi, source="upper_roi", conf=torso_conf)

        out = _filter_phones_with_person_context(
            out, dets_debug, rejected, person_boxes, wrists=wrists
        )

        global _last_kept_phones, _last_kept_dets, _last_kept_ts
        held = False
        if out:
            _last_kept_phones = list(out)
            _last_kept_dets = [dict(d) for d in dets_debug]
            _last_kept_ts = time.perf_counter()
        elif (
            _last_kept_phones
            and (time.perf_counter() - float(_last_kept_ts)) <= _PHONE_DETECT_HOLD_SECONDS
        ):
            # Hold só se a bbox ainda passa no filtro (não reanimar garrafa rejeitada).
            hold_debug = [dict(d) for d in _last_kept_dets]
            hold_rejected: List[dict] = []
            held_out = _filter_phones_with_person_context(
                list(_last_kept_phones),
                hold_debug,
                hold_rejected,
                person_boxes,
                wrists=wrists,
            )
            if held_out:
                out = held_out
                dets_debug = hold_debug
                for d in dets_debug:
                    d["held"] = True
                    d["hold_reason"] = "phone_detect_temporal_hold"
                held = True
            else:
                _last_kept_phones = []
                _last_kept_dets = []
                rejected.extend(hold_rejected)
        else:
            _last_kept_phones = []
            _last_kept_dets = []

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
            "detection_hold_active": held,
            "detection_hold_seconds": _PHONE_DETECT_HOLD_SECONDS,
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
