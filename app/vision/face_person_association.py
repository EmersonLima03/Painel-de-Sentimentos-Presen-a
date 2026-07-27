"""Associação espacial face ↔ person track (antes da identidade)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.vision.tracking_types import FaceTrack, PersonTrack

BBox = Tuple[float, float, float, float]


def _center(b: BBox) -> Tuple[float, float]:
    return b[0] + b[2] / 2.0, b[1] + b[3] / 2.0


def _iou(a: BBox, b: BBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _face_center_inside(face: BBox, person: BBox) -> bool:
    cx, cy = _center(face)
    return person[0] <= cx <= person[0] + person[2] and person[1] <= cy <= person[1] + person[3]


def _face_in_upper_body(face: BBox, person: BBox) -> bool:
    """Face na metade superior do corpo."""
    cx, cy = _center(face)
    if not (person[0] <= cx <= person[0] + person[2]):
        return False
    upper_bottom = person[1] + person[3] * 0.55
    return person[1] - person[3] * 0.05 <= cy <= upper_bottom


def _head_region_distance(face: BBox, person: BBox) -> float:
    """Distância normalizada centro facial ↔ região da cabeça (topo do bbox)."""
    fcx, fcy = _center(face)
    hx = person[0] + person[2] / 2.0
    hy = person[1] + person[3] * 0.18
    diag = max(1.0, (person[2] ** 2 + person[3] ** 2) ** 0.5)
    return ((fcx - hx) ** 2 + (fcy - hy) ** 2) ** 0.5 / diag


@dataclass
class FacePersonAssociation:
    person_track_id: Optional[str]
    face_track_id: Optional[str]
    score: float
    method: str
    ambiguous: bool
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "person_track_id": self.person_track_id,
            "face_track_id": self.face_track_id,
            "score": round(self.score, 3),
            "method": self.method,
            "ambiguous": self.ambiguous,
            "reasons": list(self.reasons),
        }


class FacePersonAssociator:
    """
    Combina: center_inside + upper_body + head distance + history + ambiguidade.
    Não usa só IoU (face << corpo).
    """

    def __init__(self, *, history_bonus: float = 0.12, ambiguous_gap: float = 0.08):
        self.history_bonus = history_bonus
        self.ambiguous_gap = ambiguous_gap
        self._pair_history: Dict[Tuple[str, str], int] = {}
        self._last_face_for_person: Dict[str, str] = {}

    def associate(
        self,
        person_tracks: List[PersonTrack],
        face_tracks: List[FaceTrack],
    ) -> List[FacePersonAssociation]:
        results: List[FacePersonAssociation] = []
        used_faces: set = set()
        n_persons = len(person_tracks)

        for person in person_tracks:
            scored: List[Tuple[float, FaceTrack, List[str], str]] = []
            for face in face_tracks:
                score, reasons, method = self._score_pair(person, face, n_persons)
                scored.append((score, face, reasons, method))
            scored.sort(key=lambda x: x[0], reverse=True)

            if not scored or scored[0][0] < 0.35:
                results.append(
                    FacePersonAssociation(
                        person_track_id=person.track_id,
                        face_track_id=None,
                        score=0.0,
                        method="none",
                        ambiguous=False,
                        reasons=["no_face_candidate"],
                    )
                )
                continue

            best_score, best_face, best_reasons, best_method = scored[0]
            second = scored[1][0] if len(scored) > 1 else 0.0
            ambiguous = (best_score - second) < self.ambiguous_gap and second >= 0.30
            if n_persons >= 2 and best_score < 0.55:
                # pessoas próximas: exigir score mais alto
                if second > 0.25:
                    ambiguous = True
                    best_reasons = list(best_reasons) + ["multi_person_proximity_penalty"]

            if best_face.track_id in used_faces:
                results.append(
                    FacePersonAssociation(
                        person_track_id=person.track_id,
                        face_track_id=None,
                        score=best_score,
                        method=best_method,
                        ambiguous=True,
                        reasons=["face_already_assigned"],
                    )
                )
                continue

            if ambiguous:
                results.append(
                    FacePersonAssociation(
                        person_track_id=person.track_id,
                        face_track_id=best_face.track_id,
                        score=best_score,
                        method=best_method,
                        ambiguous=True,
                        reasons=best_reasons + ["ambiguous_association"],
                    )
                )
                # não marca used — associação ambígua não consome exclusividade forte
                continue

            used_faces.add(best_face.track_id)
            key = (person.track_id, best_face.track_id)
            self._pair_history[key] = self._pair_history.get(key, 0) + 1
            self._last_face_for_person[person.track_id] = best_face.track_id
            results.append(
                FacePersonAssociation(
                    person_track_id=person.track_id,
                    face_track_id=best_face.track_id,
                    score=best_score,
                    method=best_method,
                    ambiguous=False,
                    reasons=best_reasons,
                )
            )

        for face in face_tracks:
            if face.track_id in used_faces:
                continue
            if any(r.face_track_id == face.track_id for r in results):
                continue
            results.append(
                FacePersonAssociation(
                    person_track_id=None,
                    face_track_id=face.track_id,
                    score=0.0,
                    method="none",
                    ambiguous=False,
                    reasons=["face_without_person"],
                )
            )
        return results

    def _score_pair(
        self, person: PersonTrack, face: FaceTrack, n_persons: int
    ) -> Tuple[float, List[str], str]:
        reasons: List[str] = []
        score = 0.0
        methods: List[str] = []

        pb, fb = person.bounding_box, face.face_bbox
        if _face_center_inside(fb, pb):
            score += 0.40
            reasons.append("center_inside")
            methods.append("center_inside")
        if _face_in_upper_body(fb, pb):
            score += 0.25
            reasons.append("upper_body")
            methods.append("upper_body")

        head_d = _head_region_distance(fb, pb)
        if head_d < 0.25:
            score += 0.20 * (1.0 - head_d / 0.25)
            reasons.append(f"head_dist={head_d:.2f}")
            methods.append("head_region")

        iou = _iou(pb, fb)
        score += 0.10 * min(1.0, iou * 5.0)  # IoU contribui pouco
        if iou > 0.02:
            reasons.append(f"iou={iou:.2f}")

        hist = self._pair_history.get((person.track_id, face.track_id), 0)
        if hist > 0:
            score += min(self.history_bonus, 0.04 * hist)
            reasons.append(f"history={hist}")
            methods.append("history")
        elif self._last_face_for_person.get(person.track_id) == face.track_id:
            score += 0.08
            reasons.append("prev_link")
            methods.append("history")

        if n_persons >= 2:
            score -= 0.05  # leve penalização multi-pessoa

        method = "+".join(methods) if methods else "weak"
        return score, reasons, method
