"""Alinhamento facial via landmarks YuNet (5 pontos) antes do embedding."""

from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np

# Template ArcFace / InsightFace 112x112 (olhos, nariz, cantos da boca)
_ARCFACE_REF_112 = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def _landmarks_from_yunet_row(row: np.ndarray, x: int, y: int) -> np.ndarray:
    """YuNet: após bbox, 10 valores = 5 pontos (x,y) relativos ou absolutos."""
    if len(row) < 14:
        return np.zeros((5, 2), dtype=np.float32)
    pts = row[4:14].reshape(5, 2).astype(np.float32)
    # OpenCV YuNet retorna coordenadas absolutas na imagem
    if pts.max() <= 1.5:
        pts[:, 0] *= 1
    return pts


def rotate_align_by_eyes(
    image: np.ndarray,
    left_eye: np.ndarray,
    right_eye: np.ndarray,
) -> np.ndarray:
    """Rotaciona o frame para alinhar os olhos na horizontal."""
    h, w = image.shape[:2]
    dx = float(right_eye[0] - left_eye[0])
    dy = float(right_eye[1] - left_eye[1])
    angle = np.degrees(np.arctan2(dy, dx))
    center = (
        float((left_eye[0] + right_eye[0]) * 0.5),
        float((left_eye[1] + right_eye[1]) * 0.5),
    )
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(image, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def crop_aligned_face(
    frame: np.ndarray,
    bbox: Tuple[int, int, int, int],
    landmarks: np.ndarray,
    *,
    output_size: Tuple[int, int] = (112, 112),
    padding_ratio: float = 0.15,
) -> Optional[np.ndarray]:
    """
    Alinha pelo ângulo dos olhos e recorta ROI; opcional warp para template 112x112.
    """
    if frame is None or frame.size == 0:
        return None

    x, y, w, h = bbox
    fh, fw = frame.shape[:2]
    if w <= 0 or h <= 0:
        return None

    lm = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
    if lm.shape != (5, 2) or not np.isfinite(lm).all():
        y_end = min(fh, y + h)
        x_end = min(fw, x + w)
        return frame[y:y_end, x:x_end]

    left_eye = lm[0]
    right_eye = lm[1]
    rotated = rotate_align_by_eyes(frame, left_eye, right_eye)

    # Reaplicar bbox com padding após rotação (aproximação: expandir bbox original)
    pad_w = int(w * padding_ratio)
    pad_h = int(h * padding_ratio)
    x0 = max(0, x - pad_w)
    y0 = max(0, y - pad_h)
    x1 = min(fw, x + w + pad_w)
    y1 = min(fh, y + h + pad_h)
    crop = rotated[y0:y1, x0:x1]
    if crop.size == 0:
        return None

    if output_size and output_size != (0, 0):
        try:
            dst = _ARCFACE_REF_112 * (output_size[0] / 112.0)
            src = lm.copy()
            tform, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
            if tform is not None:
                warped = cv2.warpAffine(
                    frame,
                    tform,
                    output_size,
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE,
                )
                return warped
        except Exception:
            pass
        crop = cv2.resize(crop, output_size, interpolation=cv2.INTER_LINEAR)

    return crop


def parse_yunet_landmarks(row: np.ndarray) -> Tuple[Tuple[int, int, int, int], np.ndarray]:
    x, y, w, h = int(row[0]), int(row[1]), int(row[2]), int(row[3])
    lm = row[4:14].reshape(5, 2).astype(np.float32)
    return (x, y, w, h), lm
