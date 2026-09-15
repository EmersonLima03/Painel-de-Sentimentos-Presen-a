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
_LEFT_EAR = 7
_RIGHT_EAR = 8
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


def nose_in_profile_face(
    nose: Optional[Tuple[float, float, float]],
    face_bbox: Optional[Tuple[float, float, float, float]],
) -> bool:
    """I: nariz no terço esquerdo/direito da caixa YuNet (perfil 2D).

    De lado, o nariz continua 'no meio' dos ombros — o corte 0.35 falha.
    Nariz fora da caixa (ventilador FP) não conta.
    """
    if nose is None or face_bbox is None:
        return False
    fx, fy, fw, fh = (float(face_bbox[0]), float(face_bbox[1]), float(face_bbox[2]), float(face_bbox[3]))
    if fw < 12.0 or fh < 12.0:
        return False
    nx, ny = float(nose[0]), float(nose[1])
    if not (fx - 0.12 * fw <= nx <= fx + fw + 0.12 * fw):
        return False
    if not (fy - 0.18 * fh <= ny <= fy + fh + 0.18 * fh):
        return False
    rel = (nx - fx) / fw
    # Terço lateral (I). >0.78 costuma ser YuNet FP (cortina/headset) no H.
    return (rel <= 0.38 or rel >= 0.62) and (0.18 <= rel <= 0.78)


def nose_inside_face_bbox(
    nose: Optional[Tuple[float, float, float]],
    face_bbox: Optional[Tuple[float, float, float, float]],
) -> bool:
    """Nariz dentro da caixa YuNet (com folga). Cortina/ventilador sem nariz = False."""
    if nose is None or face_bbox is None:
        return False
    fx, fy, fw, fh = (float(face_bbox[0]), float(face_bbox[1]), float(face_bbox[2]), float(face_bbox[3]))
    if fw < 12.0 or fh < 12.0:
        return False
    nx, ny = float(nose[0]), float(nose[1])
    if not (fx - 0.12 * fw <= nx <= fx + fw + 0.12 * fw):
        return False
    if not (fy - 0.18 * fh <= ny <= fy + fh + 0.18 * fh):
        return False
    return True


def _face_crop_bgr(
    frame: Optional[np.ndarray],
    face_bbox: Optional[Tuple[float, float, float, float]],
) -> Optional[np.ndarray]:
    if frame is None or face_bbox is None or frame.size == 0:
        return None
    fx, fy, fw, fh = (int(face_bbox[0]), int(face_bbox[1]), int(face_bbox[2]), int(face_bbox[3]))
    if fw < 16 or fh < 16:
        return None
    ih, iw = frame.shape[:2]
    x1, y1 = max(0, fx), max(0, fy)
    x2, y2 = min(iw, fx + fw), min(ih, fy + fh)
    if x2 - x1 < 16 or y2 - y1 < 16:
        return None
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    return crop


def face_crop_skin_ratio(
    frame: Optional[np.ndarray],
    face_bbox: Optional[Tuple[float, float, float, float]],
) -> Optional[float]:
    """Fração de pixels tipo pele no crop YuNet. Cabelo/cortina fica baixo."""
    crop = _face_crop_bgr(frame, face_bbox)
    if crop is None:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    ycr = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
    m_hsv = cv2.inRange(hsv, (0, 40, 50), (25, 180, 255))
    m_ycr = cv2.inRange(ycr, (0, 133, 77), (255, 173, 127))
    return float(np.mean((m_hsv > 0) | (m_ycr > 0)))


def face_crop_dark_ratio(
    frame: Optional[np.ndarray],
    face_bbox: Optional[Tuple[float, float, float, float]],
) -> Optional[float]:
    """Fração de pixels escuros (HSV V). Cabelo no LIVE BGR; JPEG comprime e engana só a pele."""
    crop = _face_crop_bgr(frame, face_bbox)
    if crop is None:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return float(np.mean(hsv[:, :, 2] < 90))


def crown_look_down_face(
    frame: Optional[np.ndarray],
    nose: Optional[Tuple[float, float, float]],
    face_bbox: Optional[Tuple[float, float, float, float]],
    *,
    skin_max: float = 0.24,
) -> bool:
    """H: YuNet no topo da cabeça (cabelo). Rosto real tem pele alta — não entra."""
    if not nose_inside_face_bbox(nose, face_bbox):
        return False
    skin = face_crop_skin_ratio(frame, face_bbox)
    if skin is None:
        return False
    if skin < skin_max:
        return True
    # Pele alta (rosto real, mesmo com fone/cabelo na caixa) NÃO é topo da cabeça.
    return False


