"""Utilitários compartilhados do POC M2 — somente leitura do YuNet do repo; sem escrever no produto."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
RESULTS = ROOT / "results"
GALLERY = RESULTS / "gallery_temp"
PROBES = RESULTS / "probes"
CROPS = RESULTS / "crops"
# Galeria legacy (fallback crop+resize) — preservar para comparação before/after
GALLERY_FACENET_V1 = GALLERY / "facenet"
CROPS_V1 = CROPS
# Galeria alinhada com product crop_aligned_face (esta etapa)
GALLERY_FACENET_ALIGNED_V2 = GALLERY / "facenet_aligned_v2"
CROPS_ALIGNED_V2 = RESULTS / "crops_aligned_v2"
# Ativo no POC após correção de alignment
GALLERY_ACTIVE = GALLERY_FACENET_ALIGNED_V2
CROPS_ACTIVE = CROPS_ALIGNED_V2
ALIGNMENT_MODE_PRODUCT = "product_crop_aligned_face"
ALIGNMENT_MODE_FALLBACK = "fallback"
MODELS = ROOT / "models"
YUNET = REPO / "data" / "opencv_models" / "face_detection_yunet_2023mar.onnx"


class AlignmentError(Exception):
    """Alignment do produto falhou — captura NÃO é válida para fidelidade."""

    def __init__(self, reason: str, detail: str | None = None):
        self.reason = reason
        self.detail = detail
        msg = reason if not detail else f"{reason}: {detail}"
        super().__init__(msg)

# Permite importar app.* (somente leitura) se o usuário rodar a partir do repo
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def ensure_dirs() -> None:
    for p in (RESULTS, GALLERY, PROBES, CROPS, CROPS_ALIGNED_V2, GALLERY_FACENET_ALIGNED_V2, MODELS):
        p.mkdir(parents=True, exist_ok=True)


def load_cam_web_from_config() -> dict[str, Any]:
    """Lê cam-web do config.yaml do produto (mesmo do Debug Vision). Só leitura."""
    import yaml

    cfg_path = REPO / "config.yaml"
    out: dict[str, Any] = {
        "index": 2,
        "width": 1920,
        "height": 1080,
        "camera_id": "cam-web",
        "source": str(cfg_path),
    }
    if not cfg_path.exists():
        return out
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return out
    for cam in data.get("cameras") or []:
        if not isinstance(cam, dict):
            continue
        if cam.get("camera_id") != "cam-web":
            continue
        url = cam.get("rtsp_url")
        if url is not None and str(url).strip().isdigit():
            out["index"] = int(str(url).strip())
        if cam.get("webcam_width") is not None:
            out["width"] = int(cam["webcam_width"])
        if cam.get("webcam_height") is not None:
            out["height"] = int(cam["webcam_height"])
        break
    return out


CAM_WEB = load_cam_web_from_config()


def open_webcam(index: int | None = None, width: int | None = None, height: int | None = None):
    import cv2

    idx = int(CAM_WEB["index"] if index is None else index)
    w = int(CAM_WEB["width"] if width is None else width)
    h = int(CAM_WEB["height"] if height is None else height)

    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(idx)
    if not cap.isOpened():
        raise RuntimeError(
            f"Nao foi possivel abrir webcam index={idx} (cam-web do config.yaml). "
            "Feche o Debug Vision / outro app que esteja usando a USB e tente de novo."
        )
    # Mesmo pedido do produto (XWF 1080p)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    frame = None
    means: list[float] = []
    for _ in range(8):
        ok, frame = cap.read()
        if ok and frame is not None:
            means.append(float(frame.mean()))
    if frame is None or not means:
        cap.release()
        raise RuntimeError(f"Webcam index={idx} abriu mas nao entregou frame")
    if float(np.mean(means)) < 8.0:
        cap.release()
        raise RuntimeError(
            f"Webcam index={idx} entrega frames pretos (media={np.mean(means):.1f}). "
            f"USB XWF no config e index={CAM_WEB['index']} — feche apps e use esse indice."
        )
    return cap


_CAM_CACHE: dict[str, Any] = {"ts": 0.0, "items": []}
_CAM_CACHE_TTL_S = 45.0


def list_webcam_indices(max_index: int = 8, *, force: bool = False) -> list[dict]:
    """Lista indices USB. Cache curto evita LED piscando a cada clique em Detectar."""
    import time

    import cv2

    now = time.time()
    if (
        not force
        and _CAM_CACHE["items"]
        and (now - float(_CAM_CACHE["ts"])) < _CAM_CACHE_TTL_S
    ):
        return list(_CAM_CACHE["items"])

    found = []
    for i in range(0, max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(i)
        if not cap.isOpened():
            cap.release()
            continue
        means: list[float] = []
        w = h = None
        # Warm-up curto (LED ascende só o necessário)
        for _ in range(3):
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = int(frame.shape[0]), int(frame.shape[1])
            means.append(float(frame.mean()))
        mean = float(np.mean(means)) if means else 0.0
        has_image = bool(means) and mean > 8.0
        found.append(
            {
                "index": i,
                "opened": True,
                "frame_ok": bool(means),
                "has_image": has_image,
                "mean": round(mean, 1),
                "w": w,
                "h": h,
            }
        )
        cap.release()
    _CAM_CACHE["ts"] = now
    _CAM_CACHE["items"] = found
    return list(found)

def estimate_face_yaw(landmarks: list) -> Optional[float]:
    """Yaw relativo via landmarks YuNet (olho dir, olho esq, nariz, ...).

    Valor ~0 = frente.
    Positivo = pessoa virou à SUA direita (nariz desloca à direita na imagem espelhada típica USB).
    Negativo = pessoa virou à SUA esquerda.
    None se landmarks insuficientes.
    """
    if not landmarks or len(landmarks) < 3:
        return None
    reye, leye, nose = landmarks[0], landmarks[1], landmarks[2]
    mid_x = 0.5 * (float(reye[0]) + float(leye[0]))
    iod = abs(float(leye[0]) - float(reye[0]))
    if iod < 1e-3:
        return None
    # Invertido vs eixo da imagem para bater com "sua direita" no espelho USB
    return float((mid_x - float(nose[0])) / iod)


def pose_for_phase(phase: str, yaw: Optional[float]) -> dict[str, Any]:
    """Gate de pose tipo app de banco: so captura se a pose bater com a etapa."""
    FRONT_MAX = 0.18
    LATERAL_MIN = 0.28
    LATERAL_MAX = 0.90
    if yaw is None:
        return {
            "ok": False,
            "yaw": None,
            "hint": "Nao consegui medir a inclinacao do rosto",
            "bucket": "unknown",
            "guide": "none",
        }
    a = abs(float(yaw))
    if a <= FRONT_MAX:
        bucket = "front"
    elif a < LATERAL_MIN:
        bucket = "turning"
    elif a <= LATERAL_MAX:
        bucket = "lateral"
    else:
        bucket = "too_far"

    if phase == "front":
        if bucket == "front":
            return {
                "ok": True,
                "yaw": yaw,
                "hint": "Isso! Olhando para frente — mantenha",
                "bucket": bucket,
                "guide": "center",
            }
        return {
            "ok": False,
            "yaw": yaw,
            "hint": "Olhe de frente para a camera",
            "bucket": bucket,
            "guide": "center",
        }

    if phase == "lateral_right":
        if yaw >= LATERAL_MIN and yaw <= LATERAL_MAX:
            return {
                "ok": True,
                "yaw": yaw,
                "hint": "Lateral direita OK — mantenha",
                "bucket": "lateral_right",
                "guide": "right",
            }
        if yaw <= -LATERAL_MIN:
            return {
                "ok": False,
                "yaw": yaw,
                "hint": "Este lado e a esquerda — vire para a DIREITA",
                "bucket": "lateral_left",
                "guide": "right",
            }
        if bucket == "front":
            return {
                "ok": False,
                "yaw": yaw,
                "hint": "Siga a seta: vire ~45° para a SUA direita",
                "bucket": bucket,
                "guide": "right",
            }
        if bucket == "turning":
            return {
                "ok": False,
                "yaw": yaw,
                "hint": "Continue virando para a direita…",
                "bucket": bucket,
                "guide": "right",
            }
        if yaw > LATERAL_MAX:
            return {
                "ok": False,
                "yaw": yaw,
                "hint": "Passou demais — volte um pouco",
                "bucket": bucket,
                "guide": "right",
            }
        return {"ok": False, "yaw": yaw, "hint": "Ajuste a lateral direita", "bucket": bucket, "guide": "right"}

    if phase == "lateral_left":
        if yaw <= -LATERAL_MIN and yaw >= -LATERAL_MAX:
            return {
                "ok": True,
                "yaw": yaw,
                "hint": "Lateral esquerda OK — mantenha",
                "bucket": "lateral_left",
                "guide": "left",
            }
        if yaw >= LATERAL_MIN:
            return {
                "ok": False,
                "yaw": yaw,
                "hint": "Este lado e a direita — vire para a ESQUERDA",
                "bucket": "lateral_right",
                "guide": "left",
            }
        if bucket == "front":
            return {
                "ok": False,
                "yaw": yaw,
                "hint": "Siga a seta: vire ~45° para a SUA esquerda",
                "bucket": bucket,
                "guide": "left",
            }
        if bucket == "turning":
            return {
                "ok": False,
                "yaw": yaw,
                "hint": "Continue virando para a esquerda…",
                "bucket": bucket,
                "guide": "left",
            }
        if yaw < -LATERAL_MAX:
            return {
                "ok": False,
                "yaw": yaw,
                "hint": "Passou demais — volte um pouco",
                "bucket": bucket,
                "guide": "left",
            }
        return {"ok": False, "yaw": yaw, "hint": "Ajuste a lateral esquerda", "bucket": bucket, "guide": "left"}

    if phase == "validate":
        if bucket == "front":
            return {
                "ok": True,
                "yaw": yaw,
                "hint": "De frente de novo — confirmando",
                "bucket": bucket,
                "guide": "center",
            }
        return {
            "ok": False,
            "yaw": yaw,
            "hint": "Volte a olhar de frente para validar",
            "bucket": bucket,
            "guide": "center",
        }

    return {"ok": False, "yaw": yaw, "hint": "Ajuste a pose", "bucket": "unknown", "guide": "none"}


def _face_plausibility(face: dict[str, Any], frame_h: int, frame_w: int) -> float:
    """Score 0..1: rejeita FP tipico de torso/corpo (bbox grande sem geometria de rosto)."""
    bw = float(face.get("w") or 0)
    bh = float(face.get("h") or 0)
    if bw < 20 or bh < 20:
        return 0.0
    aspect = bw / max(bh, 1e-6)  # rosto ~0.65–1.15; torso costuma ser mais estreito/alto
    if aspect < 0.58 or aspect > 1.20:
        aspect_s = 0.05
    elif 0.72 <= aspect <= 1.05:
        aspect_s = 1.0
    else:
        aspect_s = 0.4

    det = float(face.get("det_score") or 0.0)
    lm = face.get("landmarks") or []
    lm_s = 0.0
    iod_ratio = 0.0
    if len(lm) >= 5:
        reye, leye, nose = lm[0], lm[1], lm[2]
        rmouth, lmouth = lm[3], lm[4]
        iod = abs(float(leye[0]) - float(reye[0]))
        iod_ratio = iod / max(bw, 1e-6)
        eye_y = 0.5 * (float(reye[1]) + float(leye[1]))
        mouth_y = 0.5 * (float(rmouth[1]) + float(lmouth[1]))
        # olhos no terço superior; boca abaixo do nariz
        eyes_band = face["y"] + 0.05 * bh <= eye_y <= face["y"] + 0.55 * bh
        mouth_below = mouth_y > float(nose[1]) and mouth_y <= face["y"] + 0.98 * bh
        eyes_inside = (
            face["x"] - 0.02 * bw <= min(reye[0], leye[0]) <= max(reye[0], leye[0]) <= face["x"] + 1.02 * bw
        )
        nose_between = min(reye[0], leye[0]) <= float(nose[0]) <= max(reye[0], leye[0])
        if eyes_inside and eyes_band and mouth_below and nose_between and 0.20 <= iod_ratio <= 0.58:
            lm_s = 1.0
        elif eyes_inside and 0.15 <= iod_ratio <= 0.70 and nose_between:
            lm_s = 0.35
        else:
            lm_s = 0.0
    elif len(lm) >= 3:
        lm_s = 0.15

    area_ratio = (bw * bh) / max(float(frame_h * frame_w), 1.0)
    # torso FP em 1080p costuma ser bem maior que rosto a 2m
    size_pen = 1.0
    if area_ratio > 0.10:
        size_pen = 0.15 if lm_s < 0.9 else 0.55
    elif area_ratio > 0.06:
        size_pen = 0.35 if lm_s < 0.9 else 0.75
    if bh > 0.32 * frame_h and lm_s < 0.9:
        size_pen = min(size_pen, 0.2)

    # sem landmarks bons, nunca passa de 0.4 (nao vence rosto real)
    if lm_s < 0.35:
        return float(max(0.0, min(0.39, 0.25 * det + 0.2 * aspect_s + 0.1 * size_pen)))

    return float(max(0.0, min(1.0, 0.30 * det + 0.40 * lm_s + 0.15 * aspect_s + 0.15 * size_pen)))


def detect_faces_yunet(frame: np.ndarray, score_th: float = 0.7) -> list[dict[str, Any]]:
    import cv2

    if not YUNET.exists():
        raise FileNotFoundError(f"YuNet ausente (somente leitura): {YUNET}")
    h, w = frame.shape[:2]
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), float(score_th), 0.3, 5000)
    det.setInputSize((w, h))
    _, faces = det.detect(frame)
    if faces is None:
        return []
    out: list[dict[str, Any]] = []
    for f in faces:
        x, y, bw, bh = map(float, f[:4])
        lm = [(float(f[i]), float(f[i + 1])) for i in range(4, 14, 2)]
        item = {
            "x": x,
            "y": y,
            "w": bw,
            "h": bh,
            "area": bw * bh,
            "det_score": float(f[-1]),
            "landmarks": lm,
        }
        item["face_score"] = _face_plausibility(item, h, w)
        out.append(item)
    out.sort(key=lambda d: (float(d.get("face_score") or 0), float(d.get("det_score") or 0)), reverse=True)
    return out


def select_primary_face(
    faces: list[dict[str, Any]],
    *,
    min_face_score: float = 0.55,
    frame_shape: Optional[tuple[int, int]] = None,
    prev: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Escolhe rosto real; descarta FP de corpo mesmo que maior."""
    if not faces:
        return None
    good = [f for f in faces if float(f.get("face_score") or 0) >= min_face_score]
    pool = good if good else []
    if not pool:
        # so aceita fallback se nao parecer torso gigante
        top = faces[0]
        fh = float((frame_shape or (1080, 1920))[0])
        if float(top.get("h") or 0) > 0.30 * fh and float(top.get("face_score") or 0) < 0.55:
            return None
        if float(top.get("face_score") or 0) < 0.35:
            return None
        pool = [top]

    # Se existe um rosto "bom e menor", descarta gigantes (corpo)
    best_small = None
    for f in pool:
        if float(f.get("face_score") or 0) >= 0.70:
            if best_small is None or float(f["area"]) < float(best_small["area"]):
                best_small = f
    if best_small is not None:
        max_area = float(best_small["area"]) * 2.0
        pool = [f for f in pool if float(f["area"]) <= max_area]
        if not pool:
            pool = [best_small]

    # Estabilidade temporal: se prev overlap razoavel com algum candidato, manter
    if prev is not None and pool:
        px, py, pw, ph = float(prev["x"]), float(prev["y"]), float(prev["w"]), float(prev["h"])
        pa = max(pw * ph, 1.0)

        def iou(f: dict[str, Any]) -> float:
            x1 = max(px, float(f["x"]))
            y1 = max(py, float(f["y"]))
            x2 = min(px + pw, float(f["x"]) + float(f["w"]))
            y2 = min(py + ph, float(f["y"]) + float(f["h"]))
            inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            union = pa + float(f["area"]) - inter
            return inter / max(union, 1e-6)

        sticky = [f for f in pool if iou(f) >= 0.25 and float(f.get("face_score") or 0) >= min_face_score - 0.05]
        if sticky:
            sticky.sort(key=lambda d: (float(d.get("face_score") or 0), float(d.get("det_score") or 0)), reverse=True)
            return sticky[0]

    pool.sort(key=lambda d: (float(d.get("face_score") or 0), float(d.get("det_score") or 0)), reverse=True)
    return pool[0]


