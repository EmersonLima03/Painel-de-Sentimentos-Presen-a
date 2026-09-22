"""Enrollment facial F3 — multi-sessão, reusa poc_common (sem alterar produto).

Pipeline por frame:
  YuNet → multi-rosto gate → select_primary → aligned_crop (produto) →
  quality → yaw/pose → hold → embed → TEMP gallery da campanha
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from poc_common import (
    ALIGNMENT_MODE_PRODUCT,
    CROPS_ACTIVE,
    GALLERY_ACTIVE,
    RESULTS,
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    embed_crop,
    estimate_face_yaw,
    pose_for_phase,
    quality_of_crop,
    select_primary_face,
)

# Galeria isolada por campanha (não mistura com lab facenet_aligned_v2)
CAMPAIGN_GALLERY = RESULTS / "gallery_temp" / "enrollment_campaigns"
CAMPAIGN_CROPS = RESULTS / "crops_enrollment"

PHASES_CORE = ("front", "lateral_right", "lateral_left", "validate")
PHASE_GLASSES = "glasses_habitual"

HUMAN_PHASE = {
    "front": ("1 de 4", "Olhe para a câmera", "Posicione seu rosto dentro da área indicada."),
    "lateral_right": ("2 de 4", "Vire o rosto lentamente para a direita", "Siga a seta e segure quando indicado."),
    "lateral_left": ("3 de 4", "Vire o rosto lentamente para a esquerda", "Siga a seta e segure quando indicado."),
    "validate": ("4 de 4", "Agora olhe novamente para a câmera", "Vamos confirmar seu cadastro."),
    "glasses_habitual": (
        "Extra",
        "Coloque seus óculos como você normalmente usa",
        "Vamos fazer uma captura adicional para ajudar no reconhecimento.",
    ),
}

# Validate must be similar to front template (cosine on L2-normalized FaceNet)
VALIDATE_MIN_SIM = 0.50


@dataclass
class CaptureSession:
    session_id: str
    campaign_id: str
    roster_student_id: str
    display_name: str
    class_label: str
    min_quality: float = 0.55
    stable_needed: int = 12  # mobile frame rate ~8–12 fps → ~1 s
    phase: str = "front"
    stable: int = 0
    turn_unlocked: bool = False
    validate_unlocked: bool = False
    status_human: str = "Posicione o rosto"
    ui_code: str = "waiting"  # waiting|no_face|multi_face|adjust|pose|alignment|holding|captured|done_phase
    pose_guide: str = "center"
    samples: list[dict[str, Any]] = field(default_factory=list)
    embeddings: dict[str, np.ndarray] = field(default_factory=dict)
    glasses_asked: bool = False
    glasses_wanted: Optional[bool] = None
    completed: bool = False
    last_face: Optional[dict] = None
    capture_flash: bool = False
    created_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def gallery_dir(self) -> Path:
        return CAMPAIGN_GALLERY / self.campaign_id / self.roster_student_id

    def crops_dir(self) -> Path:
        return CAMPAIGN_CROPS / self.campaign_id / self.roster_student_id

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self.stable = 0
        self.capture_flash = False
        if phase in ("lateral_right", "lateral_left", "validate"):
            self.turn_unlocked = False
        if phase == "validate":
            self.validate_unlocked = False
        if phase in ("front", "validate", "glasses_habitual"):
            self.pose_guide = "center"
        elif phase == "lateral_right":
            self.pose_guide = "right"
        elif phase == "lateral_left":
            self.pose_guide = "left"
        else:
            self.pose_guide = "none"
        title = HUMAN_PHASE.get(phase)
        if title:
            self.status_human = title[1]

    def ui_safe(self) -> dict[str, Any]:
        info = HUMAN_PHASE.get(self.phase, ("", "", ""))
        step_i = {
            "front": 1,
            "lateral_right": 2,
            "lateral_left": 3,
            "validate": 4,
            "glasses_habitual": 4,
            "glasses_ask": 4,
            "completed": 4,
        }.get(self.phase, 0)
        return {
            "phase": self.phase,
            "step_label": info[0],
            "title": info[1],
            "subtitle": info[2],
            "step_index": step_i,
            "step_total": 4,
            "status_human": self.status_human,
            "ui_code": self.ui_code,
            "pose_guide": self.pose_guide,
            "stable_pct": int(100 * min(1.0, self.stable / max(1, self.stable_needed))),
            "capture_flash": self.capture_flash,
            "samples_count": len(self.samples),
            "sample_steps": [s["step"] for s in self.samples],
            "glasses_asked": self.glasses_asked,
            "glasses_wanted": self.glasses_wanted,
            "completed": self.completed,
            "display_name": self.display_name,
            "class_label": self.class_label,
            # Explicitly NO scores / thresholds / embeddings
            "camera_enabled": True,
        }


class CaptureSessionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_session: dict[str, CaptureSession] = {}

    def create(
        self,
        *,
        session_id: str,
        campaign_id: str,
        roster_student_id: str,
        display_name: str,
        class_label: str,
    ) -> CaptureSession:
        with self._lock:
            cs = CaptureSession(
                session_id=session_id,
                campaign_id=campaign_id,
                roster_student_id=roster_student_id,
                display_name=display_name,
                class_label=class_label,
            )
            cs.set_phase("front")
            cs.ui_code = "waiting"
            self._by_session[session_id] = cs
            return cs

    def get(self, session_id: str) -> Optional[CaptureSession]:
        with self._lock:
            return self._by_session.get(session_id)

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._by_session.pop(session_id, None)


CAPTURE_STORE = CaptureSessionStore()


def _count_strong_faces(faces: list[dict]) -> int:
    return sum(1 for f in faces if float(f.get("face_score") or f.get("det_score") or 0) >= 0.55)


def _save_template(cs: CaptureSession, step: str, crop: np.ndarray, face: dict, q: float, lab: str, align_meta: dict, yaw: Optional[float]) -> np.ndarray:
    import cv2

    if align_meta.get("alignment_mode") != ALIGNMENT_MODE_PRODUCT:
        raise AlignmentError("not_product_alignment", f"got={align_meta.get('alignment_mode')}")
    gdir = cs.gallery_dir()
    cdir = cs.crops_dir()
    gdir.mkdir(parents=True, exist_ok=True)
    cdir.mkdir(parents=True, exist_ok=True)
    emb = embed_crop(crop)
    np.save(gdir / f"{step}.npy", emb)
    cv2.imwrite(str(cdir / f"{step}.jpg"), crop)
    sample = {
        "step": step,
        "quality": round(float(q), 4),
        "quality_label": lab,
        "yaw": None if yaw is None else round(float(yaw), 4),
        "alignment_mode": ALIGNMENT_MODE_PRODUCT,
        "npy": str(gdir / f"{step}.npy"),
        "crop": str(cdir / f"{step}.jpg"),
        "ts": datetime.now(timezone.utc).isoformat(),
        "product_db_written": False,
    }
    cs.samples.append(sample)
    cs.embeddings[step] = emb
    _persist_meta(cs)
    return emb


def _persist_meta(cs: CaptureSession) -> None:
    gdir = cs.gallery_dir()
    gdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "campaign_id": cs.campaign_id,
        "roster_student_id": cs.roster_student_id,
        "display_name": cs.display_name,
        "class_label": cs.class_label,
        "gallery_version": "enrollment_campaigns",
        "alignment_mode": ALIGNMENT_MODE_PRODUCT,
        "samples": cs.samples,
        "n_captures": len(cs.samples),
        "product_db_written": False,
        "reload_matcher_called": False,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    (gdir / "enroll_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _validate_consistency(cs: CaptureSession, emb: np.ndarray) -> tuple[bool, str]:
    front = cs.embeddings.get("front")
    if front is None:
        return False, "Template frontal ausente — reinicie o cadastro"
    sim = float(np.dot(front, emb))
    if sim < VALIDATE_MIN_SIM:
        return False, "Não conseguimos confirmar. Olhe de frente e tente de novo."
    return True, ""


def process_frame_bgr(cs: CaptureSession, frame: np.ndarray) -> dict[str, Any]:
    """Processa 1 frame BGR. Retorna ui_safe (+ flags internas mínimas)."""
    with cs.lock:
        if cs.completed:
            cs.ui_code = "completed"
            return cs.ui_safe()
        if cs.phase == "glasses_ask":
            cs.ui_code = "glasses_ask"
            return cs.ui_safe()
        if cs.phase not in PHASES_CORE and cs.phase != PHASE_GLASSES:
            return cs.ui_safe()

        phase = cs.phase
        h, w = frame.shape[:2]
        try:
            faces = detect_faces_yunet(frame, score_th=0.72)
        except FileNotFoundError:
            cs.ui_code = "adjust"
            cs.status_human = (
                "Modelo de detecção facial ausente neste Edge. "
                "Copie face_detection_yunet_2023mar.onnx para data/opencv_models/."
            )
            cs.stable = 0
            return cs.ui_safe()
        except Exception:
            cs.ui_code = "adjust"
            cs.status_human = "Não foi possível analisar a imagem. Tente de novo."
            cs.stable = 0
            return cs.ui_safe()

        n_strong = _count_strong_faces(faces)
        if n_strong > 1:
            cs.ui_code = "multi_face"
            cs.status_human = "Detectamos mais de uma pessoa. Fique sozinho diante da câmera para continuar."
            cs.stable = 0
            cs.pose_guide = HUMAN_PHASE.get(phase, ("", "", ""))[0] and cs.pose_guide
            return cs.ui_safe()

        face = select_primary_face(
            faces, min_face_score=0.55, frame_shape=(h, w), prev=cs.last_face
        )
        if face is None:
            cs.ui_code = "no_face"
            cs.status_human = "Posicione seu rosto dentro da área indicada."
            cs.stable = 0
            return cs.ui_safe()

        cs.last_face = {
            k: face[k] for k in ("x", "y", "w", "h", "face_score", "det_score") if k in face
        }

        try:
            crop, align_meta = aligned_crop(frame, face)
        except AlignmentError:
            cs.ui_code = "alignment"
            cs.status_human = "Ajuste a posição do rosto e tente novamente."
            cs.stable = 0
            return cs.ui_safe()

        lab, q = quality_of_crop(crop)
        yaw = estimate_face_yaw(face.get("landmarks") or [])
        pose = pose_for_phase(
            "front" if phase == PHASE_GLASSES else phase,
            yaw,
        )

        # Unlock transitions (same rules as ui_server lab)
        if phase == "lateral_right" and not cs.turn_unlocked:
            if yaw is not None and abs(float(yaw)) >= 0.22:
                cs.turn_unlocked = True
                cs.status_human = "Detectei a virada — continue até ~45°"
            else:
                cs.ui_code = "pose"
                cs.status_human = "Vire o rosto lentamente para a direita"
                cs.stable = 0
                return cs.ui_safe()

        if phase == "lateral_left" and not cs.turn_unlocked:
            if yaw is not None and float(yaw) <= -0.22:
                cs.turn_unlocked = True
                cs.status_human = "Detectei a virada à esquerda — continue"
            elif yaw is not None and abs(float(yaw)) <= 0.20:
                cs.ui_code = "pose"
                cs.status_human = "Bom. Agora vire para a esquerda"
                cs.stable = 0
                return cs.ui_safe()
            else:
                cs.ui_code = "pose"
                cs.status_human = "Volte um pouco ao centro e depois vire à esquerda"
                cs.stable = 0
                return cs.ui_safe()

        if phase == "validate" and not cs.validate_unlocked:
            if yaw is not None and abs(float(yaw)) <= 0.22:
                cs.validate_unlocked = True
            else:
                cs.ui_code = "pose"
                cs.status_human = "Agora olhe novamente para a câmera"
                cs.stable = 0
                return cs.ui_safe()

        quality_ok = q >= cs.min_quality and lab != "poor"
        if not quality_ok:
            cs.ui_code = "adjust"
            cs.status_human = "Aproxime-se e melhore a iluminação"
            cs.stable = 0
            return cs.ui_safe()

        if phase != PHASE_GLASSES and not pose["ok"]:
            cs.ui_code = "pose"
            cs.status_human = str(pose["hint"])
            cs.stable = 0
            return cs.ui_safe()

        if phase == PHASE_GLASSES and not pose["ok"]:
            # glasses: require frontal-ish
            cs.ui_code = "pose"
            cs.status_human = "Olhe de frente com os óculos"
            cs.stable = 0
            return cs.ui_safe()

        if align_meta.get("alignment_mode") != ALIGNMENT_MODE_PRODUCT:
            cs.ui_code = "alignment"
            cs.status_human = "Ajuste a posição do rosto e tente novamente."
            cs.stable = 0
            return cs.ui_safe()

        cs.ui_code = "holding"
        cs.stable += 1
        cs.status_human = f"Mantenha assim… ({cs.stable}/{cs.stable_needed})"
        if cs.stable < cs.stable_needed:
            return cs.ui_safe()

        # Capture
        try:
            emb = _save_template(cs, phase, crop, face, q, lab, align_meta, yaw)
        except Exception:
            cs.ui_code = "adjust"
            cs.status_human = "Falha na captura. Tente novamente."
            cs.stable = 0
            return cs.ui_safe()

        if phase == "validate":
            ok, msg = _validate_consistency(cs, emb)
            if not ok:
                # remove bad validate sample
                cs.samples = [s for s in cs.samples if s["step"] != "validate"]
                cs.embeddings.pop("validate", None)
                npy = cs.gallery_dir() / "validate.npy"
                if npy.exists():
                    npy.unlink()
                cs.ui_code = "pose"
                cs.status_human = msg
                cs.stable = 0
                cs.validate_unlocked = False
                return cs.ui_safe()

        cs.capture_flash = True
        cs.ui_code = "captured"
        cs.stable = 0

        if phase == "front":
            cs.set_phase("lateral_right")
            cs.status_human = HUMAN_PHASE["lateral_right"][1]
        elif phase == "lateral_right":
            cs.set_phase("lateral_left")
            cs.status_human = HUMAN_PHASE["lateral_left"][1]
        elif phase == "lateral_left":
            cs.set_phase("validate")
            cs.status_human = HUMAN_PHASE["validate"][1]
        elif phase == "validate":
            cs.phase = "glasses_ask"
            cs.glasses_asked = True
            cs.ui_code = "glasses_ask"
            cs.status_human = "Você costuma usar óculos durante as aulas?"
            cs.pose_guide = "none"
        elif phase == PHASE_GLASSES:
            cs.phase = "completed"
            cs.completed = True
            cs.ui_code = "completed"
            cs.status_human = "Cadastro concluído"
            cs.pose_guide = "none"

        return cs.ui_safe()


def ack_glasses(cs: CaptureSession, uses_glasses: bool) -> dict[str, Any]:
    with cs.lock:
        if cs.phase != "glasses_ask":
            return cs.ui_safe()
        cs.glasses_wanted = bool(uses_glasses)
        if uses_glasses:
            cs.set_phase(PHASE_GLASSES)
            cs.ui_code = "waiting"
            cs.status_human = HUMAN_PHASE[PHASE_GLASSES][1]
        else:
            cs.phase = "completed"
            cs.completed = True
            cs.ui_code = "completed"
            cs.status_human = "Cadastro concluído"
            cs.pose_guide = "none"
        return cs.ui_safe()


def decode_jpeg_bytes(data: bytes) -> np.ndarray:
    import cv2

    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("jpeg invalido")
    return frame


def force_advance_for_tests(cs: CaptureSession, step: str) -> dict[str, Any]:
    """Hook de teste: grava embedding sintético L2 e avança fase (sem camera)."""
    with cs.lock:
        rng = np.random.default_rng(abs(hash(cs.roster_student_id + step)) % (2**32))
        emb = rng.normal(size=512).astype(np.float32)
        emb /= max(1e-9, float(np.linalg.norm(emb)))
        # For validate, copy front so consistency passes
        if step == "validate" and "front" in cs.embeddings:
            emb = cs.embeddings["front"].copy()
            emb = emb + rng.normal(scale=0.01, size=512).astype(np.float32)
            emb /= max(1e-9, float(np.linalg.norm(emb)))
        gdir = cs.gallery_dir()
        cdir = cs.crops_dir()
        gdir.mkdir(parents=True, exist_ok=True)
        cdir.mkdir(parents=True, exist_ok=True)
        np.save(gdir / f"{step}.npy", emb)
        # tiny placeholder crop
        import cv2

        crop = np.zeros((112, 112, 3), dtype=np.uint8)
        crop[:] = (40, 80, 60)
        cv2.imwrite(str(cdir / f"{step}.jpg"), crop)
        cs.embeddings[step] = emb
        cs.samples.append(
            {
                "step": step,
                "quality": 0.9,
                "quality_label": "good",
                "yaw": 0.0,
                "alignment_mode": ALIGNMENT_MODE_PRODUCT,
                "npy": str(gdir / f"{step}.npy"),
                "test_hook": True,
                "product_db_written": False,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        _persist_meta(cs)
        cs.capture_flash = True
        if step == "front":
            cs.set_phase("lateral_right")
        elif step == "lateral_right":
            cs.set_phase("lateral_left")
        elif step == "lateral_left":
            cs.set_phase("validate")
        elif step == "validate":
            cs.phase = "glasses_ask"
            cs.glasses_asked = True
            cs.ui_code = "glasses_ask"
            cs.status_human = "Você costuma usar óculos durante as aulas?"
        elif step == PHASE_GLASSES:
            cs.phase = "completed"
            cs.completed = True
            cs.ui_code = "completed"
        return cs.ui_safe()