def unilateral_ear_profile(
    left_ear: Optional[Tuple[float, float, float]],
    right_ear: Optional[Tuple[float, float, float]],
) -> bool:
    """I: só uma orelha no pose (a outra some de lado). Ambos ausentes ≠ perfil (pode ser H)."""
    return (left_ear is None) != (right_ear is None)


def nose_ear_distance_profile(
    nose: Optional[Tuple[float, float, float]],
    left_ear: Optional[Tuple[float, float, float]],
    right_ear: Optional[Tuple[float, float, float]],
    shoulder_w: float,
) -> bool:
    """I / 3/4: uma orelha fica colada no nariz (a de trás projetada); a visível fica longe.

    De frente as duas distâncias são parecidas.
    """
    if nose is None or left_ear is None or right_ear is None:
        return False
    dl = math.hypot(float(nose[0]) - float(left_ear[0]), float(nose[1]) - float(left_ear[1]))
    dr = math.hypot(float(nose[0]) - float(right_ear[0]), float(nose[1]) - float(right_ear[1]))
    near, far = min(dl, dr), max(dl, dr)
    if far < 12.0:
        return False
    sw = max(1.0, float(shoulder_w))
    return (near / far) < 0.48 and (far / sw) > 0.18


def ears_stacked_profile(
    left_ear: Optional[Tuple[float, float, float]],
    right_ear: Optional[Tuple[float, float, float]],
    shoulder_w: float,
) -> bool:
    """I: orelhas quase na mesma X (perfil); de frente o vão é largo."""
    if left_ear is None or right_ear is None:
        return False
    sw = max(1.0, float(shoulder_w))
    return abs(float(left_ear[0]) - float(right_ear[0])) / sw < 0.14