def crop_bgr(frame: np.ndarray, face: dict[str, Any], pad: float = 0.15) -> np.ndarray:
    h, w = frame.shape[:2]
    x, y, bw, bh = face["x"], face["y"], face["w"], face["h"]
    px, py = bw * pad, bh * pad
    x1 = max(0, int(x - px))
    y1 = max(0, int(y - py))
    x2 = min(w, int(x + bw + px))
    y2 = min(h, int(y + bh + py))
    return frame[y1:y2, x1:x2].copy()


def quality_of_crop(crop: np.ndarray) -> tuple[str, float]:
    try:
        from app.vision.quality import calculate_face_quality

        return calculate_face_quality(crop)
    except Exception:
        # fallback mínimo se app indisponível
        import cv2

        if crop is None or crop.size == 0:
            return "poor", 0.0
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        blur = min(cv2.Laplacian(gray, cv2.CV_64F).var() / 100.0, 1.0)
        bri = 1.0 - abs(float(np.mean(gray)) - 140) / 140.0
        bri = max(0.0, min(1.0, bri))
        score = 0.5 * blur + 0.5 * bri
        label = "good" if score >= 0.7 else ("fair" if score >= 0.4 else "poor")
        return label, float(score)


def aligned_crop(frame: np.ndarray, face: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Alinhamento geométrico idêntico ao produto (somente leitura).

    Assinatura real:
        crop_aligned_face(frame, bbox, landmarks, output_size=(112, 112))

    Retorna (crop, meta) com alignment_mode=product_crop_aligned_face.
    NÃO faz fallback silencioso para crop+resize — levanta AlignmentError.
    """
    from app.vision.face_alignment import crop_aligned_face

    if frame is None or getattr(frame, "size", 0) == 0:
        raise AlignmentError("empty_frame")

    lm_raw = face.get("landmarks") or []
    if len(lm_raw) < 5:
        raise AlignmentError("landmarks_missing", f"got={len(lm_raw)}")

    try:
        x = int(round(float(face["x"])))
        y = int(round(float(face["y"])))
        w = int(round(float(face["w"])))
        h = int(round(float(face["h"])))
    except (KeyError, TypeError, ValueError) as e:
        raise AlignmentError("bbox_invalid", str(e)) from e

    if w <= 0 or h <= 0:
        raise AlignmentError("bbox_non_positive", f"w={w} h={h}")

    bbox = (x, y, w, h)
    landmarks = np.asarray(lm_raw[:5], dtype=np.float32).reshape(5, 2)
    if landmarks.shape != (5, 2) or not np.isfinite(landmarks).all():
        raise AlignmentError("landmarks_invalid", f"shape={landmarks.shape}")

    crop = crop_aligned_face(frame, bbox, landmarks, output_size=(112, 112))
    if crop is None or getattr(crop, "size", 0) == 0:
        raise AlignmentError("crop_aligned_face_empty")

    ch, cw = int(crop.shape[0]), int(crop.shape[1])
    meta: dict[str, Any] = {
        "alignment_mode": ALIGNMENT_MODE_PRODUCT,
        "bbox": [x, y, w, h],
        "landmarks_ok": True,
        "output_h": ch,
        "output_w": cw,
        "output_size_requested": [112, 112],
    }
    # Produto com output_size=(112,112) deve entregar 112x112 (warp ou resize interno).
    if (ch, cw) != (112, 112):
        raise AlignmentError(
            "unexpected_output_size",
            f"got={cw}x{ch} expected=112x112 — captura inválida para fidelidade",
        )
    return crop, meta


_embedder = None


def get_facenet_embedder():
    global _embedder
    if _embedder is not None:
        return _embedder
    from app.vision.embedder import FaceNetEmbedder

    _embedder = FaceNetEmbedder()
    return _embedder


def embed_crop(crop: np.ndarray) -> np.ndarray:
    emb = get_facenet_embedder()
    vec = emb.embed(crop)
    v = np.asarray(vec, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v) + 1e-12)
    return v / n


def match_gallery(
    query: np.ndarray,
    gallery: list[tuple[str, np.ndarray]],
    threshold: float,
    margin: float,
) -> dict[str, Any]:
    if not gallery:
        return {"top1_id": None, "top1_score": None, "margin": None, "decision": "UNKNOWN", "reason": "empty_gallery"}
    scores = [(sid, float(np.dot(query, vec))) for sid, vec in gallery]
    scores.sort(key=lambda x: x[1], reverse=True)
    top1_id, top1_score = scores[0]
    competitor = next((sc for sid, sc in scores[1:] if sid != top1_id), None)
    marg = None if competitor is None else top1_score - competitor
    ok = top1_score >= threshold and (marg is None or marg >= margin)
    return {
        "top1_id": top1_id,
        "top1_score": round(top1_score, 6),
        "margin": None if marg is None else round(marg, 6),
        "decision": top1_id if ok else "UNKNOWN",
        "raw": "ID" if ok else "UNKNOWN",
    }


def load_gallery_facenet(gallery_dir: Path | None = None) -> list[tuple[str, np.ndarray]]:
    gallery_dir = gallery_dir or GALLERY_ACTIVE
    items: list[tuple[str, np.ndarray]] = []
    if not gallery_dir.is_dir():
        return items
    for person in sorted(gallery_dir.iterdir()):
        if not person.is_dir():
            continue
        for f in sorted(person.glob("*.npy")):
            v = np.load(f).astype(np.float32).reshape(-1)
            n = float(np.linalg.norm(v) + 1e-12)
            items.append((person.name, v / n))
    return items
