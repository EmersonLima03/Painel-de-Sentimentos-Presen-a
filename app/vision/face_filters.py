"""Filtros pós-detecção para reduzir fantasmas (parede, gola, textura)."""

from __future__ import annotations

from typing import List, Tuple

BBox = Tuple[int, int, int, int]


def stabilize_face_detections(
    faces: List[BBox],
    frame_h: int,
    frame_w: int,
    *,
    min_face_size: int = 40,
    min_area_ratio: float = 0.0015,
    max_area_ratio: float = 0.35,
    aspect_min: float = 0.68,
    aspect_max: float = 1.32,
    single_subject_mode: bool = False,
    largest_face_min_fraction: float = 0.28,
    relative_min_fraction: float = 0.0,
    max_faces: int = 12,
) -> List[BBox]:
    """
    Remove caixas irreais e, em modo 1 pessoa, descarta detecções muito menores que o maior rosto.
    """
    if not faces or frame_h < 2 or frame_w < 2:
        return []

    frame_area = float(frame_h * frame_w)
    filtered: List[Tuple[float, BBox]] = []

    for (x, y, w, h) in faces:
        if w <= 0 or h <= 0:
            continue
        if min(w, h) < min_face_size:
            continue
        aspect = w / float(h)
        if aspect < aspect_min or aspect > aspect_max:
            continue
        area = float(w * h)
        area_ratio = area / frame_area
        if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
            continue
        filtered.append((area, (x, y, w, h)))

    if not filtered:
        return []

    filtered.sort(key=lambda t: t[0], reverse=True)

    if single_subject_mode and len(filtered) > 1:
        largest_area = filtered[0][0]
        min_area = largest_area * largest_face_min_fraction
        filtered = [(a, b) for a, b in filtered if a >= min_area]

    return [b for _, b in filtered[:max_faces]]