def wrist_in_true_head_zone(
    wrist: Tuple[float, float, float],
    *,
    nose: Optional[Tuple[float, float, float]],
    left_shoulder: Optional[Tuple[float, float, float]],
    right_shoulder: Optional[Tuple[float, float, float]],
    face_bbox: Optional[Tuple[float, float, float, float]],
) -> bool:
    """J: punho na cabeça. I/E4: punho no ombro/peito não conta."""
    if float(wrist[2]) < 0.28:
        return False
    if not (left_shoulder and right_shoulder):
        return False
    ls, rs = left_shoulder, right_shoulder
    shoulder_cy = (ls[1] + rs[1]) / 2.0
    shoulder_w = max(1.0, abs(rs[0] - ls[0]))
    cx = (ls[0] + rs[0]) / 2.0
    y_max = shoulder_cy + 0.18 * shoulder_w
    if face_bbox is not None:
        y_max = min(y_max, float(face_bbox[1]) + float(face_bbox[3]) * 1.08)
    # Perfil: caixa do rosto fica alta e o punho no ombro entra no 1.08×. Exigir y de cabeça.
    if nose is not None:
        y_slack = 0.25 * shoulder_w
        # J: palma no rosto, punho no queixo (alinhado em X com o nariz). Sem caixa YuNet.
        if face_bbox is None and abs(float(wrist[0]) - float(nose[0])) / shoulder_w < 0.32:
            y_slack = 0.50 * shoulder_w
        y_max = min(y_max, float(nose[1]) + y_slack)
    if wrist[1] > y_max:
        return False
    if abs(wrist[0] - cx) / shoulder_w > 0.90:
        return False
    if face_bbox is not None:
        fx, _fy, fw, _fh = (
            float(face_bbox[0]),
            float(face_bbox[1]),
            float(face_bbox[2]),
            float(face_bbox[3]),
        )
        pad = 0.28 * fw
        if not (fx - pad <= wrist[0] <= fx + fw + pad):
            return False
    return True


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

    def abs_pt(idx: int, min_vis: Optional[float] = None):
        p = _lm_xy(
            lms,
            idx,
            cw,
            ch,
            min_vis=float(min_keypoint_confidence if min_vis is None else min_vis),
        )
        if p is None:
            return None
        return p[0] + x1, p[1] + y1, p[2]

    face_missing = face_bbox is None
    # Ângulo extremo (só topo da cabeça): nariz/olhos falham no limiar 0.4 — aceitar mais fraco.
    nose_min_vis = 0.22 if face_missing else min_keypoint_confidence
    nose = abs_pt(_NOSE, min_vis=nose_min_vis)
    ls = abs_pt(_LEFT_SHOULDER)
    rs = abs_pt(_RIGHT_SHOULDER)
    lw = abs_pt(_LEFT_WRIST)
    rw = abs_pt(_RIGHT_WRIST)
    le = abs_pt(_LEFT_ELBOW)
    re = abs_pt(_RIGHT_ELBOW)
    lh = abs_pt(_LEFT_HIP)
    rh = abs_pt(_RIGHT_HIP)
    ear_vis = 0.20 if face_missing else 0.28
    lear = abs_pt(_LEFT_EAR, min_vis=ear_vis)
    rear = abs_pt(_RIGHT_EAR, min_vis=ear_vis)

    landmarks = {
        "nose": None if nose is None else {"x": nose[0], "y": nose[1], "v": nose[2]},
        "left_shoulder": None if ls is None else {"x": ls[0], "y": ls[1], "v": ls[2]},
        "right_shoulder": None if rs is None else {"x": rs[0], "y": rs[1], "v": rs[2]},
        "left_elbow": None if le is None else {"x": le[0], "y": le[1], "v": le[2]},
        "right_elbow": None if re is None else {"x": re[0], "y": re[1], "v": re[2]},
        "left_wrist": None if lw is None else {"x": lw[0], "y": lw[1], "v": lw[2]},
        "right_wrist": None if rw is None else {"x": rw[0], "y": rw[1], "v": rw[2]},
        "left_ear": None if lear is None else {"x": lear[0], "y": lear[1], "v": lear[2]},
        "right_ear": None if rear is None else {"x": rear[0], "y": rear[1], "v": rear[2]},
    }

    reasons: List[str] = []
    head_state = "pose_inconclusive"
    head_conf = 0.0
    torso_ori = None

    def _wrist_on_head_zone() -> bool:
        """Mão na cabeça/rosto (acima dos ombros). Peito/ombro NÃO conta — senão mata H e inventa J no I."""
        for wrist in (lw, rw):
            if wrist is None:
                continue
            if wrist_in_true_head_zone(
                wrist, nose=nose, left_shoulder=ls, right_shoulder=rs, face_bbox=face_bbox
            ):
                return True
        return False

    def _wrist_near_upper() -> bool:
        """Compat: só zona da cabeça (não terço superior inteiro do torso)."""
        return _wrist_on_head_zone()

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
        if crown_look_down_face(frame, nose, face_bbox):
            # Topo da cabeça visível: caixa YuNet é cabelo, não perfil.
            head_down_geom = True
            head_turned = False
            skin = face_crop_skin_ratio(frame, face_bbox)
            dark = face_crop_dark_ratio(frame, face_bbox)
            reasons.append(
                f"yunet_crown_look_down_skin={0.0 if skin is None else skin:.2f}"
                f"_dark={0.0 if dark is None else dark:.2f}"
            )
        elif nose_in_profile_face(nose, face_bbox):
            head_turned = True
            reasons.append("face_nose_yaw_profile")
        elif unilateral_ear_profile(lear, rear):
            head_turned = True
            reasons.append("ear_unilateral_profile")
        elif nose_ear_distance_profile(nose, lear, rear, shoulder_w):
            head_turned = True
            reasons.append("ear_nose_span_profile")
        elif ears_stacked_profile(lear, rear, shoulder_w):
            head_turned = True
            reasons.append("ear_asymmetric_profile")

        # Nariz fraco / acima dos ombros com face ausente = falso positivo no topo da cabeça.
        # Com head_down_since já ativo, permite mesmo com punho na zona (braço apoiado
        # enquanto look-down) — L/K sem since prévio não entram aqui.
        nose_weak = float(nose[2]) < 0.40
        nose_above_shoulders = nose[1] < shoulder_cy - 0.02 * shoulder_w
        wrist_on_head = _wrist_on_head_zone()
        if face_missing and (nose_weak or nose_above_shoulders) and (
            not wrist_on_head or head_down_since is not None
        ):
            # ratio bem negativo = nariz acima dos ombros (cabeça erguida). Forçar
            # look-down aqui criava FP sticky quando a face era omitida no analytics.
            if float(nose_to_shoulder) < -0.18 and not nose_weak:
                reasons.append("skip_untrusted_nose_clearly_elevated")
            else:
                head_down_geom = True
                head_turned = False
                reasons.append("face_missing_untrusted_nose")

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
            # Geometria look-down prevalece sobre punho na cabeça: braço apoiado ≠ oclusão J/K.
            # Arbitration usa chest_keep para não suprimir; L/K sem geom continuam oclusão.
            dur = (now - head_down_since) if head_down_since else 0.0
            if dur >= 8.0:
                head_state = "head_down_persistent"
            else:
                head_state = "head_down_short"
            head_conf = min(0.95, 0.55 + abs(nose_to_shoulder) * 0.3)
            reasons.append(f"nose_shoulder_ratio={nose_to_shoulder:.2f}")
            if head_supported or wrist_on_head:
                reasons.append("wrist_near_chest_keep_head_down")
        elif face_missing and not wrist_on_head:
            # Pose alinhada + face detector ausente ≠ cabeça baixa (cenário I: virar/sair).
            head_state = "pose_inconclusive"
            head_conf = 0.3
            reasons.append("face_detector_missing_pose_aligned")
        elif head_turned:
            head_state = "head_turned"
            head_conf = 0.6
            reasons.append("lateral_nose_offset")
        else:
            head_state = "head_forward"
            head_conf = 0.7
            reasons.append("aligned_torso_head")
    elif ls and rs and face_missing and not _wrist_on_head_zone():
        # Look-down extremo (H): orelhas acima dos ombros. Virar/sair (I): inconclusivo.
        shoulder_cy = (ls[1] + rs[1]) / 2.0
        shoulder_w = max(1.0, abs(rs[0] - ls[0]))
        ear_pts = [p for p in (lear, rear) if p is not None]
        ear_above = any(p[1] < shoulder_cy - 0.02 * shoulder_w for p in ear_pts)
        if ear_above:
            dur = (now - head_down_since) if head_down_since else 0.0
            if dur >= 8.0:
                head_state = "head_down_persistent"
            else:
                head_state = "head_down_short"
            head_conf = 0.62
            reasons.append("shoulders_without_face_look_down")
            reasons.append("ears_above_shoulders")
        else:
            head_state = "pose_inconclusive"
            head_conf = 0.28
            reasons.append("face_missing_lateral_or_out_of_frame")
    else:
        reasons.append("insufficient_keypoints")

    # Hysteresis: se já havia head_down válido, nariz ainda na linha/abaixo dos ombros
    # mantém postura (anti-flicker aligned_torso / crown). Não inicia do zero.
    if (
        head_down_since is not None
        and head_state in ("head_forward", "pose_inconclusive", "head_turned")
        and ls
        and rs
        and nose
    ):
        shoulder_cy_h = (ls[1] + rs[1]) / 2.0
        shoulder_w_h = max(1.0, abs(rs[0] - ls[0]))
        nts_h = (nose[1] - shoulder_cy_h) / shoulder_w_h
        if nts_h > 0.0:
            dur_h = (now - head_down_since) if now is not None else 0.0
            head_state = "head_down_persistent" if dur_h >= 8.0 else "head_down_short"
            head_conf = max(head_conf, 0.55)
            reasons.append(f"nose_hysteresis_ratio={nts_h:.2f}")
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
    near_reason = "wrist_near_face"
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

    # Facepalm com YuNet ainda "vendo" face: afrouxar vis do punho acima dos ombros.
    min_wrist_vis = 0.28 if face_missing else 0.40
    near_ratio = float(wrist_near_face_max_ratio)
    if face_missing:
        near_ratio = min(max(near_ratio, 0.70), 0.85)
    else:
        # J: mão cobrindo — distância um pouco mais permissiva
        near_ratio = min(max(near_ratio, 0.70), 0.80)

    if proxy_bbox and (lw or rw):
        fx, fy, fw, fh = proxy_bbox[:4]
        fcx = fx + fw / 2.0
        fcy = fy + fh / 2.0
        fdiag = max(1.0, (fw ** 2 + fh ** 2) ** 0.5)
        # Expansão moderada — face close-up enorme + 1.35× engolia o peito (E4/L).
        if face_missing:
            expand = (fx - fw * 0.20, fy - fh * 0.20, fw * 1.4, fh * 1.25)
        else:
            down = 1.12 if fh >= 180 else 1.28
            expand = (fx - fw * 0.18, fy - fh * 0.18, fw * 1.36, fh * down)
        for wrist in (lw, rw):
            if wrist is None:
                continue
            wx, wy = wrist[0], wrist[1]
            wrist_vis = float(wrist[2])
            # Punho acima dos ombros: aceitar vis mais baixa (facepalm).
            above_shoulders = False
            if ls and rs:
                shoulder_cy = (ls[1] + rs[1]) / 2.0
                shoulder_w = max(1.0, abs(rs[0] - ls[0]))
                above_shoulders = wy <= shoulder_cy + 0.12 * shoulder_w
            need_vis = 0.28 if (face_missing or above_shoulders) else min_wrist_vis
            if wrist_vis < need_vis:
                continue
            # Peito ≠ oclusão (E4/L), com ou sem face: punho abaixo dos ombros.
            if ls and rs:
                shoulder_cy = (ls[1] + rs[1]) / 2.0
                shoulder_w = max(1.0, abs(rs[0] - ls[0]))
                if wy > shoulder_cy + 0.18 * shoulder_w:
                    continue
            d = math.hypot(wx - fcx, wy - fcy) / fdiag
            if d >= near_ratio:
                continue
            if not (
                expand[0] <= wx <= expand[0] + expand[2]
                and expand[1] <= wy <= expand[1] + expand[3]
            ):
                continue
            near = True
            near_reason = "wrist_near_face_proxy" if face_missing else "wrist_near_face"
            break

    # Fallback: punho acima da linha dos ombros (mão no rosto) — também com face visível (J).
    if not near and ls and rs:
        if _wrist_on_head_zone():
            near = True
            near_reason = (
                "wrist_in_head_zone_proxy" if face_missing else "wrist_in_head_zone"
            )

    # Cotovelo só na zona da cabeça (J). Linha dos ombros pegava E4 (celular no peito).
    if not near and ls and rs:
        shoulder_cy = (ls[1] + rs[1]) / 2.0
        shoulder_w = max(1.0, abs(rs[0] - ls[0]))
        cx = (ls[0] + rs[0]) / 2.0
        head_y = nose[1] if nose is not None else (shoulder_cy - 0.20 * shoulder_w)
        for elbow in (le, re):
            if elbow is None or float(elbow[2]) < 0.28:
                continue
            if elbow[1] <= head_y + 0.10 * shoulder_w and abs(elbow[0] - cx) / shoulder_w <= 0.70:
                near = True
                near_reason = (
                    "elbow_raised_head_zone_proxy"
                    if face_missing
                    else "elbow_raised_head_zone"
                )
                break

    hands["visibility"] = 0.6 if near else (0.3 if (lw or rw) else 0.0)
    if near:
        hands["state"] = "hand_near_face"
        dur_h = (now - hand_near_since) if hand_near_since else 0.0
        reason_suffix = "_proxy" if face_missing else ""
        reason_tag = near_reason if near_reason.startswith("wrist_near") or near_reason.startswith("elbow") else (
            f"wrist_near_face{reason_suffix}"
        )
        if dur_h >= occlusion_persistent_seconds:
            face_occlusion = {
                "state": "persistent_possible_face_occlusion",
                "confidence": 0.55 if not face_missing else 0.5,
                "reasons": [f"{reason_tag}_persistent" if not reason_tag.endswith("persistent") else reason_tag],
                "note": "wrists_only_no_hand_landmarker",
                "duration_seconds": round(dur_h, 2),
            }
        else:
            face_occlusion = {
                "state": "possible_face_occlusion_by_hand",
                "confidence": 0.4 if not face_missing else 0.35,
                "reasons": [reason_tag],
                "note": "wrists_only_no_hand_landmarker",
                "duration_seconds": round(dur_h, 2),
            }
        hands["state"] = "hand_near_face"
        # Com head_down geom ativo: manter postura (braço apoiado ≠ cancelar look-down).
        # Sem head_down: reason de oclusão segue para arbitragem L/K.
        if head_state in ("head_down_short", "head_down_persistent", "head_supported"):
            reasons.append("wrist_near_chest_keep_head_down")
        elif _wrist_on_head_zone() or near_reason.startswith("elbow_raised"):
            if head_state == "head_supported":
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
