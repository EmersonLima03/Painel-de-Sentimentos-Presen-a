"""IdentityBinding — não depende só de IoU; nunca escreve presença."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.vision.tracking_types import FaceTrack, IdentityBindingResult, PersonTrack


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
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


def _face_center_inside_person(face: Tuple, person: Tuple) -> bool:
    fx, fy, fw, fh = face[:4]
    px, py, pw, ph = person[:4]
    cx, cy = fx + fw / 2.0, fy + fh / 2.0
    return px <= cx <= px + pw and py <= cy <= py + ph


class IdentityBindingEngine:
    """
    Liga person_track ↔ face_track ↔ student_id.
    Usa IoU + contenção + histórico temporal + confiança de identidade.
    NÃO cria/altera attendance_checkin.
    """

    def __init__(self, history_bonus: float = 0.15):
        self.history_bonus = history_bonus
        self._pair_history: Dict[Tuple[str, str], int] = {}

    def bind(
        self,
        person_tracks: List[PersonTrack],
        face_tracks: List[FaceTrack],
        *,
        face_identities: Optional[Dict[str, Tuple[Optional[str], float]]] = None,
    ) -> List[IdentityBindingResult]:
        face_identities = face_identities or {}
        results: List[IdentityBindingResult] = []
        used_faces = set()

        for person in person_tracks:
            best_face: Optional[FaceTrack] = None
            best_score = 0.0
            best_reasons: List[str] = []

            for face in face_tracks:
                if face.track_id in used_faces:
                    continue
                reasons: List[str] = []
                score = 0.0

                iou = _iou(person.bounding_box, face.face_bbox)
                score += 0.35 * iou
                if iou > 0.05:
                    reasons.append(f"iou={iou:.2f}")

                if _face_center_inside_person(face.face_bbox, person.bounding_box):
                    score += 0.35
                    reasons.append("face_center_in_person")

                # Qualidade / oclusão
                q = min(person.observation_quality, face.observation_quality)
                score += 0.15 * q
                if person.occlusion_level > 0.6 or face.occlusion_level > 0.6:
                    score -= 0.2
                    reasons.append("occlusion_penalty")

                hist_key = (person.track_id, face.track_id)
                hist = self._pair_history.get(hist_key, 0)
                if hist > 0:
                    score += min(self.history_bonus, 0.05 * hist)
                    reasons.append(f"temporal_pair_count={hist}")

                if score > best_score:
                    best_score = score
                    best_face = face
                    best_reasons = reasons

            student_id = None
            id_conf = 0.0
            if best_face is not None and best_score >= 0.35:
                used_faces.add(best_face.track_id)
                self._pair_history[(person.track_id, best_face.track_id)] = (
                    self._pair_history.get((person.track_id, best_face.track_id), 0) + 1
                )
                sid, conf = face_identities.get(best_face.track_id, (None, 0.0))
                student_id, id_conf = sid, conf
                if student_id:
                    best_reasons.append("identity_from_facenet_cache")
                results.append(
                    IdentityBindingResult(
                        person_track_id=person.track_id,
                        face_track_id=best_face.track_id,
                        student_id=student_id,
                        identity_confidence=id_conf,
                        binding_confidence=min(1.0, best_score),
                        reasons=best_reasons,
                    )
                )
            else:
                results.append(
                    IdentityBindingResult(
                        person_track_id=person.track_id,
                        face_track_id=None,
                        student_id=None,
                        identity_confidence=0.0,
                        binding_confidence=0.0,
                        reasons=["no_stable_face_binding"],
                    )
                )

        for face in face_tracks:
            if face.track_id in used_faces:
                continue
            sid, conf = face_identities.get(face.track_id, (None, 0.0))
            results.append(
                IdentityBindingResult(
                    person_track_id=None,
                    face_track_id=face.track_id,
                    student_id=sid,
                    identity_confidence=conf,
                    binding_confidence=0.2 if sid else 0.0,
                    reasons=["face_without_person"],
                )
            )
        return results
