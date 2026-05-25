"""Tracker simples por bbox (IoU/centro) para manter track_id por face por alguns segundos."""

import time
from typing import List, Tuple, Optional
from dataclasses import dataclass, field

from app.logging import get_logger

logger = get_logger(__name__)


def _iou(b1: Tuple[int, int, int, int], b2: Tuple[int, int, int, int]) -> float:
    """IoU entre dois bboxes (x, y, w, h)."""
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    xi1 = max(x1, x2)
    yi1 = max(y1, y2)
    xi2 = min(x1 + w1, x2 + w2)
    yi2 = min(y1 + h1, y2 + h2)
    if xi2 <= xi1 or yi2 <= yi1:
        return 0.0
    inter = (xi2 - xi1) * (yi2 - yi1)
    a1 = w1 * h1
    a2 = w2 * h2
    union = a1 + a2 - inter
    return inter / union if union > 0 else 0.0


def _center(b: Tuple[int, int, int, int]) -> Tuple[float, float]:
    x, y, w, h = b
    return (x + w / 2.0, y + h / 2.0)


def _center_dist_sq(b1: Tuple[int, int, int, int], b2: Tuple[int, int, int, int]) -> float:
    c1 = _center(b1)
    c2 = _center(b2)
    return (c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2


@dataclass
class Track:
    """Um track = uma face sendo seguida no tempo."""
    track_id: int
    last_bbox: Tuple[int, int, int, int]
    last_student_id: Optional[str] = None
    last_confidence: float = 0.0
    last_recognition_ts: float = 0.0
    last_seen_ts: float = field(default_factory=time.time)

    def update_bbox(self, bbox: Tuple[int, int, int, int], now: float) -> None:
        self.last_bbox = bbox
        self.last_seen_ts = now

    def update_recognition(self, student_id: Optional[str], confidence: float, now: float) -> None:
        self.last_student_id = student_id
        self.last_confidence = confidence
        self.last_recognition_ts = now
        self.last_seen_ts = now


class BboxTracker:
    """
    Associa bboxes de um frame a track_ids. TTL expira tracks não vistos.
    Usa IoU primeiro; fallback por distância de centro.
    """

    def __init__(self, ttl_seconds: float = 2.5, iou_threshold: float = 0.2, max_tracks: int = 50):
        self.ttl_seconds = ttl_seconds
        self.iou_threshold = iou_threshold
        self.max_tracks = max_tracks
        self._tracks: List[Track] = []
        self._next_id = 0

    def _next_track_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _expire_old(self, now: float) -> None:
        self._tracks = [t for t in self._tracks if (now - t.last_seen_ts) <= self.ttl_seconds]
        if len(self._tracks) > self.max_tracks:
            self._tracks.sort(key=lambda t: t.last_seen_ts)
            self._tracks = self._tracks[-self.max_tracks:]

    def update(
        self,
        bboxes: List[Tuple[int, int, int, int]],
        now: Optional[float] = None,
    ) -> List[Tuple[Tuple[int, int, int, int], int, Optional[Track]]]:
        """
        Dado lista de bboxes do frame atual, retorna (bbox, track_id, track) para cada bbox.
        track pode ser None se for track novo (sem reconhecimento prévio).
        """
        now = now or time.time()
        self._expire_old(now)

        result: List[Tuple[Tuple[int, int, int, int], int, Optional[Track]]] = []
        used_track_ids = set()

        # Para cada bbox do frame, achar o track com maior IoU (ou centro mais próximo)
        for bbox in bboxes:
            best_track: Optional[Track] = None
            best_score = -1.0  # IoU ou -dist_sq

            for t in self._tracks:
                if t.track_id in used_track_ids:
                    continue
                iou = _iou(bbox, t.last_bbox)
                if iou >= self.iou_threshold and iou > best_score:
                    best_score = iou
                    best_track = t

            if best_track is None:
                # Fallback: menor distância de centro (dentro de raio razoável)
                best_d_sq = float("inf")
                for t in self._tracks:
                    if t.track_id in used_track_ids:
                        continue
                    d_sq = _center_dist_sq(bbox, t.last_bbox)
                    bw, bh = bbox[2], bbox[3]
                    max_jump = max(80, int(max(bw, bh) * 1.2))
                    if d_sq < max_jump * max_jump and d_sq < best_d_sq:
                        best_d_sq = d_sq
                        best_track = t

            if best_track is not None:
                used_track_ids.add(best_track.track_id)
                best_track.update_bbox(bbox, now)
                result.append((bbox, best_track.track_id, best_track))
            else:
                # Novo track
                tid = self._next_track_id()
                new_track = Track(track_id=tid, last_bbox=bbox, last_seen_ts=now, last_recognition_ts=0.0)
                self._tracks.append(new_track)
                result.append((bbox, tid, new_track))

        return result
