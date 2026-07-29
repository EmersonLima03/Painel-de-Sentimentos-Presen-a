"""
Pose corporal via MediaPipe Pose Landmarker (IMAGE mode).

Smoothing temporal fica no RealtimeAnalyticsEngine (por person_track_id).
Não usar VIDEO mode nesta versão.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)

_pose = None
_pose_lock = threading.Lock()
_pose_error: Optional[str] = None

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)

# MediaPipe Pose landmark indices
_NOSE = 0
_LEFT_SHOULDER = 11
_RIGHT_SHOULDER = 12
_LEFT_ELBOW = 13
_RIGHT_ELBOW = 14
_LEFT_WRIST = 15
_RIGHT_WRIST = 16
_LEFT_HIP = 23
_RIGHT_HIP = 24


@dataclass
class BodyPoseResult:
    status: str  # available | inconclusive | unavailable | error
    provider: str = "mediapipe_pose"
    landmarks: Dict[str, Any] = field(default_factory=dict)
    head_state: str = "pose_inconclusive"
    head_confidence: float = 0.0
    hands: Dict[str, Any] = field(default_factory=dict)
    face_occlusion: Dict[str, Any] = field(default_factory=dict)
    torso_orientation: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    inference_ms: float = 0.0

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "provider": self.provider,
            "landmarks": self.landmarks,
            "head_state": self.head_state,
            "head_confidence": round(self.head_confidence, 3),
            "hands": self.hands,
            "face_occlusion": self.face_occlusion,
            "torso_orientation": None
            if self.torso_orientation is None
            else round(self.torso_orientation, 3),
            "reasons": list(self.reasons),
            "inference_ms": round(self.inference_ms, 2),
        }


def pose_landmarker_health() -> dict:
    p = _get_pose_landmarker(create=False)
    if p is not None:
        return {"status": "available", "provider": "mediapipe_tasks", "reason": None}
    p2 = _get_pose_landmarker(create=True)
    if p2 is not None:
        return {"status": "available", "provider": "mediapipe_tasks", "reason": None}
    return {
        "status": "unavailable",
        "provider": "mediapipe_tasks",
        "reason": _pose_error or "not_initialized",
    }


def _model_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    cache = root / "data" / "mediapipe_models"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / "pose_landmarker_lite.task"


def _ensure_model() -> Path:
    path = _model_path()
    if path.is_file() and path.stat().st_size > 100_000:
        return path
    import urllib.request

    logger.info("pose_landmarker_downloading", url=_MODEL_URL, path=str(path))
    urllib.request.urlretrieve(_MODEL_URL, path)
    if not path.is_file() or path.stat().st_size < 100_000:
        raise RuntimeError("pose_landmarker_lite.task download failed")
    return path


def _get_pose_landmarker(*, create: bool = True):
    global _pose, _pose_error
    with _pose_lock:
        if _pose is not None:
            return _pose
        if not create:
            return None
        try:
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core import base_options as mp_base_options

            model_path = str(_ensure_model())
            opts = vision.PoseLandmarkerOptions(
                base_options=mp_base_options.BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.45,
                min_pose_presence_confidence=0.45,
                min_tracking_confidence=0.45,
            )
            _pose = vision.PoseLandmarker.create_from_options(opts)
            _pose_error = None
            logger.info("pose_landmarker_ready", model=model_path)
            return _pose
        except Exception as e:
            _pose = None
            _pose_error = f"{type(e).__name__}:{e}"
            logger.warning("pose_landmarker_init_failed", error=_pose_error)
            return None


def _lm_xy(lms, idx: int, w: int, h: int, min_vis: float = 0.4) -> Optional[Tuple[float, float, float]]:
    if idx >= len(lms):
        return None
    p = lms[idx]
    vis = float(getattr(p, "visibility", 1.0) or 0.0)
    if vis < min_vis:
        return None
    return float(p.x) * w, float(p.y) * h, vis


def estimate_body_pose(
    frame: np.ndarray,
    person_bbox: Tuple[float, float, float, float],
    *,
    face_bbox: Optional[Tuple[float, float, float, float]] = None,
    head_down_since: Optional[float] = None,
    hand_near_since: Optional[float] = None,
    now: Optional[float] = None,
    min_keypoint_confidence: float = 0.4,
    wrist_near_face_max_ratio: float = 0.65,
    occlusion_persistent_seconds: float = 5.0,
) -> BodyPoseResult:
    """
    IMAGE mode no ROI corporal (coords convertidas ao frame).
    """
    import time

    t0 = time.perf_counter()
    now = now if now is not None else time.time()
    health = pose_landmarker_health()
    if health.get("status") != "available":
        return BodyPoseResult(
            status="unavailable",
            reasons=[health.get("reason") or "pose_unavailable"],
            inference_ms=(time.perf_counter() - t0) * 1000,
        )

    ih, iw = frame.shape[:2]
    px, py, pw, ph = [float(v) for v in person_bbox[:4]]
    # pad ROI
    pad_x, pad_y = pw * 0.08, ph * 0.08
    x1 = max(0, int(px - pad_x))
    y1 = max(0, int(py - pad_y))
    x2 = min(iw, int(px + pw + pad_x))
    y2 = min(ih, int(py + ph + pad_y))
    if x2 - x1 < 32 or y2 - y1 < 32:
        return BodyPoseResult(
            status="inconclusive",
            reasons=["person_roi_too_small"],
            inference_ms=(time.perf_counter() - t0) * 1000,
        )

    crop = frame[y1:y2, x1:x2]
    landmarker = _get_pose_landmarker(create=True)
    if landmarker is None:
        return BodyPoseResult(
            status="unavailable",
            reasons=[_pose_error or "pose_init_failed"],
            inference_ms=(time.perf_counter() - t0) * 1000,
        )

    try:
        import mediapipe as mp

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)
    except Exception as e:
        return BodyPoseResult(
            status="error",
            reasons=[str(e)],
            inference_ms=(time.perf_counter() - t0) * 1000,
        )

    if not result.pose_landmarks:
        return BodyPoseResult(
            status="inconclusive",
            reasons=["no_pose_landmarks"],
            inference_ms=(time.perf_counter() - t0) * 1000,
        )

    lms = result.pose_landmarks[0]
    ch, cw = crop.shape[:2]

    def abs_pt(idx: int):
        p = _lm_xy(lms, idx, cw, ch, min_vis=min_keypoint_confidence)
        if p is None:
            return None
        return p[0] + x1, p[1] + y1, p[2]

    nose = abs_pt(_NOSE)
    ls = abs_pt(_LEFT_SHOULDER)
    rs = abs_pt(_RIGHT_SHOULDER)
    lw = abs_pt(_LEFT_WRIST)
    rw = abs_pt(_RIGHT_WRIST)
    lh = abs_pt(_LEFT_HIP)
    rh = abs_pt(_RIGHT_HIP)

    landmarks = {
        "nose": None if nose is None else {"x": nose[0], "y": nose[1], "v": nose[2]},
        "left_shoulder": None if ls is None else {"x": ls[0], "y": ls[1], "v": ls[2]},
        "right_shoulder": None if rs is None else {"x": rs[0], "y": rs[1], "v": rs[2]},
        "left_wrist": None if lw is None else {"x": lw[0], "y": lw[1], "v": lw[2]},
        "right_wrist": None if rw is None else {"x": rw[0], "y": rw[1], "v": rw[2]},
    }

    reasons: List[str] = []
    head_state = "pose_inconclusive"
    head_conf = 0.0
    torso_ori = None

    if ls and rs and nose:
        shoulder_cx = (ls[0] + rs[0]) / 2.0
        shoulder_cy = (ls[1] + rs[1]) / 2.0
        shoulder_w = max(1.0, abs(rs[0] - ls[0]))
        # distância nariz–centro ombros / largura ombros
        nose_to_shoulder = (nose[1] - shoulder_cy) / shoulder_w
        # inclinação eixo cabeça–pescoço (vetor nariz → ombros)
        dx = shoulder_cx - nose[0]
        dy = shoulder_cy - nose[1]
        angle = math.degrees(math.atan2(dx, max(1e-3, dy)))  # ~0 = vertical
        torso_ori = abs(angle)

        # cabeça baixa: webcam frontal — nariz não precisa ir muito abaixo dos ombros
        # (topo da cabeça visível quando olha para baixo). Critérios mais permissivos.
        head_down_geom = (
            nose[1] > shoulder_cy + 0.02 * shoulder_w and nose_to_shoulder > 0.05
        ) or (nose_to_shoulder > 0.22)
        # Inclinação do eixo cabeça–torso também conta como look-down
        head_pitch_proxy = dy > 0 and (nose[1] - shoulder_cy) > shoulder_w * 0.05
        if head_pitch_proxy and abs(dx) / shoulder_w < 0.45:
            head_down_geom = True
        head_turned = abs(nose[0] - shoulder_cx) / shoulder_w > 0.35

        # mão apoiando cabeça (punho perto da cabeça)
        head_supported = False
        face_ref = face_bbox or (nose[0] - shoulder_w * 0.35, nose[1] - shoulder_w * 0.5, shoulder_w * 0.7, shoulder_w * 0.7)
        for wrist in (lw, rw):
            if wrist is None:
                continue
            fcx = face_ref[0] + face_ref[2] / 2.0
            fcy = face_ref[1] + face_ref[3] / 2.0
            dist = math.hypot(wrist[0] - fcx, wrist[1] - fcy) / shoulder_w
            if dist < 0.55:
                head_supported = True

        if head_down_geom:
            # Mão perto da cabeça/rosto: não rotular como cabeça baixa —
            # prioridade oclusão (DMS: visibility/occlusion gates).
            if head_supported:
                head_state = "pose_inconclusive"
                head_conf = 0.35
                reasons.append("wrist_near_prefer_occlusion")
            else:
                dur = (now - head_down_since) if head_down_since else 0.0
                # short→persistent alinhado ao evento (≥8s); evita "prolongada" em 2.5s
                if dur >= 8.0:
                    head_state = "head_down_persistent"
                else:
                    head_state = "head_down_short"
                head_conf = min(0.95, 0.55 + abs(nose_to_shoulder) * 0.3)
                reasons.append(f"nose_shoulder_ratio={nose_to_shoulder:.2f}")
        elif head_turned:
            head_state = "head_turned"
            head_conf = 0.6
            reasons.append("lateral_nose_offset")
        else:
            head_state = "head_forward"
            head_conf = 0.7
            reasons.append("aligned_torso_head")
    else:
        reasons.append("insufficient_keypoints")

    # mãos: só punhos → near / possible occlusion (nunca cobertura forte)
    hands = {
        "left_wrist": landmarks.get("left_wrist"),
        "right_wrist": landmarks.get("right_wrist"),
        "state": "not_near_face",
        "visibility": 0.0,
    }
    face_occlusion = {
        "state": "none",
        "confidence": 0.0,
        "reasons": [],
        "note": "wrists_only_no_hand_landmarker",
    }

    near = False
    # Sem face_bbox (rosto coberto/perdido), usa proxy: nariz ou terço superior do corpo.
    # Sem isso a oclusão por punho NUNCA dispara exatamente quando mais importa.
    proxy_bbox = face_bbox
    if proxy_bbox is None and nose is not None and ls and rs:
        shoulder_w = max(1.0, abs(rs[0] - ls[0]))
        proxy_bbox = (
            nose[0] - shoulder_w * 0.4,
            nose[1] - shoulder_w * 0.55,
            shoulder_w * 0.8,
            shoulder_w * 0.85,
        )
    elif proxy_bbox is None and person_bbox is not None:
        px, py, pw, ph = person_bbox[:4]
        proxy_bbox = (px + pw * 0.2, py, pw * 0.6, ph * 0.35)

    if proxy_bbox and (lw or rw):
        fx, fy, fw, fh = proxy_bbox[:4]
        fcx = fx + fw / 2.0
        fcy = fy + fh / 2.0
        fdiag = max(1.0, (fw ** 2 + fh ** 2) ** 0.5)
        expand = (fx - fw * 0.15, fy - fh * 0.12, fw * 1.3, fh * 1.25)
        for wrist in (lw, rw):
            if wrist is None:
                continue
            if float(wrist[2]) < 0.40:
                continue
            wx, wy = wrist[0], wrist[1]
            d = math.hypot(wx - fcx, wy - fcy) / fdiag
            if d >= wrist_near_face_max_ratio:
                continue
            # Punho deve intersectar região facial expandida (não só distância ao centro).
            if not (
                expand[0] <= wx <= expand[0] + expand[2]
                and expand[1] <= wy <= expand[1] + expand[3]
            ):
                continue
            near = True
        hands["visibility"] = 0.6 if near else (0.3 if (lw or rw) else 0.0)
        if near:
            hands["state"] = "hand_near_face"
            dur_h = (now - hand_near_since) if hand_near_since else 0.0
            reason_suffix = "_proxy" if face_bbox is None else ""
            if dur_h >= occlusion_persistent_seconds:
                face_occlusion = {
                    "state": "persistent_possible_face_occlusion",
                    "confidence": 0.55 if face_bbox else 0.5,
                    "reasons": [f"wrist_near_face_persistent{reason_suffix}"],
                    "note": "wrists_only_no_hand_landmarker",
                    "duration_seconds": round(dur_h, 2),
                }
            else:
                face_occlusion = {
                    "state": "possible_face_occlusion_by_hand",
                    "confidence": 0.4 if face_bbox else 0.35,
                    "reasons": [f"wrist_near_face{reason_suffix}"],
                    "note": "wrists_only_no_hand_landmarker",
                    "duration_seconds": round(dur_h, 2),
                }
            hands["state"] = "hand_near_face"
            # Oclusão ativa: não emitir cabeça baixa no mesmo frame
            if head_state in ("head_down_short", "head_down_persistent", "head_supported"):
                head_state = "pose_inconclusive"
                head_conf = min(head_conf, 0.35)
                reasons.append("wrist_near_prefer_occlusion")

    pose_vis = 0.0
    visible_n = sum(1 for v in (nose, ls, rs, lw, rw) if v is not None)
    pose_vis = visible_n / 5.0

    return BodyPoseResult(
        status="available" if pose_vis >= 0.4 else "inconclusive",
        landmarks=landmarks,
        head_state=head_state,
        head_confidence=head_conf,
        hands=hands,
        face_occlusion=face_occlusion,
        torso_orientation=torso_ori,
        reasons=reasons + [f"pose_visibility={pose_vis:.2f}"],
        inference_ms=(time.perf_counter() - t0) * 1000,
    )
