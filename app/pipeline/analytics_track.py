"""Analytics por track no runtime real (RTSP/webcam) - sem mocks."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)

BBox = Tuple[float, float, float, float]

PHONE_OCCLUSION_SUPPRESS_STATES = frozenset(
    {
        "phone_in_hand",
        "phone_near_person",
        "possible_phone_interaction",
        "probable_phone_interaction",
    }
)


def analytics_person_bbox_for_pose(
    person_bbox: BBox,
    face_bbox: Optional[BBox],
    frame_shape: Tuple[int, ...],
) -> BBox:
    """
    ROI analítica para MediaPipe Pose — NÃO altera ByteTrack / identity.

    LIVE webcam: person bbox quase full-frame distorce yaw/pitch/wrists vs MP4
    (person derivado da face). Quando a área do person domina o frame e há face,
    usa expansão face→person alinhada aos runners validados.
    """
    px, py, pw, ph = person_bbox
    fh = float(frame_shape[0]) if len(frame_shape) >= 1 else 0.0
    fw = float(frame_shape[1]) if len(frame_shape) >= 2 else 0.0
    frame_area = max(1.0, fw * fh)
    area_frac = (pw * ph) / frame_area
    if face_bbox is not None and area_frac >= 0.45:
        fx, fy, fbw, fbh = face_bbox
        ax = max(0.0, fx - 0.55 * fbw)
        ay = max(0.0, fy - 0.35 * fbh)
        aw = min(fw - ax, fbw * 2.3)
        ah = min(fh - ay, fbh * 3.6)
        if aw >= 40.0 and ah >= 80.0:
            return (ax, ay, aw, ah)
    if area_frac >= 0.55:
        return (px + pw * 0.12, py, pw * 0.76, ph * 0.72)
    return person_bbox


def is_displayable_track(
    track: dict,
    *,
    min_track_confidence: float = 0.2,
    max_lost_display_seconds: float = 2.5,
) -> bool:
    """Tracks exibíveis/contáveis — oculta fantasmas temporarily_lost / unknown."""
    tstate = str(track.get("tracking_state") or "active")
    if tstate == "expired":
        return False

    ident = track.get("identity") or {}
    face_vis = bool(ident.get("face_visible"))
    has_face_bbox = bool(track.get("face_bbox"))
    sid = track.get("student_id") or ident.get("student_id")
    id_state = str(ident.get("identity_state") or "unknown")
    conf = float(track.get("track_confidence") or 0.0)
    secs_lost = float(track.get("seconds_since_person_detection") or 0.0)
    obs = track.get("observability") or {}
    body_det = bool(obs.get("body_detected"))
    body_obs = bool(obs.get("body_observable"))

    occ = track.get("face_occlusion") or {}
    occ_state = str(occ.get("state") or "none")
    occ_active = occ_state in (
        "possible_face_occlusion_by_hand",
        "persistent_possible_face_occlusion",
    )
    hands_st = str((track.get("hands") or {}).get("state") or "")
    # Oclusão só estende hold enquanto o sumiço corporal é curto (evita fantasma na cortina).
    occlusion_hold = (occ_active or hands_st == "hand_near_face") and secs_lost <= 4.0

    pb = track.get("person_bbox") or track.get("bbox")
    fan_like = False
    if pb and len(pb) >= 4:
        pw, ph = float(pb[2] or 0), float(pb[3] or 0)
        if pw > 1 and ph / max(pw, 1.0) > 2.55:
            fan_like = True
        elif pw > 1 and ph / max(pw, 1.0) > 2.15 and pw < 90:
            fan_like = True
    lq = (track.get("observation_quality") or {}).get("landmarks_quality")
    if lq is None:
        lq = (track.get("facial_features") or {}).get("landmarks_quality")
    real_face = bool(face_vis) and float(lq or 0.0) >= 0.40

    if tstate == "active":
        # Ventilador/poste: YOLO person + YuNet no objeto — esconde sem rosto real.
        if fan_like and not real_face and not sid:
            return False
        if body_det or body_obs:
            return conf >= min_track_confidence
        # Face YuNet sozinha (sem landmarks / corpo) = fantasma de parede — não contar.
        if real_face:
            return True
        if sid and id_state in ("face_confirmed", "body_continuity"):
            return True
        # H ✅: cabeça baixa / perfil — person_bbox sem face landmarks ainda conta.
        if (
            pb
            and len(pb) >= 4
            and conf >= min_track_confidence
            and not fan_like
            and float(pb[2] or 0) > 8
            and float(pb[3] or 0) > 8
            and (
                sid
                or id_state in ("face_confirmed", "body_continuity", "uncertain")
                or secs_lost <= 1.5
            )
        ):
            return True
        if face_vis or has_face_bbox:
            return False
        if sid and id_state == "uncertain":
            return conf >= max(min_track_confidence, 0.45)
        return conf >= max(min_track_confidence, 0.45)

    if tstate == "temporarily_lost":
        if real_face:
            return secs_lost <= max(max_lost_display_seconds, 6.0)
        if sid and id_state in ("face_confirmed", "body_continuity"):
            grace = 6.0 if occlusion_hold else max_lost_display_seconds
            # H: person_bbox ainda no track (look-down) — grace curto extra, sem fantasma de cortina.
            if (
                pb
                and len(pb) >= 4
                and float(pb[2] or 0) > 8
                and float(pb[3] or 0) > 8
                and not fan_like
            ):
                grace = max(grace, 4.0)
            return secs_lost <= grace
        if id_state == "uncertain" and occlusion_hold:
            return secs_lost <= 4.0
        # has_face_bbox sem real_face: não segurar fantasma de parede
        return False
    if real_face or (sid and id_state in ("face_confirmed", "body_continuity")):
        return True

    if id_state == "uncertain" and tstate == "reassociated":
        return body_det and conf >= max(min_track_confidence, 0.35)

    if tstate != "active":
        return False

    return body_det and conf >= min_track_confidence


def filter_displayable_tracks(tracks: List[dict], **kwargs) -> List[dict]:
    return [t for t in tracks if is_displayable_track(t, **kwargs)]


def _clip_crop(frame: np.ndarray, bbox: BBox, *, pad_ratio: float = 0.0) -> Optional[np.ndarray]:
    ih, iw = frame.shape[:2]
    x, y, w, h = bbox[:4]
    if pad_ratio > 0:
        px = float(w) * pad_ratio
        py = float(h) * pad_ratio
        x, y, w, h = x - px, y - py, w + 2 * px, h + 2 * py
    x1, y1 = max(0, int(x)), max(0, int(y))
    x2, y2 = min(iw, int(x + w)), min(ih, int(y + h))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    return frame[y1:y2, x1:x2].copy()


def _quality_status(overall: float, reasons: List[str]) -> str:
    if "face_not_visible" in reasons or "invalid_bbox" in reasons:
        return "inconclusive"
    if overall >= 0.55 and "blurred" not in reasons and "face_too_small" not in reasons:
        return "observable"
    if overall >= 0.35:
        return "low_quality"
    return "inconclusive"


def ascii_overlay_label(text: str) -> str:
    """cv2.putText cannot draw accents — use ASCII on the bitmap."""
    repl = {
        "\u00e1": "a", "\u00e0": "a", "\u00e2": "a", "\u00e3": "a", "\u00e4": "a",
        "\u00e9": "e", "\u00ea": "e", "\u00e8": "e",
        "\u00ed": "i", "\u00ec": "i",
        "\u00f3": "o", "\u00f4": "o", "\u00f5": "o", "\u00f2": "o",
        "\u00fa": "u", "\u00f9": "u",
        "\u00e7": "c",
        "\u00c1": "A", "\u00c9": "E", "\u00cd": "I", "\u00d3": "O", "\u00da": "U", "\u00c7": "C",
        "\u00f1": "n", "\u00d1": "N",
    }
    out = []
    for ch in text or "":
        out.append(repl.get(ch, ch if ord(ch) < 128 else "?"))
    return "".join(out)


@dataclass
class TrackAnalyticsCache:
    track_key: str
    last_quality_ts: float = 0.0
    last_landmarks_ts: float = 0.0
    last_expression_ts: float = 0.0
    last_attention_ts: float = 0.0
    last_pose_ts: float = 0.0
    observation_quality: Dict[str, Any] = field(default_factory=dict)
    facial_features: Dict[str, Any] = field(default_factory=dict)
    expression: Dict[str, Any] = field(default_factory=dict)
    visual_attention: Dict[str, Any] = field(default_factory=dict)
    drowsiness: Dict[str, Any] = field(default_factory=dict)
    phone: Dict[str, Any] = field(default_factory=dict)
    pose: Dict[str, Any] = field(default_factory=dict)
    hands: Dict[str, Any] = field(default_factory=dict)
    head_state: Dict[str, Any] = field(default_factory=dict)
    face_occlusion: Dict[str, Any] = field(default_factory=dict)
    latencies_ms: Dict[str, Any] = field(default_factory=dict)
    # expr smoothing
    expr_labels: Deque[Tuple[float, str, float]] = field(default_factory=lambda: deque(maxlen=64))
    expr_negative_since: Optional[float] = None
    # attention / drowsiness temporal
    attn_samples: Deque[Tuple[float, str, float]] = field(default_factory=lambda: deque(maxlen=64))
    eyes_closed_since: Optional[float] = None  # legado; preferir accum
    eyes_closed_accum_seconds: float = 0.0
    eyes_last_tick: Optional[float] = None
    eyes_unobservable_since: Optional[float] = None
    eyes_observation_paused: bool = False
    eyes_recover_since: Optional[float] = None  # face voltou — só limpa unobs após hold
    head_down_accum_seconds: float = 0.0
    head_down_last_tick: Optional[float] = None
    head_down_since: Optional[float] = None
    hand_near_since: Optional[float] = None
    hand_near_last_seen: Optional[float] = None
    hand_near_candidate_since: Optional[float] = None
    event_clear_since: Dict[str, float] = field(default_factory=dict)  # etype -> since
    forward_since: Optional[float] = None
    away_since: Optional[float] = None
    drowsiness_cooldown_until: float = 0.0
    drowsiness_state: str = "none"
    attention_state: str = "inconclusive"
    attention_started: Optional[float] = None
    track_first_seen: Optional[float] = None
    force_close_observation_gap: bool = False
    perclos_samples: Deque[Tuple[float, bool]] = field(default_factory=lambda: deque(maxlen=512))
    episode_counts: Dict[str, int] = field(default_factory=dict)
    last_student_id: Optional[str] = None
    last_identity_state: Optional[str] = None
    observability: Dict[str, Any] = field(default_factory=dict)


class RealtimeAnalyticsEngine:
    """
    Motor Ãºnico de analytics por track no modo RTSP.
    FusionEngine legado permanece disponÃ­vel; este engine Ã© o oficial no runtime.
    """

    def __init__(self, settings):
        self.settings = settings
        self._cache: Dict[str, TrackAnalyticsCache] = {}
        self._expression_provider = None
        self._expression_provider_secondary = None
        self._expression_provider_status = "not_loaded"
        self._expression_health_reason = None
        self._emotion_async_worker = None
        self._emotion_backend = "fer_onnx"
        self._phone_associator = None
        self._phone_status = "disabled"
        self._phone_reason = "phone_yolo_disabled"
        self._open_events: Dict[str, Dict[str, Any]] = {}  # key = f"{track}:{event_type}"
        self._live_event_buffer: Deque[Dict[str, Any]] = deque(maxlen=200)
        self._event_sink = None  # callable(event_dict) | None
        self._ws_events: Deque[Dict[str, Any]] = deque(maxlen=64)
        self._identity_engine = None
        self._person_tracker_debug: Dict[str, Any] = {}
        self._phone_detector_debug: Dict[str, Any] = {}
        self._init_expression_provider()
        self._init_emotion_async_backend()
        self._init_phone()
        self._init_identity_engine()

    def shutdown(self) -> None:
        """Encerra worker assíncrono de emoção (se ativo)."""
        w = getattr(self, "_emotion_async_worker", None)
        if w is not None:
            try:
                w.shutdown()
            except Exception as e:
                logger.warning("emotion_async_worker_shutdown_failed", error=str(e))
            self._emotion_async_worker = None

    def _emotion_backend_is_vgaf(self) -> bool:
        b = str(getattr(self.settings, "expression_emotion_backend", "hsemotion_vgaf") or "hsemotion_vgaf")
        return b.strip().lower() in ("hsemotion_vgaf", "hsemotion_enet_b0_8_best_vgaf", "hs_vgaf")

    def _activate_fer_onnx_fallback(self, *, reason: str) -> None:
        """Fallback explícito para FER+ (não silencioso). Não derruba o pipeline."""
        self._emotion_backend = "fer_onnx"
        self._emotion_async_worker = None
        try:
            from app.vision.expressions import create_expression_provider

            cur = str(getattr(self._expression_provider, "provider_name", "") or "").lower()
            if cur in ("fer_onnx", "ferplus", "emotion_ferplus") and self._expression_provider_status == "available":
                self._expression_health_reason = f"fallback_fer_onnx;reason={reason};kept_existing"
                logger.error(
                    "hsemotion_vgaf_falling_back_fer_onnx",
                    reason=reason,
                    note="FER+ already loaded; async worker disabled",
                )
                return
            prov = create_expression_provider("fer_onnx")
            h = prov.health(force=True) if hasattr(prov, "health") else {"status": "available"}
            if h.get("status") != "available":
                logger.error(
                    "fer_onnx_fallback_unavailable",
                    reason=reason,
                    fer_reason=h.get("reason"),
                )
                self._expression_provider_status = "unavailable"
                self._expression_health_reason = f"fallback_fer_failed;{reason}"
                return
            self._expression_provider = prov
            self._expression_provider_status = "available"
            self._expression_health_reason = f"fallback_fer_onnx;reason={reason}"
            logger.error(
                "hsemotion_vgaf_falling_back_fer_onnx",
                reason=reason,
                note="FER+ activated as explicit fallback",
            )
        except Exception as e:
            logger.error(
                "fer_onnx_fallback_init_failed",
                reason=reason,
                error=str(e),
            )
            self._expression_provider_status = "unavailable"
            self._expression_health_reason = f"fallback_fer_init_failed;{reason}"

    def _init_emotion_async_backend(self) -> None:
        """Default: HSEmotion VGAF + worker assíncrono. FER+ se backend≠vgaf ou falha de boot."""
        self._emotion_backend = str(
            getattr(self.settings, "expression_emotion_backend", "hsemotion_vgaf") or "hsemotion_vgaf"
        ).strip().lower()
        if not self._emotion_backend_is_vgaf():
            return
        mode = str(getattr(self.settings, "module_expression_mode", "disabled") or "disabled").lower()
        if mode == "disabled":
            return
        try:
            from app.pipeline.emotion_async_worker import AsyncEmotionWorker
            from app.vision.expressions import create_expression_provider

            prov = create_expression_provider("hsemotion_vgaf")
            h = prov.health(force=True) if hasattr(prov, "health") else {"status": "available"}
            if h.get("status") != "available":
                self._activate_fer_onnx_fallback(
                    reason=str(h.get("reason") or "hsemotion_vgaf_unavailable")
                )
                return
            interval = float(
                getattr(self.settings, "expression_hsemotion_interval_seconds", 2.0) or 2.0
            )
            max_batch = int(getattr(self.settings, "expression_hsemotion_max_batch", 5) or 5)
            worker = AsyncEmotionWorker(
                prov, interval_seconds=interval, max_batch=max_batch
            )
            worker.start()
            self._emotion_async_worker = worker
            # provider de analytics aponta para VGAF (documentação/health); inferência via worker
            self._expression_provider = prov
            self._expression_provider_status = "available"
            self._expression_health_reason = (
                f"provider=hsemotion_vgaf;async_worker=1;interval_s={interval};"
                "smile_boost=off;frown_boost=off;smooth=1"
            )
            logger.info(
                "expression_emotion_backend_hsemotion_vgaf_enabled",
                interval_s=interval,
                max_batch=max_batch,
                note="default_async_no_smile_frown_boost",
            )
        except Exception as e:
            logger.error(
                "hsemotion_vgaf_init_failed_falling_back_fer",
                error=str(e),
            )
            self._activate_fer_onnx_fallback(reason=f"init_exception:{e}")

    def _init_identity_engine(self) -> None:
        from app.vision.identity_binding import IdentityBindingEngine

        self._identity_engine = IdentityBindingEngine(
            face_missing_ttl_seconds=float(
                getattr(self.settings, "identity_face_missing_ttl_seconds", 12) or 12
            ),
            minimum_new_identity_confidence=float(
                getattr(self.settings, "identity_minimum_new_confidence", 0.75) or 0.75
            ),
            minimum_identity_margin=float(
                getattr(self.settings, "identity_minimum_margin", 0.10) or 0.10
            ),
            confirmations_before_switch=int(
                getattr(self.settings, "identity_confirmations_before_switch", 3) or 3
            ),
            identity_switch_cooldown_seconds=float(
                getattr(self.settings, "identity_switch_cooldown_seconds", 10) or 10
            ),
            confidence_decay_per_second=float(
                getattr(self.settings, "identity_confidence_decay_per_second", 0.04) or 0.04
            ),
            body_continuity_uncertain_threshold=float(
                getattr(self.settings, "identity_body_continuity_uncertain_threshold", 0.45) or 0.45
            ),
            temporarily_lost_uncertain_seconds=float(
                getattr(self.settings, "identity_temporarily_lost_uncertain_seconds", 4.0) or 4.0
            ),
        )

    def set_event_sink(self, sink) -> None:
        """Callback para persistir/publicar eventos comportamentais (open/update/close)."""
        self._event_sink = sink

    def drain_ws_events(self) -> List[Dict[str, Any]]:
        out = list(self._ws_events)
        self._ws_events.clear()
        return out

    def _init_expression_provider(self) -> None:
        mode = str(getattr(self.settings, "module_expression_mode", "disabled") or "disabled").lower()
        if mode == "disabled":
            self._expression_provider_status = "disabled"
            self._expression_health_reason = "module_expression_disabled"
            self._expression_provider_secondary = None
            return
        try:
            from app.vision.expressions import create_expression_provider

            primary = str(getattr(self.settings, "expression_provider", "fer_legacy") or "fer_legacy")
            if primary in ("none", "mock") and not self._is_demo():
                primary = "fer_legacy"

            chain_raw = getattr(self.settings, "expression_fallback_chain", None)
            if chain_raw:
                if isinstance(chain_raw, str):
                    chain = [x.strip() for x in chain_raw.split(",") if x.strip()]
                else:
                    chain = [str(x).strip() for x in chain_raw if str(x).strip()]
            else:
                chain = [primary, "hsemotion", "deepface", "fer_legacy"]
            # Garante primary no início, sem duplicatas
            ordered: List[str] = []
            for name in [primary] + list(chain):
                key = name.strip().lower()
                if key and key not in ordered:
                    ordered.append(key)

            self._expression_provider = None
            self._expression_provider_secondary = None
            last_reason = None
            primary_key = primary.strip().lower()
            for name in ordered:
                try:
                    prov = create_expression_provider(name)
                except Exception as e:
                    last_reason = f"{name}:{e}"
                    continue
                ok = True
                reason = None
                if hasattr(prov, "health"):
                    h = prov.health(force=True)
                    ok = h.get("status") == "available"
                    reason = h.get("reason")
                elif hasattr(prov, "is_available"):
                    ok = bool(prov.is_available)
                if not ok:
                    last_reason = reason or f"{name}:unavailable"
                    continue
                self._expression_provider = prov
                self._expression_provider_status = "available"
                selected = str(getattr(prov, "provider_name", name) or name).lower()
                used_fallback = selected != primary_key and name.strip().lower() != primary_key
                self._expression_health_reason = (
                    f"provider={name};requested={primary_key};fallback={used_fallback}"
                )
                if used_fallback:
                    logger.warning(
                        "expression_provider_fallback",
                        requested=primary_key,
                        selected=selected,
                        reason="primary_unavailable",
                    )
                else:
                    logger.info(
                        "expression_provider_selected",
                        requested=primary_key,
                        selected=selected,
                        model_name=getattr(prov, "model_name", None),
                    )
                    if selected not in ("fer_onnx", "ferplus") and mode in ("debug", "shadow", "production"):
                        logger.warning(
                            "expression_provider_not_tri_profile",
                            selected=selected,
                            hint="Para entrega TRI use $env:PRESENCA_CONFIG_OVERLAY='config.tri.yaml' (fer_onnx).",
                        )
                break

            if self._expression_provider is None:
                self._expression_provider_status = "unavailable"
                self._expression_health_reason = last_reason or "no_provider_available"
                logger.warning(
                    "expression_provider_unavailable",
                    requested=primary_key,
                    reason=self._expression_health_reason,
                )
                return

            # A/B secundário (opcional)
            secondary_name = getattr(self.settings, "expression_ab_secondary", None)
            if secondary_name:
                sec_key = str(secondary_name).strip().lower()
                primary_key = str(getattr(self._expression_provider, "provider_name", "") or "").lower()
                if sec_key and sec_key != primary_key:
                    try:
                        sec = create_expression_provider(sec_key)
                        sec_ok = True
                        if hasattr(sec, "health"):
                            sec_ok = sec.health(force=True).get("status") == "available"
                        if sec_ok:
                            self._expression_provider_secondary = sec
                    except Exception:
                        self._expression_provider_secondary = None
        except Exception as e:
            logger.warning("expression_provider_init_failed", error=str(e))
            self._expression_provider = None
            self._expression_provider_secondary = None
            self._expression_provider_status = "unavailable"
            self._expression_health_reason = str(e)

    def _init_phone(self) -> None:
        mode = str(getattr(self.settings, "module_phone_mode", "disabled") or "disabled").lower()
        if mode == "disabled":
            self._phone_status = "disabled"
            self._phone_reason = "module_phone_disabled"
            return
        if not getattr(self.settings, "phone_yolo_enabled", False):
            self._phone_status = "unavailable"
            self._phone_reason = "phone_yolo_disabled_or_model_missing"
            return
        try:
            from app.vision.person_phone import PersonPhoneAssociator

            self._phone_associator = PersonPhoneAssociator(
                minimum_interaction_seconds=float(
                    getattr(self.settings, "phone_possible_after_seconds", 5.0) or 5.0
                ),
                probable_seconds=float(
                    getattr(self.settings, "phone_probable_after_seconds", 12.0) or 12.0
                ),
                interaction_requires_in_hand=bool(
                    getattr(self.settings, "phone_interaction_requires_in_hand", True)
                ),
                clear_hold_seconds=float(
                    getattr(self.settings, "phone_association_clear_hold_seconds", 2.0) or 2.0
                ),
            )
            # probe import
            from app.vision.phone_yolo import detect_phones  # noqa: F401

            self._phone_status = "available"
            self._phone_reason = None
        except Exception as e:
            self._phone_associator = None
            self._phone_status = "unavailable"
            self._phone_reason = f"dependency_or_model_missing:{e}"

    def _is_demo(self) -> bool:
        try:
            from app.runtime_mode import is_demo

            return is_demo()
        except Exception:
            return False

    def _get_cache(self, key: str) -> TrackAnalyticsCache:
        if key not in self._cache:
            self._cache[key] = TrackAnalyticsCache(track_key=key)
            self._cache[key].expression = {"status": "not_implemented"}
            self._cache[key].visual_attention = {"status": "not_implemented"}
            self._cache[key].drowsiness = {"status": "not_implemented"}
            self._cache[key].phone = {
                "status": self._phone_status,
                "state": "not_detected",
                "provider": "yolo",
                "reason": self._phone_reason,
            }
        return self._cache[key]

    def process_camera(
        self,
        *,
        camera_id: str,
        frame: np.ndarray,
        matches: List[dict],
        boxes: List[tuple],
        now: Optional[float] = None,
        person_tracks: Optional[List[Any]] = None,
        person_tracker_debug: Optional[Dict[str, Any]] = None,
    ) -> List[dict]:
        """
        Person-first: person_tracks alimentam o motor.
        matches/boxes (faces do overlay de presenÃ§a) sÃ³ reconfirmam identidade.
        Compat: se person_tracks ausente, sintetiza 1 track por face (legado).
        """
        now = now if now is not None else time.time()
        self._person_tracker_debug = dict(person_tracker_debug or {})
        q_iv = float(getattr(self.settings, "analytics_quality_interval_seconds", 0.5) or 0.5)
        l_iv = float(getattr(self.settings, "analytics_landmarks_interval_seconds", 0.5) or 0.5)
        e_iv = float(getattr(self.settings, "expression_interval_seconds", 1.0) or 1.0)
        a_iv = float(getattr(self.settings, "visual_attention_interval_seconds", 0.5) or 0.5)

        from datetime import datetime, timezone
        from app.vision.tracking_types import FaceTrack, PersonTrack

        # --- person tracks ---
        persons: List[PersonTrack] = list(person_tracks or [])
        if not persons:
            # fallback legado: face boxes como person proxy (deprecated path)
            n = max(len(matches), len(boxes))
            for i in range(n):
                m = matches[i] if i < len(matches) else {}
                bbox = boxes[i] if i < len(boxes) else (m.get("bbox") or [0, 0, 0, 0])
                bbox_t = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                ts = datetime.now(timezone.utc)
                persons.append(
                    PersonTrack(
                        track_id=f"{camera_id}-person-face-{i:03d}",
                        camera_id=camera_id,
                        first_seen_at=ts,
                        last_seen_at=ts,
                        bounding_box=bbox_t,
                        tracking_confidence=float(m.get("confidence") or 0.4),
                        visible=True,
                    )
                )
            self._person_tracker_debug = {
                **self._person_tracker_debug,
                "tracker_backend": "face_proxy_fallback",
                "detections_count": len(persons),
                "person_tracks_count": len(persons),
                "note": "sem person_tracks - usando faces como proxy",
            }

        # --- face tracks from overlay ---
        face_tracks: List[FaceTrack] = []
        face_identities: Dict[str, dict] = {}
        n_faces = max(len(matches), len(boxes))
        for i in range(n_faces):
            m = matches[i] if i < len(matches) else {}
            bbox = boxes[i] if i < len(boxes) else (m.get("bbox") or m.get("box") or [0, 0, 0, 0])
            if not bbox or len(bbox) < 4:
                continue
            bbox_t = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            fid = f"face-{i:03d}"
            ts = datetime.now(timezone.utc)
            face_tracks.append(
                FaceTrack(
                    track_id=fid,
                    camera_id=camera_id,
                    first_seen_at=ts,
                    last_seen_at=ts,
                    face_bbox=bbox_t,
                    tracking_confidence=float(m.get("confidence") or 0.0),
                    visible=True,
                )
            )
            sid = m.get("student_id")
            conf = float(m.get("confidence") or 0.0)
            margin = m.get("margin")
            top2 = m.get("top2_score")
            face_identities[fid] = {
                "student_id": sid,
                "confidence": conf,
                "margin": margin,
                "top2_score": top2,
                "full_name": m.get("full_name"),
            }

        # identity continuity
        id_states = {}
        if self._identity_engine is not None:
            person_meta = {
                p.track_id: {
                    "tracking_state": getattr(p, "tracking_state", "active"),
                    "tracking_confidence": float(getattr(p, "tracking_confidence", 0.0) or 0.0),
                    "seconds_since_person_detection": float(
                        getattr(p, "seconds_since_person_detection", 0.0) or 0.0
                    ),
                    # Só no frame de reclaim — NÃO usar reassociation_score residual
                    # (score fica >0 enquanto o track vive e derrubava identidade para uncertain).
                    "spatial_reassociation": getattr(p, "tracking_state", "") == "reassociated",
                }
                for p in persons
            }
            id_states = self._identity_engine.update_continuity(
                now=now,
                person_tracks=persons,
                face_tracks=face_tracks,
                face_identities=face_identities,
                person_meta=person_meta,
            )

        # map face_id â†’ face track
        faces_by_id = {f.track_id: f for f in face_tracks}

        tracks_out: List[dict] = []
        person_boxes: Dict[str, BBox] = {}
        face_bboxes_by_person: Dict[str, BBox] = {}
        wrists_by_person: Dict[str, List[Tuple[float, float]]] = {}
        head_down_flags: Dict[str, bool] = {}
        active_keys = set()

        pose_mode = str(getattr(self.settings, "module_pose_mode", "disabled")).lower()
        pose_enabled = pose_mode != "disabled" and bool(
            getattr(self.settings, "pose_body_enabled", True)
        )

        for person in persons:
            key = person.track_id
            active_keys.add(key)
            cache = self._get_cache(key)
            if cache.track_first_seen is None:
                cache.track_first_seen = now
            person_bbox = (
                float(person.bounding_box[0]),
                float(person.bounding_box[1]),
                float(person.bounding_box[2]),
                float(person.bounding_box[3]),
            )
            person_boxes[key] = person_bbox
            ist = id_states.get(key)
            assoc = (ist.association if ist else None) or {}
            face_tid = assoc.get("face_track_id") if not assoc.get("ambiguous") else None
            face_tr = faces_by_id.get(face_tid) if face_tid else None
            face_bbox = face_tr.face_bbox if face_tr else None
            # se associaÃ§Ã£o ambÃ­gua mas hÃ¡ face candidata, ainda pode usar bbox espacialmente
            if face_bbox is None and assoc.get("face_track_id"):
                ft = faces_by_id.get(assoc["face_track_id"])
                if ft:
                    face_bbox = ft.face_bbox
            if face_bbox is not None:
                face_bboxes_by_person[key] = face_bbox

            identity = (
                ist.as_dict()
                if ist
                else {
                    "student_id": None,
                    "confidence": 0.0,
                    "source": "unknown",
                    "face_visible": False,
                    "seconds_since_face_seen": None,
                    "margin": None,
                }
            )
            sid = identity.get("student_id")
            conf = float(identity.get("confidence") or 0.0)
            face_visible = bool(identity.get("face_visible"))

            t0 = time.perf_counter()
            # crops: face se visÃ­vel, senÃ£o ROI cabeÃ§a (topo do person)
            if face_bbox is not None:
                crop = _clip_crop(frame, face_bbox)
                crop_lm = _clip_crop(frame, face_bbox, pad_ratio=0.35)
                if crop_lm is None:
                    crop_lm = crop
            else:
                hx, hy, hw, hh = person_bbox
                head_proxy = (hx + hw * 0.2, hy, hw * 0.6, hh * 0.35)
                crop = None
                crop_lm = _clip_crop(frame, head_proxy, pad_ratio=0.1)

            # --- quality multimodal ---
            if now - cache.last_quality_ts >= q_iv or not cache.observation_quality:
                tq0 = time.perf_counter()
                cache.observation_quality = self._compute_multimodal_quality(
                    face_crop=crop,
                    face_bbox=face_bbox,
                    person_bbox=person_bbox,
                    frame_shape=frame.shape,
                    face_visible=face_visible,
                    pose=cache.pose,
                    phone=cache.phone,
                    face_occlusion=cache.face_occlusion,
                )
                cache.latencies_ms["quality"] = round((time.perf_counter() - tq0) * 1000.0, 2)
                cache.last_quality_ts = now

            # --- landmarks (sÃ³ se face observÃ¡vel) ---
            if face_visible and face_bbox is not None:
                if now - cache.last_landmarks_ts >= l_iv or not cache.facial_features:
                    tl0 = time.perf_counter()
                    cache.facial_features = self._compute_landmarks(
                        crop_lm, key, cache.observation_quality
                    )
                    cache.latencies_ms["landmarks"] = round((time.perf_counter() - tl0) * 1000.0, 2)
                    cache.last_landmarks_ts = now
                    lq = cache.facial_features.get("landmarks_quality")
                    if lq is not None and cache.observation_quality:
                        cache.observation_quality["landmarks_quality"] = lq
                        cache.observation_quality["face_visibility"] = float(lq)
            else:
                cache.facial_features = {
                    "status": "inconclusive",
                    "reason": "face_not_observable",
                    "provider": "skipped",
                    "left_eye_openness": None,
                    "right_eye_openness": None,
                    "average_eye_openness": None,
                    "yaw": None,
                    "pitch": None,
                    "roll": None,
                    "landmarks_quality": 0.0,
                }

            # --- pose corporal ---
            if pose_enabled and (now - cache.last_pose_ts >= a_iv or not cache.pose):
                tp0 = time.perf_counter()
                try:
                    from app.vision.body_pose import estimate_body_pose

                    # Baseline recovery: person ByteTrack puro (sem face-ROI analítica).
                    # Sempre passa face YuNet real — NÃO anular por head_down_since
                    # (isso causava sticky face_missing_untrusted_nose).
                    pr = estimate_body_pose(
                        frame,
                        person_bbox,
                        face_bbox=face_bbox,
                        head_down_since=cache.head_down_since,
                        hand_near_since=cache.hand_near_since,
                        now=now,
                        wrist_near_face_max_ratio=float(
                            getattr(self.settings, "face_occlusion_wrist_near_ratio", 0.65) or 0.65
                        ),
                        occlusion_persistent_seconds=float(
                            getattr(self.settings, "face_occlusion_persistent_seconds", 5.0) or 5.0
                        ),
                    )
                    cache.pose = pr.as_dict()
                    cache.hands = dict(pr.hands)
                    cache.face_occlusion = dict(pr.face_occlusion)
                    cache.head_state = {
                        "state": pr.head_state,
                        "confidence": pr.head_confidence,
                        "reasons": list(pr.reasons),
                    }
                    q_pose = str((cache.observation_quality or {}).get("status") or "")
                    if pr.head_state in ("head_down_short", "head_down_persistent", "head_supported"):
                        if cache.head_down_since is None:
                            cache.head_down_since = now
                    elif pr.head_state == "head_forward":
                        # Face YuNet presente + pose forward limpa sticky.
                        # LIVE costuma ser partially_observable — exigir qualidade plena
                        # impedia reset (cabeça erguida + evento de 23s+/minutos).
                        _face_ok = False
                        if face_bbox is not None:
                            _face_ok = float(face_bbox[2]) >= 55.0 and float(face_bbox[3]) >= 70.0
                        if face_visible or _face_ok:
                            cache.head_down_since = None
                            cache.head_down_accum_seconds = 0.0
                            cache.head_down_last_tick = None
                    elif pr.head_state == "head_turned" and (
                        face_visible
                        or (
                            face_bbox is not None
                            and float(face_bbox[2]) >= 55.0
                            and float(face_bbox[3]) >= 70.0
                        )
                    ):
                        cache.head_down_since = None
                        cache.head_down_accum_seconds = 0.0
                        cache.head_down_last_tick = None
                    confirm_sec = float(
                        getattr(self.settings, "face_occlusion_confirm_seconds", 0.7) or 0.7
                    )
                    hand_hold = float(
                        getattr(self.settings, "face_occlusion_clear_hold_seconds", 0.45) or 0.45
                    )
                    # Enquanto o rosto está sumido (mão cobrindo), punhos somem com frequência —
                    # hold bem mais longo evita episódios de 6–10s fragmentados.
                    face_missing_hold = float(
                        getattr(self.settings, "face_occlusion_face_missing_hold_seconds", 15.0)
                        or 15.0
                    )
                    effective_hold = (
                        max(hand_hold, face_missing_hold) if not face_visible else hand_hold
                    )
                    persist_sec = float(
                        getattr(self.settings, "face_occlusion_persistent_seconds", 5.0) or 5.0
                    )
                    wrist_near_now = (pr.hands or {}).get("state") == "hand_near_face"
                    if wrist_near_now:
                        if cache.hand_near_candidate_since is None:
                            cache.hand_near_candidate_since = now
                        elif (now - cache.hand_near_candidate_since) >= confirm_sec:
                            if cache.hand_near_since is None:
                                cache.hand_near_since = cache.hand_near_candidate_since
                            cache.hand_near_last_seen = now
                        if cache.hand_near_since is None:
                            cache.face_occlusion = {
                                "state": "none",
                                "reasons": ["occlusion_pending_confirm"],
                            }
                            cache.hands = dict(cache.hands or {})
                            cache.hands["state"] = "not_near_face"
                    else:
                        cache.hand_near_candidate_since = None
                        if cache.hand_near_last_seen is not None and (
                            now - cache.hand_near_last_seen
                        ) < effective_hold:
                            dur_h = now - float(cache.hand_near_since or now)
                            cache.hands = dict(cache.hands or {})
                            cache.hands["state"] = "hand_near_face"
                            if dur_h >= persist_sec:
                                cache.face_occlusion = {
                                    "state": "persistent_possible_face_occlusion",
                                    "confidence": 0.55,
                                    "reasons": ["wrist_near_face_persistent", "occlusion_hold"],
                                    "note": "occlusion_hold",
                                    "duration_seconds": round(dur_h, 2),
                                }
                            else:
                                cache.face_occlusion = {
                                    "state": "possible_face_occlusion_by_hand",
                                    "confidence": 0.4,
                                    "reasons": ["wrist_near_face", "occlusion_hold"],
                                    "note": "occlusion_hold",
                                    "duration_seconds": round(dur_h, 2),
                                }
                        else:
                            cache.hand_near_since = None
                            cache.hand_near_last_seen = None
                            if (cache.face_occlusion or {}).get("state") not in (None, "none"):
                                if not wrist_near_now:
                                    cache.face_occlusion = {"state": "none", "reasons": ["wrist_cleared"]}
                            cache.hands = dict(cache.hands or {})
                            if cache.hands.get("state") == "hand_near_face":
                                cache.hands["state"] = "not_near_face"

                    if cache.hand_near_since is not None:
                        dur_h = now - float(cache.hand_near_since)
                        state = (
                            "persistent_possible_face_occlusion"
                            if dur_h >= persist_sec
                            else "possible_face_occlusion_by_hand"
                        )
                        hold_reasons = []
                        if not wrist_near_now:
                            hold_reasons.append("occlusion_hold")
                        if not face_visible:
                            hold_reasons.append("face_missing_continuity")
                        cache.face_occlusion = {
                            "state": state,
                            "confidence": 0.55 if state.endswith("persistent") else 0.4,
                            "reasons": [
                                "wrist_near_face_persistent"
                                if state.endswith("persistent")
                                else "wrist_near_face"
                            ]
                            + hold_reasons,
                            "duration_seconds": round(dur_h, 2),
                        }
                        cache.hands = dict(cache.hands or {})
                        cache.hands["state"] = "hand_near_face"

                    self._suppress_false_occlusion_if_face_clear(
                        cache, face_visible=face_visible, now=now
                    )
                    self._apply_pitch_head_state(cache, face_visible=face_visible, now=now)
                    # Duração cabeça baixa: usar since do pose mesmo sem face (antes só acumulava com face)
                    self._tick_head_down_duration(cache, now=now)
                    # wrists for phone
                    wr = []
                    for kname in ("left_wrist", "right_wrist"):
                        w = (pr.landmarks or {}).get(kname)
                        if w and w.get("x") is not None:
                            wr.append((float(w["x"]), float(w["y"])))
                    wrists_by_person[key] = wr
                    head_down_flags[key] = pr.head_state in (
                        "head_down_short",
                        "head_down_persistent",
                        "head_supported",
                    )
                except Exception as e:
                    cache.pose = {"status": "error", "reason": str(e)}
                    cache.head_state = {"state": "pose_inconclusive", "confidence": 0.0, "reasons": [str(e)]}
                    cache.hands = {"state": "unavailable"}
                    cache.face_occlusion = {"state": "none"}
                cache.latencies_ms["pose"] = round((time.perf_counter() - tp0) * 1000.0, 2)
                cache.last_pose_ts = now
            elif not pose_enabled:
                cache.pose = {"status": "disabled"}
                cache.head_state = {"state": "pose_inconclusive", "status": "disabled"}
                cache.hands = {"status": "disabled"}
                cache.face_occlusion = {"state": "none"}

            # Rosto sumiu sem punho → preferir cabeça baixa (antes da atenção/expressão)
            self._apply_face_not_observable_occlusion(cache, face_visible=face_visible, now=now)

            # refresh quality with pose/occlusion
            if cache.observation_quality:
                cache.observation_quality = self._enrich_quality_from_pose(
                    cache.observation_quality,
                    pose=cache.pose,
                    face_occlusion=cache.face_occlusion,
                    phone=cache.phone,
                    face_visible=face_visible,
                    person_visible=True,
                )
                # preservar invalid_bbox
                if "invalid_bbox" in (cache.observation_quality.get("reasons") or []):
                    cache.observation_quality["status"] = "inconclusive"

            # --- expression ---
            expr_mode = str(getattr(self.settings, "module_expression_mode", "disabled")).lower()
            occ = (cache.face_occlusion or {}).get("state") or "none"
            if not face_visible or occ in (
                "possible_face_occlusion_by_hand",
                "persistent_possible_face_occlusion",
            ):
                cache.expr_labels.clear()
                cache.expression = {
                    "status": "inconclusive",
                    "reason": "face_not_observable"
                    if not face_visible
                    else "possible_face_occlusion",
                    "normalized_state": "inconclusive",
                    "smoothed_state": "inconclusive",
                    "smoothed_display_pt": "inconclusivo",
                    "is_conclusive": False,
                    "confidence": 0.0,
                }
            elif expr_mode != "disabled":
                if self._emotion_async_worker is not None:
                    # Poll frequente do cache; cadência de inferência = worker (2s).
                    # NÃO bloqueia: maybe_submit só enfileira.
                    poll_iv = min(e_iv, 0.5)
                    if now - cache.last_expression_ts >= poll_iv:
                        te0 = time.perf_counter()
                        self._emotion_async_worker.maybe_submit(key, crop, now)
                        cache.expression = self._emotion_async_worker.build_expression_dict(
                            key, now
                        )
                        cache.latencies_ms["expression"] = round(
                            (time.perf_counter() - te0) * 1000.0, 2
                        )
                        cache.last_expression_ts = now
                elif now - cache.last_expression_ts >= e_iv:
                    te0 = time.perf_counter()
                    cache.expression = self._compute_expression(crop, cache, now)
                    cache.latencies_ms["expression"] = round((time.perf_counter() - te0) * 1000.0, 2)
                    cache.last_expression_ts = now
            else:
                cache.expression = {"status": "disabled"}

            # --- attention + drowsiness ---
            lm_mode = str(getattr(self.settings, "module_face_landmarks_mode", "disabled")).lower()
            fusion_mode = str(getattr(self.settings, "module_temporal_fusion_mode", "disabled")).lower()
            if lm_mode != "disabled" or pose_mode != "disabled" or fusion_mode != "disabled":
                if now - cache.last_attention_ts >= a_iv:
                    ta0 = time.perf_counter()
                    cache.visual_attention, cache.drowsiness = self._compute_attention_drowsiness(
                        cache, now, face_visible=face_visible
                    )
                    cache.latencies_ms["attention_drowsiness"] = round(
                        (time.perf_counter() - ta0) * 1000.0, 2
                    )
                    cache.last_attention_ts = now
            else:
                cache.visual_attention = {"status": "disabled", "state": "inconclusive"}
                cache.drowsiness = {"status": "disabled", "state": "inconclusive"}

            # Repassa oclusão → attention/expr UI (J: não manter "Alta" sob mão no rosto)
            occ_now = str((cache.face_occlusion or {}).get("state") or "none")
            hands_now = str((cache.hands or {}).get("state") or "")
            if occ_now in (
                "possible_face_occlusion_by_hand",
                "persistent_possible_face_occlusion",
            ) or hands_now == "hand_near_face":
                if cache.visual_attention:
                    va = dict(cache.visual_attention)
                    va["state"] = "inconclusive"
                    va["level"] = "inconclusive"
                    va["status"] = "inconclusive"
                    reasons = list(va.get("reasons") or [])
                    if "face_occlusion" not in reasons:
                        reasons.append("face_occlusion")
                    va["reasons"] = reasons
                    va["face_occlusion"] = occ_now if occ_now != "none" else hands_now
                    va["unobservable_seconds"] = (cache.face_occlusion or {}).get(
                        "duration_seconds"
                    ) or va.get("unobservable_seconds")
                    cache.visual_attention = va
                if cache.drowsiness and str((cache.drowsiness or {}).get("state") or "") not in (
                    "inconclusive",
                    "none",
                ):
                    cache.drowsiness = {
                        **dict(cache.drowsiness or {}),
                        "state": "inconclusive",
                        "reasons": list(
                            set(list((cache.drowsiness or {}).get("reasons") or []) + ["face_occlusion"])
                        ),
                    }
            # sincroniza face_occlusion no quality
            if cache.observation_quality:
                cache.observation_quality = self._enrich_quality_from_pose(
                    cache.observation_quality,
                    pose=cache.pose,
                    face_occlusion=cache.face_occlusion,
                    phone=cache.phone,
                    face_visible=face_visible,
                    person_visible=True,
                )

            cache.latencies_ms["total_analytics"] = round((time.perf_counter() - t0) * 1000.0, 2)
            full_name = None
            if face_tid and face_tid in face_identities:
                full_name = face_identities[face_tid].get("full_name")
            if not full_name:
                full_name = identity.get("full_name")

            pb_list = [int(person_bbox[0]), int(person_bbox[1]), int(person_bbox[2]), int(person_bbox[3])]
            fb_list = (
                [int(face_bbox[0]), int(face_bbox[1]), int(face_bbox[2]), int(face_bbox[3])]
                if face_bbox
                else None
            )
            track_age = now - (cache.track_first_seen or now)

            # reset janelas se identidade mudou de forma real
            id_state = str(identity.get("identity_state") or "unknown")
            if cache.last_student_id and sid and cache.last_student_id != sid:
                cache.eyes_closed_accum_seconds = 0.0
                cache.eyes_last_tick = None
                cache.perclos_samples.clear()
                cache.episode_counts.clear()
            if cache.last_identity_state == "uncertain" and id_state == "face_confirmed":
                pass  # confirmação — mantém eventos do track
            cache.last_student_id = sid
            cache.last_identity_state = id_state

            tstate = getattr(person, "tracking_state", "active") or "active"
            secs_body = float(getattr(person, "seconds_since_person_detection", 0.0) or 0.0)
            body_detected = tstate == "active" and bool(person.visible if hasattr(person, "visible") else True)
            if tstate == "temporarily_lost":
                body_detected = False
            max_lost = float(getattr(self.settings, "person_tracking_max_time_lost_seconds", 8) or 8)
            body_track_active = tstate in ("active", "temporarily_lost", "reassociated")
            body_continuity_available = body_track_active and (
                tstate != "temporarily_lost" or secs_body < max_lost
            )
            body_observable = body_detected and float(person.tracking_confidence or 0) >= 0.25
            ff_st = (cache.facial_features or {}).get("status")
            ear_v = (cache.facial_features or {}).get("average_eye_openness")
            face_obs = bool(face_visible) and ff_st == "available"
            eyes_obs = face_obs and ear_v is not None
            head_obs = face_obs and (cache.facial_features or {}).get("yaw") is not None
            expr_st = (cache.expression or {}).get("status")
            expression_obs = face_obs and expr_st in ("available", "inconclusive")
            phone_obs = body_detected and self._phone_status == "available"
            id_obs = id_state in ("face_confirmed", "body_continuity") and not bool(
                identity.get("revalidation_required")
            )
            observability = {
                "face_observable": face_obs,
                "eyes_observable": eyes_obs,
                "head_pose_observable": head_obs,
                "body_detected": body_detected,
                "body_observable": body_observable,
                "body_track_active": body_track_active,
                "body_continuity_available": body_continuity_available,
                "seconds_since_body_detection": round(secs_body, 2),
                "tracking_state": tstate,
                "phone_observable": phone_obs,
                "expression_observable": expression_obs,
                "identity_observable": id_obs,
                "ui_body_label": (
                    "body_observable"
                    if body_observable
                    else (
                        "body_continuity_temporarily_interrupted"
                        if body_continuity_available and not body_detected
                        else "body_not_observable"
                    )
                ),
            }
            cache.observability = observability

            tracks_out.append(
                {
                    "person_track_id": key,
                    "track_age_seconds": round(track_age, 2),
                    "track_confidence": round(float(person.tracking_confidence or 0.0), 3),
                    "tracking_state": tstate,
                    "seconds_since_person_detection": round(secs_body, 2),
                    "last_person_bbox": [
                        int(person.bounding_box[0]),
                        int(person.bounding_box[1]),
                        int(person.bounding_box[2]),
                        int(person.bounding_box[3]),
                    ],
                    "reassociation_score": (
                        None
                        if getattr(person, "reassociation_score", None) is None
                        else round(float(person.reassociation_score), 3)
                    ),
                    "raw_tracker_id": getattr(person, "raw_tracker_id", None),
                    "missed_detections": int(getattr(person, "missed_detections", 0) or 0),
                    "expire_reason": getattr(person, "expire_reason", None),
                    "identity": identity,
                    "observability": observability,
                    "person_bbox": pb_list,
                    "face_bbox": fb_list,
                    "face_person_association": assoc,
                    "pose": dict(cache.pose or {}),
                    "hands": dict(cache.hands or {}),
                    "observation_quality": dict(cache.observation_quality),
                    "head_state": self._head_state_for_track(cache, now=now),
                    "face_occlusion": dict(cache.face_occlusion or {}),
                    "phone": dict(cache.phone),
                    "expression": dict(cache.expression),
                    "facial_features": dict(cache.facial_features),
                    "visual_attention": dict(cache.visual_attention),
                    "drowsiness": dict(cache.drowsiness),
                    "latencies_ms": dict(cache.latencies_ms),
                    "full_name": full_name,
                    # aliases deprecated
                    "track_id": key,
                    "student_id": sid,
                    "identity_confidence": conf if sid else None,
                    "confidence": conf,
                    "bbox": pb_list,
                }
            )

        # phone
        self._update_phones(
            frame,
            person_boxes,
            tracks_out,
            now,
            wrists=wrists_by_person,
            head_looking_down=head_down_flags,
            face_bboxes=face_bboxes_by_person,
        )
        self._suppress_occlusion_for_phone(tracks_out, frame, now)

        # close events for dead tracks
        for old_key in list(self._cache.keys()):
            if old_key not in active_keys:
                self._close_all_events_for_track(old_key, now)
                if self._identity_engine:
                    self._identity_engine.expire_track(old_key)
                self._cache.pop(old_key, None)

        for t in tracks_out:
            t["displayable"] = is_displayable_track(t)
            self._sync_temporal_events(t, now)
            tid = str(t.get("person_track_id") or t.get("track_id"))
            t["active_events"] = [
                {
                    "event_id": ev["event_id"],
                    "event_type": ev["event_type"],
                    "status": ev["lifecycle"],
                    "duration_seconds": round(now - ev["started_at"], 2),
                    "episode_index": ev.get("episode_index"),
                    "attribution_status": ev.get("attribution_status"),
                    "candidate_student_id": ev.get("candidate_student_id"),
                    "confirmed_student_id": ev.get("confirmed_student_id"),
                    "identity_state": ev.get("identity_state"),
                    "reasons": ev.get("reasons"),
                    "severity": ev.get("severity"),
                }
                for k, ev in self._open_events.items()
                if k.startswith(tid + ":")
            ]
            t["phone_detector"] = dict(self._phone_detector_debug)
            t["person_detector"] = dict(self._person_tracker_debug)

        return tracks_out

    def _compute_multimodal_quality(
        self,
        *,
        face_crop,
        face_bbox,
        person_bbox,
        frame_shape,
        face_visible: bool,
        pose: dict,
        phone: dict,
        face_occlusion: dict,
    ) -> Dict[str, Any]:
        from app.vision.observation_quality import compute_observation_quality

        person_vis = 0.85 if person_bbox and person_bbox[2] > 8 else 0.0
        face_vis = 0.0
        face_reasons: List[str] = []
        base = {
            "face_size_score": 0.0,
            "sharpness_score": 0.0,
            "illumination_score": 0.0,
            "pose_score": None,
            "occlusion_score": None,
            "visibility_score": 0.0,
            "landmarks_quality": None,
            "overall_score": 0.0,
        }
        if face_visible and face_crop is not None and face_bbox is not None:
            q = compute_observation_quality(face_crop, face_bbox=face_bbox, frame_shape=frame_shape)
            base.update(
                {
                    "face_size_score": round(q.face_size_score, 3),
                    "sharpness_score": round(q.sharpness_score, 3),
                    "illumination_score": round(q.illumination_score, 3),
                    "pose_score": round(q.pose_score, 3),
                    "visibility_score": round(q.visibility_score, 3),
                    "overall_score": round(q.overall_score, 3),
                }
            )
            face_vis = float(q.visibility_score or q.overall_score or 0.0)
            face_reasons = list(q.reasons)
        elif face_visible and face_bbox is not None and face_crop is None:
            face_reasons = ["invalid_bbox"]
            face_vis = 0.0
        else:
            face_reasons = ["face_not_visible"]

        return self._enrich_quality_from_pose(
            {
                **base,
                "person_visibility": person_vis,
                "face_visibility": face_vis,
                "pose_visibility": 0.0,
                "hands_visibility": 0.0,
                "phone_visibility": 0.0,
                "overall_observability": 0.0,
                "status": "inconclusive",
                "reasons": face_reasons,
            },
            pose=pose or {},
            face_occlusion=face_occlusion or {},
            phone=phone or {},
            face_visible=face_visible,
            person_visible=person_vis > 0,
        )

    def _enrich_quality_from_pose(
        self,
        q: Dict[str, Any],
        *,
        pose: dict,
        face_occlusion: dict,
        phone: dict,
        face_visible: bool,
        person_visible: bool,
    ) -> Dict[str, Any]:
        reasons = list(q.get("reasons") or [])
        pose_vis = 0.0
        if (pose or {}).get("status") == "available":
            for r in pose.get("reasons") or []:
                if isinstance(r, str) and r.startswith("pose_visibility="):
                    try:
                        pose_vis = float(r.split("=", 1)[1])
                    except ValueError:
                        pose_vis = 0.6
            if pose_vis <= 0:
                pose_vis = 0.6
        hands_vis = float((pose or {}).get("hands", {}).get("visibility") or 0.0)
        if not hands_vis and (q.get("hands_visibility") is not None):
            hands_vis = float(q.get("hands_visibility") or 0.0)
        # from cache hands
        phone_vis = 0.0
        ph_state = (phone or {}).get("state")
        if ph_state and ph_state not in ("not_detected", "none", None):
            phone_vis = 0.7
        occ = (face_occlusion or {}).get("state") or "none"
        if occ != "none":
            reasons.append(occ if "occlusion" in occ else f"possible_face_occlusion")
            q["face_visibility"] = min(float(q.get("face_visibility") or 0.0), 0.25)
        head = (pose or {}).get("head_state")
        if isinstance(head, str) and "head_down" in head:
            reasons.append("head_down")
        elif isinstance((q.get("head_state") if False else None), dict):
            pass

        person_vis = float(q.get("person_visibility") or (0.85 if person_visible else 0.0))
        face_vis = float(q.get("face_visibility") or 0.0)
        overall = (
            0.35 * person_vis
            + 0.30 * face_vis
            + 0.20 * pose_vis
            + 0.10 * hands_vis
            + 0.05 * phone_vis
        )
        if "invalid_bbox" in reasons:
            status = "inconclusive"
        elif not person_visible:
            status = "not_visible"
            reasons = ["person_not_detected"]
        elif face_vis < 0.35 or occ != "none" or "head_down" in reasons:
            status = "partially_observable"
        elif overall >= 0.55 and face_visible:
            status = "observable"
        elif overall >= 0.25:
            status = "partially_observable"
        else:
            status = "inconclusive"

        q.update(
            {
                "person_visibility": round(person_vis, 3),
                "face_visibility": round(face_vis, 3),
                "pose_visibility": round(pose_vis, 3),
                "hands_visibility": round(hands_vis, 3),
                "phone_visibility": round(phone_vis, 3),
                "overall_observability": round(overall, 3),
                "overall_score": round(max(float(q.get("overall_score") or 0), overall), 3),
                "status": status,
                "reasons": list(dict.fromkeys(reasons)),
            }
        )
        return q

    def _compute_quality(
        self, crop: Optional[np.ndarray], bbox: BBox, frame_shape
    ) -> Dict[str, Any]:
        from app.vision.observation_quality import compute_observation_quality

        if crop is None:
            return {
                "face_size_score": 0.0,
                "sharpness_score": 0.0,
                "illumination_score": 0.0,
                "pose_score": None,
                "occlusion_score": None,
                "visibility_score": 0.0,
                "landmarks_quality": None,
                "overall_score": 0.0,
                "status": "inconclusive",
                "reasons": ["invalid_bbox"],
            }
        q = compute_observation_quality(crop, face_bbox=bbox, frame_shape=frame_shape)
        status = _quality_status(q.overall_score, q.reasons)
        return {
            "face_size_score": round(q.face_size_score, 3),
            "sharpness_score": round(q.sharpness_score, 3),
            "illumination_score": round(q.illumination_score, 3),
            "pose_score": round(q.pose_score, 3),
            "occlusion_score": None,  # nÃ£o estimamos oclusÃ£o sem modelo
            "visibility_score": round(q.visibility_score, 3),
            "landmarks_quality": None,
            "overall_score": round(q.overall_score, 3),
            "status": status,
            "reasons": list(q.reasons),
        }

    def _compute_landmarks(
        self, crop: Optional[np.ndarray], track_id: str, quality: Dict[str, Any]
    ) -> Dict[str, Any]:
        base = {
            "left_eye_openness": None,
            "right_eye_openness": None,
            "average_eye_openness": None,
            "blink_score": None,
            "mouth_open_score": None,
            "possible_yawn_score": None,
            "smile_score": None,
            "frown_score": None,
            "yaw": None,
            "pitch": None,
            "roll": None,
            "gaze_horizontal": None,
            "gaze_vertical": None,
            "landmarks_quality": None,
            "provider": "unavailable",
            "status": "unavailable",
            "reason": None,
        }
        if crop is None:
            base["status"] = "inconclusive"
            base["reason"] = "invalid_bbox"
            return base
        if quality.get("status") in ("inconclusive",) and "invalid_bbox" in (quality.get("reasons") or []):
            base["status"] = "inconclusive"
            base["reason"] = "invalid_bbox"
            return base

        try:
            from app.vision.facial_signals import face_landmarker_health
            from app.vision.landmarks_adapter import facial_features_from_roi

            health = face_landmarker_health()
            if health.get("status") != "available":
                base["status"] = "unavailable"
                base["provider"] = "mediapipe"
                base["reason"] = health.get("reason") or "face_landmarker_unavailable"
                return base

            ff = facial_features_from_roi(crop, track_id)
            provider = "mediapipe"
            status = "available"
            reason = None
            if ff.yaw is None and ff.average_eye_openness is None and (ff.landmarks_quality or 0) <= 0:
                status = "inconclusive"
                reason = "no_landmarks"
            return {
                "left_eye_openness": None if ff.left_eye_openness is None else round(float(ff.left_eye_openness), 4),
                "right_eye_openness": None if ff.right_eye_openness is None else round(float(ff.right_eye_openness), 4),
                "average_eye_openness": None if ff.average_eye_openness is None else round(float(ff.average_eye_openness), 4),
                "blink_score": ff.blink_score,
                "mouth_open_score": None if ff.mouth_open_score is None else round(float(ff.mouth_open_score), 4),
                "possible_yawn_score": None if ff.mouth_open_score is None else (
                    round(float(ff.mouth_open_score), 4) if ff.mouth_open_score >= 0.55 else 0.0
                ),
                "smile_score": None if ff.smile_score is None else round(float(ff.smile_score), 4),
                "frown_score": None if ff.frown_score is None else round(float(ff.frown_score), 4),
                "yaw": None if ff.yaw is None else round(float(ff.yaw), 4),
                "pitch": None if ff.pitch is None else round(float(ff.pitch), 4),
                "roll": None if ff.roll is None else round(float(ff.roll), 4),
                "gaze_horizontal": None if ff.gaze_horizontal is None else round(float(ff.gaze_horizontal), 4),
                "gaze_vertical": None if ff.gaze_vertical is None else round(float(ff.gaze_vertical), 4),
                "landmarks_quality": round(float(ff.landmarks_quality or 0.0), 3),
                "provider": provider,
                "status": status,
                "reason": reason,
            }
        except Exception as e:
            logger.debug("landmarks_error", error=str(e))
            base["status"] = "error"
            base["reason"] = str(e)
            return base

    def _compute_expression(
        self, crop: Optional[np.ndarray], cache: TrackAnalyticsCache, now: float
    ) -> Dict[str, Any]:
        q = cache.observation_quality or {}
        min_q = float(getattr(self.settings, "expression_minimum_observation_quality", 0.55) or 0.55)
        min_samples = int(getattr(self.settings, "expression_minimum_samples", 4) or 4)
        provider_fallback = str(
            getattr(self._expression_provider, "provider_name", None)
            or getattr(self.settings, "expression_provider", "fer_onnx")
        )

        def _held_from_buffer(*, reason: str) -> Optional[Dict[str, Any]]:
            """Mantém expressão conclusiva breve se o buffer já tem amostras (evita zerar o relatório)."""
            if len(cache.expr_labels) < min_samples:
                return None
            smoothed, sample_count = self._smooth_expression(
                cache.expr_labels, now, provider_name=provider_fallback
            )
            if smoothed == "inconclusive":
                return None
            from app.vision.expressions.normalization import display_expression_pt

            return {
                "provider": provider_fallback,
                "model_name": getattr(self._expression_provider, "model_name", None) or provider_fallback,
                "raw_label": None,
                "normalized_state": smoothed.replace("predominantly_", "")
                if smoothed.startswith("predominantly_")
                else smoothed,
                "confidence": 0.0,
                "smoothed_state": smoothed,
                "smoothed_display_pt": display_expression_pt(smoothed),
                "is_conclusive": True,
                "status": "available",
                "inference_ms": 0.0,
                "sample_count": sample_count,
                "reason": reason,
                "quality_hold": True,
            }

        if q.get("overall_score") is not None and float(q["overall_score"]) < min_q:
            held = _held_from_buffer(reason="insufficient_observation_quality_hold")
            if held is not None:
                return held
            return {
                "provider": provider_fallback,
                "model_name": getattr(self._expression_provider, "model_name", None) or provider_fallback,
                "raw_label": None,
                "normalized_state": "inconclusive",
                "confidence": 0.0,
                "smoothed_state": "inconclusive",
                "smoothed_display_pt": "inconclusivo",
                "is_conclusive": False,
                "status": "inconclusive",
                "inference_ms": 0.0,
                "sample_count": len(cache.expr_labels),
                "reason": "insufficient_observation_quality",
            }
        if self._expression_provider_status != "available" or self._expression_provider is None:
            return {
                "provider": provider_fallback,
                "model_name": getattr(self._expression_provider, "model_name", None) or provider_fallback,
                "raw_label": None,
                "normalized_state": "inconclusive",
                "confidence": 0.0,
                "smoothed_state": "inconclusive",
                "smoothed_display_pt": "inconclusivo",
                "is_conclusive": False,
                "status": self._expression_provider_status or "unavailable",
                "inference_ms": 0.0,
                "sample_count": 0,
                "reason": self._expression_health_reason or "provider_unavailable",
            }
        if crop is None:
            held = _held_from_buffer(reason="invalid_bbox_hold")
            if held is not None:
                return held
            return {
                "provider": provider_fallback,
                "status": "inconclusive",
                "normalized_state": "inconclusive",
                "smoothed_state": "inconclusive",
                "smoothed_display_pt": "inconclusivo",
                "is_conclusive": False,
                "confidence": 0.0,
                "inference_ms": 0.0,
                "sample_count": len(cache.expr_labels),
                "reason": "invalid_bbox",
            }
        try:
            from app.vision.expressions.normalization import (
                display_expression_pt,
                normalize_expression_label,
            )

            preds = self._expression_provider.predict_batch([crop])
            pred = preds[0] if preds else None
            ab_reason = "primary_only"
            if pred is not None and self._expression_provider_secondary is not None:
                try:
                    from app.vision.expressions.ab_pick import pick_expression_ab

                    sec_preds = self._expression_provider_secondary.predict_batch([crop])
                    sec = sec_preds[0] if sec_preds else None
                    if sec is not None and getattr(sec, "is_conclusive", True):
                        pred, ab_reason = pick_expression_ab(pred, sec)
                except Exception:
                    ab_reason = "ab_failed_primary"
            if pred is None:
                return {
                    "provider": getattr(self._expression_provider, "provider_name", "unknown"),
                    "status": "error",
                    "reason": "empty_prediction",
                    "normalized_state": "inconclusive",
                    "smoothed_state": "inconclusive",
                    "is_conclusive": False,
                    "confidence": 0.0,
                    "inference_ms": 0.0,
                    "sample_count": len(cache.expr_labels),
                }
            # Prefer full probability distribution when provider exposes it
            raw = pred.raw_label or pred.label
            if getattr(pred, "probabilities", None):
                from app.vision.expressions.normalization import pick_label as _pick

                # Confiança mínima mais alta para positive (FER vaza happy em rosto sério)
                label2, conf2, ok2 = _pick(pred.probabilities, minimum_confidence=0.01)
                if label2 != "inconclusive":
                    raw = pred.raw_label or label2
                    pred_label = label2
                    pred_conf = conf2
                else:
                    pred_label = pred.label
                    pred_conf = float(pred.confidence)
            else:
                pred_label = pred.label
                pred_conf = float(pred.confidence)

            provider_norm = normalize_expression_label(str(pred.label or ""))
            raw_norm = normalize_expression_label(str(pred.raw_label or ""))
            # NÃO forçar positive só porque o provider disse happy com conf baixa
            if (provider_norm == "positive" or raw_norm == "positive") and float(pred_conf) >= 0.50:
                pred_label = "positive"
                pred_conf = max(float(pred_conf), float(pred.confidence or 0.0))

            # Smile boost: desligado por padrão (rosto sério virava "positiva")
            smile_boost_enabled = bool(
                getattr(self.settings, "expression_smile_boost_enabled", False)
            )
            frown_boost_enabled = bool(
                getattr(self.settings, "expression_frown_boost_enabled", True)
            )
            smile_src = "none"
            frown_src = "none"
            smile_combined = 0.0
            smile_lm_f = 0.0
            frown_lm_f = 0.0
            if smile_boost_enabled or frown_boost_enabled:
                try:
                    from app.vision.emotion_engagement import _smile_heuristic_score

                    smile_px = float(_smile_heuristic_score(crop)) if crop is not None else 0.0
                except Exception:
                    smile_px = 0.0
                ff = cache.facial_features or {}
                smile_lm = ff.get("smile_score")
                smile_lm_f = float(smile_lm) if isinstance(smile_lm, (int, float)) else 0.0
                frown_lm = ff.get("frown_score")
                frown_lm_f = float(frown_lm) if isinstance(frown_lm, (int, float)) else 0.0
                ear = ff.get("average_eye_openness")
                ear_f = float(ear) if isinstance(ear, (int, float)) else 1.0
                mouth = ff.get("mouth_open_score")
                mouth_f = float(mouth) if isinstance(mouth, (int, float)) else 0.0
                smile_combined = max(smile_px, smile_lm_f)
                # Sorriso: landmark alto OU pixel forte com dentes (sorriso aberto).
                # Pixel sozinho em cara séria (~0.3–0.45) NÃO dispara boost.
                if (
                    smile_boost_enabled
                    and ear_f >= 0.15
                    and smile_lm_f >= 0.50
                    and frown_lm_f < smile_lm_f * 0.85
                ):
                    pred_label = "positive"
                    pred_conf = max(float(pred_conf), smile_lm_f, 0.6)
                    raw = "happy"
                    smile_src = "landmarks"
                elif (
                    smile_boost_enabled
                    and ear_f >= 0.15
                    and smile_lm_f >= 0.48
                    and 0.12 <= mouth_f <= 0.55
                    and frown_lm_f < 0.30
                ):
                    pred_label = "positive"
                    pred_conf = max(float(pred_conf), smile_lm_f, 0.55)
                    raw = "happy"
                    smile_src = "landmarks_mouth"
                elif (
                    smile_boost_enabled
                    and ear_f >= 0.15
                    and smile_px >= 0.55
                    and mouth_f >= 0.14
                    and frown_lm_f < 0.35
                    and smile_lm_f >= 0.28
                ):
                    # Sorriso com dentes: pixel alto + boca aberta (EX+ mais responsivo)
                    pred_label = "positive"
                    pred_conf = max(float(pred_conf), smile_px, smile_lm_f, 0.58)
                    raw = "happy"
                    smile_src = "pixels_teeth"
                # Bico/tristeza: EAR baixo ok (olhos semicerrados no gesto).
                # Limiar ≥0.50: cara séria na webcam satura frown~0.42 (platô de droop
                # fraco) e não deve virar negativa; bico real costuma passar de 0.50
                # quando há droop/assimetría claros (ver test_frown_geometry).
                elif (
                    frown_boost_enabled
                    and smile_src == "none"
                    and smile_lm_f < 0.40
                    and frown_lm_f >= 0.50
                    and (ear_f >= 0.04 or mouth_f <= 0.14)
                ):
                    pred_label = "negative"
                    pred_conf = max(float(pred_conf), frown_lm_f, 0.55)
                    raw = "sad"
                    frown_src = "landmarks"
                elif (
                    frown_boost_enabled
                    and smile_src == "none"
                    and smile_lm_f < 0.35
                    and frown_lm_f >= 0.48
                    and mouth_f <= 0.12
                    and (ear_f >= 0.04 or mouth_f <= 0.10)
                ):
                    pred_label = "negative"
                    pred_conf = max(float(pred_conf), frown_lm_f, 0.50)
                    raw = "sad"
                    frown_src = "landmarks_pout"

            norm = normalize_expression_label(pred_label)
            min_conf = float(getattr(self.settings, "expression_minimum_confidence", 0.60) or 0.60)
            # Positive: 0.55 equilibra sorriso real vs cara séria (0.70 era overcorrection)
            min_conf_positive = float(
                getattr(self.settings, "expression_minimum_confidence_positive", 0.55) or 0.55
            )
            provider_name = str(
                getattr(pred, "provider", None)
                or getattr(self._expression_provider, "provider_name", "unknown")
            )
            # FER legado: barra um pouco mais alta; DeepFace/HSEmotion: confiar mais no modelo
            if provider_name in ("fer_legacy", "fer", "mini_xception"):
                min_conf_positive = max(min_conf_positive, 0.60)
            if norm == "positive" and float(pred_conf) < min_conf_positive:
                norm = "neutral"
                pred_label = "neutral"
                raw = "neutral"
            # Sem smile_boost geométrico: não confiar em "happy" fraco do FER (cara séria→positiva)
            if (
                norm == "positive"
                and smile_src == "none"
                and smile_lm_f < 0.48
            ):
                norm = "neutral"
                pred_label = "neutral"
                raw = "neutral"
            # Negativa: barra TRI um pouco abaixo da positiva (FER+ dilui raiva/tristeza em neutra)
            min_conf_negative = float(
                getattr(self.settings, "expression_minimum_confidence_negative", 0.42) or 0.42
            )
            if provider_name in ("fer_legacy", "fer", "mini_xception"):
                min_conf_negative = max(min_conf_negative, 0.50)
            # Massa negativa nas probs do provider (mesmo se argmax era neutra/surprise)
            neg_mass = 0.0
            try:
                probs_n = dict(pred.probabilities or {})
                neg_mass = float(probs_n.get("negative", 0.0) or 0.0)
            except Exception:
                neg_mass = 0.0
            if norm != "negative" and neg_mass >= 0.32 and smile_src == "none" and frown_src == "none":
                neu_p = float((pred.probabilities or {}).get("neutral", 0.0) or 0.0)
                pos_p = float((pred.probabilities or {}).get("positive", 0.0) or 0.0)
                if neg_mass >= neu_p * 0.70 and neg_mass >= pos_p:
                    norm = "negative"
                    pred_label = "negative"
                    pred_conf = max(float(pred_conf), neg_mass)
                    raw = str(pred.raw_label or "sad")
            if norm == "negative" and float(pred_conf) < min_conf_negative and neg_mass < min_conf_negative and frown_src == "none":
                norm = "neutral"
                pred_label = "neutral"
                raw = "neutral"
            conclusive = bool(pred.is_conclusive and pred_conf >= min_conf and norm != "inconclusive")
            if not conclusive and norm != "inconclusive" and pred_conf >= min_conf:
                conclusive = True
            if smile_src != "none" and norm == "positive":
                conclusive = True
            if (norm == "negative" and float(pred_conf) >= min_conf_negative) or frown_src != "none":
                conclusive = True
            # Aceita amostras com confiança razoável para smoothing
            # Repouso = sem boost E scores geométricos baixos (NÃO usar só FER=neutral —
            # isso apagava bico quando o modelo dizia neutral).
            resting_face = (
                smile_src == "none"
                and frown_src == "none"
                and smile_lm_f < 0.42
                and frown_lm_f < 0.28
            )
            if norm != "inconclusive" and pred_conf >= min(0.35, min_conf):
                if smile_src != "none" and norm == "positive":
                    kept = [
                        (t, lab, c)
                        for t, lab, c in cache.expr_labels
                        if lab not in ("neutral", "negative")
                    ]
                    cache.expr_labels.clear()
                    cache.expr_labels.extend(kept[-6:])
                    cache.expr_labels.append((now, "positive", float(pred_conf)))
                elif frown_src != "none" or norm == "negative":
                    kept = [
                        (t, lab, c)
                        for t, lab, c in cache.expr_labels
                        if lab not in ("neutral", "surprise", "positive")
                    ]
                    cache.expr_labels.clear()
                    cache.expr_labels.extend(kept[-6:])
                    cache.expr_labels.append((now, "negative", float(pred_conf)))
                elif resting_face:
                    # Só zera extremos quando geométrico confirma repouso
                    cache.expr_labels.clear()
                    cache.expr_labels.append((now, "neutral", float(pred_conf)))
                else:
                    cache.expr_labels.append((now, norm, pred_conf))
            win = float(getattr(self.settings, "expression_window_seconds", 8) or 8)
            while cache.expr_labels and now - cache.expr_labels[0][0] > win:
                cache.expr_labels.popleft()
            smoothed, sample_count = self._smooth_expression(
                cache.expr_labels, now, provider_name=provider_name
            )
            if smile_src != "none" and norm == "positive":
                smoothed = "predominantly_positive"
                sample_count = max(sample_count, len(cache.expr_labels), 1)
            elif frown_src != "none" or (
                norm == "negative" and float(pred_conf) >= min_conf_negative
            ):
                neg_n = sum(1 for _, lab, _ in cache.expr_labels if lab == "negative")
                min_neg = int(getattr(self.settings, "expression_minimum_negative_samples", 2) or 2)
                if frown_src != "none" or neg_n >= min_neg or neg_mass >= 0.40:
                    smoothed = "predominantly_negative"
                    sample_count = max(sample_count, len(cache.expr_labels), 1)
            elif resting_face:
                smoothed = "predominantly_neutral"
                sample_count = max(sample_count, len(cache.expr_labels), 1)
            negative_frame = frown_src != "none" or norm == "negative"
            smoothed, neg_sustained = self._apply_expression_negative_persistence(
                cache, now, smoothed, negative_frame=negative_frame
            )
            display = display_expression_pt(smoothed)
            try:
                from app.vision.emotion_engagement import emotion_backend_health

                h = emotion_backend_health()
                model_name = (
                    getattr(self._expression_provider, "model_name", None)
                    or h.get("model_name")
                    or provider_name
                )
            except Exception:
                model_name = getattr(self._expression_provider, "model_name", None) or provider_name
            status = "inconclusive"
            if sample_count > 0 and smoothed != "inconclusive":
                status = "available"
            elif conclusive:
                status = "available"
            return {
                "provider": provider_name,
                "model_name": model_name,
                "raw_label": raw,
                "normalized_state": norm if (conclusive or sample_count) else "inconclusive",
                "confidence": round(pred_conf, 3),
                "smoothed_state": smoothed,
                "smoothed_display_pt": display,
                "is_conclusive": status == "available" and smoothed != "inconclusive",
                "status": status,
                "inference_ms": round(float(pred.inference_ms), 2),
                "sample_count": sample_count,
                "smile_boost": smile_src,
                "smile_score": round(smile_combined, 3),
                "frown_boost": frown_src,
                "frown_score": round(frown_lm_f, 3),
                "negative_sustained_seconds": (
                    round(neg_sustained, 2) if neg_sustained is not None else None
                ),
                "negative_building": bool(
                    negative_frame and smoothed == "predominantly_neutral"
                ),
                "ab_reason": ab_reason,
            }
        except Exception as e:
            return {
                "provider": "fer_legacy",
                "status": "error",
                "reason": str(e),
                "normalized_state": "inconclusive",
                "smoothed_state": "inconclusive",
                "is_conclusive": False,
                "confidence": 0.0,
                "inference_ms": 0.0,
                "sample_count": len(cache.expr_labels),
            }

    def _smooth_expression(
        self,
        buf: Deque[Tuple[float, str, float]],
        now: float,
        *,
        provider_name: str = "fer_legacy",
    ) -> Tuple[str, int]:
        min_samples = int(getattr(self.settings, "expression_minimum_samples", 4) or 4)
        if len(buf) < min_samples:
            return "inconclusive", len(buf)
        counts: Dict[str, float] = {}
        for _, label, conf in buf:
            counts[label] = counts.get(label, 0.0) + conf
        # Só penaliza positive vs neutra no FER legado (overcorrection com deepface/hs)
        if provider_name in ("fer_legacy", "fer", "mini_xception", ""):
            pos = float(counts.get("positive", 0.0))
            neu = float(counts.get("neutral", 0.0))
            if pos > 0 and neu > 0 and pos <= neu * 1.15:
                counts["positive"] = pos * 0.85
        # Negativa: margem leve vs neutra (FER+ dilui); ≥2 amostras na janela
        neg = float(counts.get("negative", 0.0))
        neu = float(counts.get("neutral", 0.0))
        if neg > 0 and neu > 0 and neg < neu * 0.95:
            counts["negative"] = neg * 0.90
        best = max(counts.items(), key=lambda kv: kv[1])[0]
        if best == "surprise":
            best = "neutral"
        if best == "negative":
            neg_n = sum(1 for _, lab, _ in buf if lab == "negative")
            min_neg = int(getattr(self.settings, "expression_minimum_negative_samples", 2) or 2)
            if neg_n < min_neg and neg < neu:
                best = "neutral" if neu > 0 else "inconclusive"
        mapping = {
            "positive": "predominantly_positive",
            "neutral": "predominantly_neutral",
            "negative": "predominantly_negative",
            "surprise": "predominantly_neutral",
            "inconclusive": "inconclusive",
        }
        return mapping.get(best, "inconclusive"), len(buf)

    def _apply_expression_negative_persistence(
        self,
        cache: TrackAnalyticsCache,
        now: float,
        smoothed: str,
        *,
        negative_frame: bool,
    ) -> Tuple[str, Optional[float]]:
        """
        EX−: só promove predominantly_negative após gesto sustentado (segundos),
        não a cada frame isolado. Cara séria permanece neutra.
        """
        min_sec = float(
            getattr(self.settings, "expression_negative_min_seconds", 6.0) or 6.0
        )
        # Sorriso claro / positiva: sai da negativa imediatamente (sem esperar janela).
        if smoothed == "predominantly_positive":
            cache.expr_negative_since = None
            return smoothed, None
        candidate = smoothed == "predominantly_negative" or bool(negative_frame)
        if candidate:
            if cache.expr_negative_since is None:
                cache.expr_negative_since = now
            sustained = now - float(cache.expr_negative_since)
            if sustained >= min_sec:
                return "predominantly_negative", sustained
            return "predominantly_neutral", sustained
        cache.expr_negative_since = None
        return smoothed, None

    def _compute_attention_drowsiness(
        self, cache: TrackAnalyticsCache, now: float, *, face_visible: bool = True
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        from app.analytics.attention_drowsiness import (
            evaluate_apparent_drowsiness,
            evaluate_visual_attention,
        )

        q = cache.observation_quality or {}
        ff = cache.facial_features or {}
        overall = float(q.get("overall_observability") or q.get("overall_score") or 0.0)
        min_q_attn = float(getattr(self.settings, "visual_attention_minimum_observation_quality", 0.55) or 0.55)
        min_q_dr = float(getattr(self.settings, "drowsiness_minimum_observation_quality", 0.60) or 0.60)
        occ = (cache.face_occlusion or {}).get("state") or "none"
        head_st = (cache.head_state or {}).get("state") or "pose_inconclusive"

        if (
            face_visible
            and ff.get("status") == "available"
            and ff.get("average_eye_openness") is not None
            and occ not in ("possible_face_occlusion_by_hand", "persistent_possible_face_occlusion")
        ):
            cache.eyes_unobservable_since = None
            cache.eyes_recover_since = None
            cache.eyes_observation_paused = False


        # Sem face/olhos observÃ¡veis â†’ pausar acumuladores (nÃ£o avanÃ§ar, nÃ£o zerar)
        eyes_not_obs = (
            not face_visible
            or occ in ("possible_face_occlusion_by_hand", "persistent_possible_face_occlusion")
            or (
                ff.get("status") in ("unavailable", "error", "inconclusive")
                and ff.get("average_eye_openness") is None
            )
        )
        gap_limit = float(
            getattr(self.settings, "drowsiness_observation_gap_inconclusive_seconds", 8) or 8
        )
        if eyes_not_obs:
            cache.eyes_last_tick = None
            cache.eyes_observation_paused = True
            if cache.eyes_unobservable_since is None:
                cache.eyes_unobservable_since = now
            unobs = now - cache.eyes_unobservable_since
            if unobs >= gap_limit and cache.eyes_closed_accum_seconds > 0:
                cache.force_close_observation_gap = True
                cache.eyes_closed_accum_seconds = 0.0
                cache.eyes_closed_since = None
            reasons = []
            if not face_visible:
                reasons.append("face_not_observable")
            if "occlusion" in occ:
                reasons.append(occ)
            if head_st in ("head_down_short", "head_down_persistent", "head_supported"):
                reasons.append(head_st)
            # Tempo da pausa (rosto nao observavel)
            occ_dur = float((cache.face_occlusion or {}).get("duration_seconds") or 0.0)
            pause_dur = max(float(unobs), occ_dur)
            cache.eyes_recover_since = None

            # Pedagogia: mesmo sem face, celular / cabeça baixa = baixa atenção
            derived = self._low_attention_derived_reasons(cache, drowsiness_state="inconclusive")
            attn_state = "low" if derived else "inconclusive"
            attn = {
                "state": attn_state,
                "confidence": 0.35 if derived else 0.0,
                "duration_seconds": round(pause_dur, 2),
                "sample_count": len(cache.attn_samples),
                "contributing_signals": {
                    "observation_quality": overall,
                    "head_state": head_st,
                    "face_occlusion": occ,
                },
                "reasons": (reasons or ["insufficient_visual_evidence"]) + derived,
                "descriptive_signals": [s for s in (head_st, occ) if s and s not in ("none", "pose_inconclusive")],
                "observation_paused": True,
                "unobservable_seconds": round(unobs, 2),
                "descriptive_label": "face_occlusion_observation_paused"
                if "occlusion" in occ
                else "face_not_observable_observation_paused",
            }
            drow = {
                "state": "inconclusive",
                "confidence": 0.0,
                "duration_seconds": round(float(cache.eyes_closed_accum_seconds or 0.0), 2),
                "sample_count": len(cache.attn_samples),
                "reasons": ["eyes_not_observable"] + reasons,
                "observation_paused": True,
                "unobservable_seconds": round(unobs, 2),
                "descriptive_label": "eyes_not_observable_drowsiness_paused",
                "end_reason": "inconclusive_observation_gap" if cache.force_close_observation_gap else None,
            }
            cache.drowsiness_state = "inconclusive"
            if cache.attention_state != attn_state:
                cache.attention_state = attn_state
                cache.attention_started = now
            if attn_state == "low" and cache.attention_started:
                attn["duration_seconds"] = round(now - float(cache.attention_started), 2)
            return attn, drow

        # Face voltou: só limpa unobservable após hold curto (evita blink → timer 0s)
        clear_hold = float(getattr(self.settings, "face_occlusion_clear_hold_seconds", 0.45) or 0.45)
        if cache.eyes_unobservable_since is not None:
            if cache.eyes_recover_since is None:
                cache.eyes_recover_since = now
            if (now - cache.eyes_recover_since) < clear_hold:
                unobs = now - cache.eyes_unobservable_since
                attn = {
                    "state": "inconclusive",
                    "confidence": 0.0,
                    "duration_seconds": round(unobs, 2),
                    "sample_count": len(cache.attn_samples),
                    "reasons": ["face_recovering_hold"],
                    "observation_paused": True,
                    "unobservable_seconds": round(unobs, 2),
                    "descriptive_label": "face_not_observable_observation_paused",
                }
                drow = {
                    "state": "inconclusive",
                    "confidence": 0.0,
                    "duration_seconds": round(float(cache.eyes_closed_accum_seconds or 0.0), 2),
                    "reasons": ["eyes_not_observable", "face_recovering_hold"],
                    "observation_paused": True,
                    "unobservable_seconds": round(unobs, 2),
                }
                return attn, drow
            cache.eyes_unobservable_since = None
            cache.eyes_recover_since = None

        # retomada observavel
        cache.eyes_observation_paused = False
        cache.force_close_observation_gap = False

        yaw = ff.get("yaw")
        pitch = ff.get("pitch")
        ear = ff.get("average_eye_openness")
        gaze_h = ff.get("gaze_horizontal")
        gaze_reliable = ff.get("status") == "available" and yaw is not None

        ear_thr = float(getattr(self.settings, "drowsiness_eye_closed_ear_threshold", 0.18) or 0.18)
        eyes_closed = ear is not None and float(ear) < ear_thr
        lq_raw = ff.get("landmarks_quality")
        # Sem landmarks_quality explícito: proxy pela qualidade geral (legado/testes)
        lq = float(lq_raw) if lq_raw is not None else float(overall)
        min_lm = float(getattr(self.settings, "head_down_require_landmarks_quality", 0.45) or 0.45)
        pose_score = q.get("pose_score")
        if pose_score is None and isinstance(cache.head_state, dict):
            pose_score = cache.head_state.get("pose_score")
            if pose_score is None:
                pose_score = cache.head_state.get("confidence")
        occluded = occ in (
            "possible_face_occlusion_by_hand",
            "persistent_possible_face_occlusion",
        )
        # Observabilidade dos olhos: face + landmarks + qualidade + oclusão (+ pose se houver).
        # NÃO usar head_down / pitch alto como bloqueio absoluto sozinho.
        eyes_observable = (
            bool(face_visible)
            and ear is not None
            and ff.get("status") == "available"
            and lq >= min_lm
            and overall >= min_q_dr
            and not occluded
        )
        if pose_score is not None and float(pose_score) < 0.35:
            eyes_observable = False
        pitch_thr = float(getattr(self.settings, "head_down_pitch_threshold", 0.45) or 0.45)
        if (
            pitch is not None
            and abs(float(pitch)) > pitch_thr
            and lq < (min_lm + 0.15)
        ):
            # Pitch extremo só invalida quando landmarks já estão no limite (digitação tipica)
            eyes_observable = False

        head_down_pose = head_st in (
            "head_down_short",
            "head_down_persistent",
            "head_supported",
        )
        head_down = head_down_pose or (
            pitch is not None and float(pitch) > pitch_thr
        )
        # Digitar / olhar teclado: EAR na faixa PARCIAL (abaixo do thr de “fechado”,
        # acima do fechamento profundo) é evidência geométrica fraca — típica de
        # gaze/look-down com cabeça ainda “forward”, não de sono. Pausar acumulador.
        # Sono aparente exige EAR profundo (<= thr*0.5). Gate head_down_pose mantido.
        deep_close_thr = ear_thr * 0.50
        # "Fechamento parcial" tende a aparecer em olhar/teclado com cabeça ainda
        # "forward" (não é sono profundo). Para preservar o contrato dos testes:
        # - head_forward/facing_forward: pausa (não acumula)
        # - pose_inconclusive (oclusão / ausência de evidência): acumulador continua
        if ear is not None and deep_close_thr < float(ear) < ear_thr and (
            head_down_pose or head_st in ("head_forward", "facing_forward")
        ):
            eyes_observable = False
            cache.eyes_last_tick = None
        elif head_down_pose and pitch is not None and float(pitch) > pitch_thr * 0.70:
            if ear is not None and float(ear) > deep_close_thr:
                eyes_observable = False
                cache.eyes_last_tick = None
        eyes_closed_valid = bool(eyes_closed and eyes_observable)
        if eyes_closed_valid:
            if cache.eyes_last_tick is not None:
                cache.eyes_closed_accum_seconds += max(0.0, now - cache.eyes_last_tick)
            cache.eyes_last_tick = now
            if cache.eyes_closed_since is None:
                cache.eyes_closed_since = now
        elif eyes_observable and ear is not None and not eyes_closed:
            # Olhos verdadeiramente abertos e observáveis → reset
            cache.eyes_closed_accum_seconds = 0.0
            cache.eyes_closed_since = None
            cache.eyes_last_tick = None
        else:
            # Observação inválida: pausar sem incrementar nem resetar indevidamente
            cache.eyes_last_tick = None
            cache.eyes_observation_paused = True

        if head_down:
            if cache.head_down_since is None:
                cache.head_down_since = now
            # duração vem de head_down_since (tick no pose); não somar de novo aqui
            cache.head_down_accum_seconds = max(
                float(cache.head_down_accum_seconds or 0.0),
                now - float(cache.head_down_since),
            )
            cache.head_down_last_tick = now
        else:
            cache.head_down_accum_seconds = 0.0
            cache.head_down_since = None
            cache.head_down_last_tick = None

        eyes_closed_s = float(cache.eyes_closed_accum_seconds or 0.0)
        possible_after = float(getattr(self.settings, "drowsiness_possible_after_seconds", 6) or 6)
        probable_after = float(getattr(self.settings, "drowsiness_probable_after_seconds", 30) or 30)
        if head_down_pose:
            mult = float(
                getattr(self.settings, "drowsiness_head_down_possible_multiplier", 2.0) or 2.0
            )
            possible_after = possible_after * mult
            probable_after = max(
                probable_after,
                float(
                    getattr(self.settings, "drowsiness_head_down_probable_seconds", 45.0) or 45.0
                ),
            )
        cooldown = float(getattr(self.settings, "drowsiness_cooldown_seconds", 20) or 20)

        # Sonolência: exige olhos observáveis; cabeça baixa sozinha NÃO gera possible/probable
        if not eyes_observable:
            drow = {
                "state": "inconclusive",
                "confidence": 0.2,
                "duration_seconds": round(eyes_closed_s, 2),
                "sample_count": len(cache.attn_samples),
                "reasons": ["eyes_observation_invalid"],
                "observation_paused": True,
                "contributing_signals": {
                    "landmarks_quality": lq,
                    "observation_quality": overall,
                    "face_occlusion": occ,
                    "head_state": head_st,
                },
            }
        elif ear is None:
            drow = {
                "state": "inconclusive",
                "confidence": 0.2,
                "duration_seconds": round(eyes_closed_s, 2),
                "sample_count": len(cache.attn_samples),
                "reasons": ["eyes_not_observable"],
                "observation_paused": True,
            }
        elif overall < min_q_dr:
            drow = {
                "state": "inconclusive",
                "confidence": 0.2,
                "duration_seconds": round(eyes_closed_s, 2),
                "sample_count": len(cache.attn_samples),
                "reasons": ["insufficient_observation_quality"],
                "observation_paused": True,
            }
        else:
            head_supported = head_st == "head_supported"
            prev_drow = cache.drowsiness_state
            # Cooldown só após ABRIR os olhos (evita rebaixar probable→possible a cada frame)
            cooldown_active = (now < cache.drowsiness_cooldown_until) and (not eyes_closed)
            st = evaluate_apparent_drowsiness(
                eyes_closed_seconds=eyes_closed_s,
                head_pitch=float(pitch or 0.0),
                head_supported=head_supported,
                low_motion=False,
                sample_count=max(5, len(cache.attn_samples)),
                observation_quality=overall,
                min_duration_seconds=probable_after,
                possible_after_seconds=possible_after,
                min_samples=5,
                min_quality=min_q_dr,
                cooldown_active=cooldown_active,
            )
            if eyes_closed_s < 2.5:
                st.state = "none"
                st.reasons = ["brief_blink_or_closed"]
            elif not eyes_closed:
                # sem olhos fechados → nunca possible/probable só por cabeça
                st.state = "none"
                if head_down:
                    st.reasons = ["head_down_without_closed_eyes_not_drowsiness"]
            elif eyes_closed_s >= probable_after:
                st.state = "probable"
                if "eyes_closed_duration" not in (st.reasons or []):
                    st.reasons = list(st.reasons or []) + ["eyes_closed_duration"]
                st.confidence = max(float(st.confidence or 0.0), 0.75)
            elif st.state == "none" and eyes_closed_s >= possible_after:
                st.state = "possible"
                st.reasons = list(st.reasons or []) + ["eyes_closed_duration"]
            elif 2.5 <= eyes_closed_s < possible_after and eyes_closed:
                st.state = "none"
                st.reasons = ["prolonged_eye_closure_observed"]
            # Armar cooldown apenas ao sair de sonolência (olhos abrem)
            if prev_drow in ("possible", "probable") and st.state == "none" and not eyes_closed:
                cache.drowsiness_cooldown_until = now + cooldown
            drow = {
                "state": st.state,
                "confidence": round(st.confidence, 3),
                "duration_seconds": round(eyes_closed_s, 2),
                "sample_count": len(cache.attn_samples),
                "reasons": st.reasons,
                "contributing_signals": st.contributing_signals,
                "descriptive_label": (
                    "prolonged_eye_closure_observed"
                    if 2.5 <= eyes_closed_s < possible_after and eyes_closed
                    else None
                ),
            }
        cache.drowsiness_state = drow["state"]

        # PERCLOS experimental (não altera decisor)
        if bool(getattr(self.settings, "experimental_perclos_enabled", False)):
            if ear is not None and overall >= min_q_dr and eyes_observable:
                cache.perclos_samples.append((now, bool(eyes_closed)))
            drow["perclos"] = self._compute_perclos(cache, now)
        else:
            drow["perclos"] = {
                "perclos_experimental": True,
                "perclos_enabled": False,
                "perclos_state": "disabled",
            }

        if overall < min_q_attn:
            derived = self._low_attention_derived_reasons(cache, drowsiness_state=drow["state"])
            attn_state = "low" if derived else "inconclusive"
            if cache.attention_state != attn_state:
                cache.attention_state = attn_state
                cache.attention_started = now
            dur = (now - cache.attention_started) if cache.attention_started else 0.0
            attn = {
                "state": attn_state,
                "confidence": 0.35 if derived else 0.0,
                "duration_seconds": round(dur, 2),
                "sample_count": len(cache.attn_samples),
                "contributing_signals": {"observation_quality": overall},
                "reasons": ["insufficient_observation_quality"] + derived,
            }
            return attn, drow

        phone_prob = (cache.phone or {}).get("state") == "probable_phone_interaction"
        attn_eval = evaluate_visual_attention(
            head_yaw=float(yaw or 0.0),
            head_pitch=float(pitch or 0.0),
            gaze_reliable=gaze_reliable,
            gaze_toward_front=None
            if not gaze_reliable
            else max(0.0, 1.0 - abs(float(gaze_h or yaw or 0.0)) / 0.6),
            coverage=1.0,
            probable_phone=phone_prob,
            drowsiness_state=drow["state"],
            observation_quality=overall,
            min_quality=min_q_attn,
        )

        # Cabeça baixa curta: não forçar low ainda (olhar breve)
        if head_st == "head_down_short" or (
            head_down and cache.head_down_since and (now - cache.head_down_since) < 2.5
        ):
            if attn_eval.state == "low" and "probable_phone" not in (attn_eval.reasons or []):
                attn_eval.state = "moderate"
                attn_eval.reasons = list(attn_eval.reasons) + ["short_look_down"]

        # Derivação pedagógica: celular / olhos / cabeça baixa persistente → low
        derived = self._low_attention_derived_reasons(cache, drowsiness_state=drow["state"])
        if derived:
            attn_eval.state = "low"
            attn_eval.score = min(float(attn_eval.score or 0.4), 0.40)
            attn_eval.reasons = list(attn_eval.reasons or []) + derived

        if cache.attention_state != attn_eval.state:
            cache.attention_state = attn_eval.state
            cache.attention_started = now
        dur = (now - cache.attention_started) if cache.attention_started else 0.0
        cache.attn_samples.append((now, attn_eval.state, float(attn_eval.score or 0.0)))
        win = float(getattr(self.settings, "visual_attention_window_seconds", 10) or 10)
        while cache.attn_samples and now - cache.attn_samples[0][0] > win:
            cache.attn_samples.popleft()

        attn = {
            "state": attn_eval.state,
            "confidence": round(float(attn_eval.score or 0.0), 3),
            "duration_seconds": round(dur, 2),
            "sample_count": len(cache.attn_samples),
            "contributing_signals": {
                "head_forward": round(max(0.0, 1.0 - abs(float(yaw or 0.0)) / 0.5), 3)
                if yaw is not None
                else None,
                "gaze_forward": round(max(0.0, 1.0 - abs(float(gaze_h or 0.0)) / 0.6), 3)
                if gaze_reliable
                else None,
                "observation_quality": round(overall, 3),
                "head_state": head_st,
                "head_down_duration_seconds": round(float(cache.head_down_accum_seconds or 0.0), 2),
            },
            "reasons": attn_eval.reasons,
        }
        return attn, drow

    def _low_attention_derived_reasons(
        self, cache: TrackAnalyticsCache, *, drowsiness_state: str
    ) -> List[str]:
        """Sinais paralelos que, pedagogicamente, implicam baixa atenção à aula."""
        derived: List[str] = []
        phone_state = str((cache.phone or {}).get("state") or "")
        if phone_state in ("possible_phone_interaction", "probable_phone_interaction"):
            derived.append("derived_from_phone")
        if drowsiness_state in ("possible", "probable"):
            derived.append("derived_from_drowsiness")
        head_st = str((cache.head_state or {}).get("state") or "")
        hd_min = float(getattr(self.settings, "head_down_event_min_seconds", 8.0) or 8.0)
        hd_accum = float(cache.head_down_accum_seconds or 0.0)
        occ_st = str((cache.face_occlusion or {}).get("state") or "none")
        if bool(getattr(self.settings, "head_down_suppress_when_occlusion", True)) and occ_st in (
            "possible_face_occlusion_by_hand",
            "persistent_possible_face_occlusion",
        ):
            pass  # oclusão: não derivar baixa atenção de cabeça baixa
        elif head_st in ("head_down_persistent", "head_supported") or hd_accum >= hd_min:
            derived.append("derived_from_head_down")
        return derived

    def _compute_perclos(self, cache: TrackAnalyticsCache, now: float) -> Dict[str, Any]:
        window = float(getattr(self.settings, "experimental_perclos_window_seconds", 60) or 60)
        min_cov = float(getattr(self.settings, "experimental_perclos_min_coverage", 0.50) or 0.50)
        while cache.perclos_samples and now - cache.perclos_samples[0][0] > window:
            cache.perclos_samples.popleft()
        if len(cache.perclos_samples) < 2:
            return {
                "perclos_experimental": True,
                "perclos_enabled": True,
                "perclos_60s": None,
                "perclos_valid_coverage": 0.0,
                "perclos_observable_seconds": 0.0,
                "perclos_window_seconds": window,
                "perclos_state": "inconclusive",
            }
        samples = list(cache.perclos_samples)
        obs = 0.0
        closed = 0.0
        for i in range(1, len(samples)):
            dt = max(0.0, samples[i][0] - samples[i - 1][0])
            obs += dt
            if samples[i - 1][1]:
                closed += dt
        coverage = obs / window if window > 0 else 0.0
        if coverage < min_cov or obs <= 0:
            state = "inconclusive"
            ratio = None
        else:
            ratio = closed / obs
            state = "computed"
        return {
            "perclos_experimental": True,
            "perclos_enabled": True,
            "perclos_60s": None if ratio is None else round(ratio, 4),
            "perclos_valid_coverage": round(coverage, 3),
            "perclos_observable_seconds": round(obs, 2),
            "perclos_window_seconds": window,
            "perclos_state": state,
        }

    def _update_phones(
        self,
        frame: np.ndarray,
        person_boxes: Dict[str, BBox],
        tracks_out: List[dict],
        now: float,
        wrists: Optional[Dict[str, List[Tuple[float, float]]]] = None,
        head_looking_down: Optional[Dict[str, bool]] = None,
        face_bboxes: Optional[Dict[str, BBox]] = None,
    ) -> None:
        if self._phone_status != "available" or self._phone_associator is None:
            self._phone_detector_debug = {
                "provider": "yolo",
                "status": self._phone_status,
                "reason": self._phone_reason,
                "detections": [],
            }
            for t in tracks_out:
                tid = t.get("person_track_id") or t["track_id"]
                t["phone"] = {
                    "status": self._phone_status,
                    "state": "not_detected",
                    "provider": "yolo",
                    "confidence": None,
                    "duration_seconds": None,
                    "reasons": [self._phone_reason] if self._phone_reason else [],
                    "reason": self._phone_reason,
                }
                self._get_cache(tid).phone = t["phone"]
            return
        try:
            from app.vision.phone_yolo import detect_phones, get_phone_detector_debug

            phones = detect_phones(
                frame,
                person_boxes=person_boxes,
                wrists=wrists,
            )
            self._phone_detector_debug = get_phone_detector_debug()
            phone_boxes = [(p[0], p[1], p[2], p[3], p[4] if len(p) > 4 else 0.5) for p in phones]
            states = self._phone_associator.update(
                now=now,
                person_tracks=person_boxes,
                phone_boxes=phone_boxes,
                wrists=wrists or {},
                head_looking_down=head_looking_down or {},
                face_bboxes=face_bboxes or {},
            )
            by_id = {s.person_track_id: s for s in states}
            for t in tracks_out:
                tid = t.get("person_track_id") or t["track_id"]
                s = by_id.get(tid)
                if not s:
                    t["phone"] = {
                        "status": "available",
                        "state": "not_detected" if not phone_boxes else "phone_visible",
                        "provider": "yolo",
                        "confidence": 0.2 if phone_boxes else 0.0,
                        "duration_seconds": 0.0,
                        "reasons": ["phone_visible_only"] if phone_boxes else [],
                    }
                else:
                    level = s.interaction_level
                    if level in ("none",):
                        level = "not_detected"
                    t["phone"] = {
                        "status": "available",
                        "state": level,
                        "provider": "yolo",
                        "confidence": round(s.confidence, 3),
                        "duration_seconds": round(s.duration_seconds, 2),
                        "phone_in_hand": bool(getattr(s, "phone_in_hand", False)),
                        "ambiguous": bool(getattr(s, "ambiguous", False)),
                        "reasons": s.reasons,
                    }
                self._get_cache(tid).phone = t["phone"]
                # refresh observability phone_visibility
                if t.get("observation_quality") and t["phone"].get("state") not in (
                    "not_detected",
                    None,
                ):
                    t["observation_quality"]["phone_visibility"] = 0.7
        except Exception as e:
            self._phone_detector_debug = {"provider": "yolo", "status": "error", "reason": str(e)}
            for t in tracks_out:
                tid = t.get("person_track_id") or t["track_id"]
                t["phone"] = {
                    "status": "error",
                    "state": "not_detected",
                    "provider": "yolo",
                    "reason": str(e),
                    "reasons": [str(e)],
                }

    def _short_to_persistent_seconds(self) -> float:
        return float(
            getattr(self.settings, "head_down_short_to_persistent_seconds", None)
            or getattr(self.settings, "head_down_event_min_seconds", 8.0)
            or 8.0
        )

    def _head_state_for_track(self, cache: TrackAnalyticsCache, *, now: float) -> Dict[str, Any]:
        """Card/UI: duração contínua; não mostrar inconclusivo se look-down ainda ativo."""
        hs = dict(cache.head_state or {})
        state = str(hs.get("state") or "pose_inconclusive")
        dur = float(cache.head_down_accum_seconds or 0.0)
        if cache.head_down_since is not None:
            dur = max(dur, now - float(cache.head_down_since))
        occ = str((cache.face_occlusion or {}).get("state") or "none")
        occ_reasons = list((cache.face_occlusion or {}).get("reasons") or [])
        strong_occ = occ in (
            "possible_face_occlusion_by_hand",
            "persistent_possible_face_occlusion",
        ) and any(
            any(k in str(r) for k in ("wrist_near_face", "elbow_raised", "wrist_in_head_zone", "occlusion_hold"))
            for r in occ_reasons
        )
        promote = self._short_to_persistent_seconds()
        if not strong_occ and cache.head_down_since is not None and dur > 0.4:
            if dur >= promote:
                state = "head_down_persistent"
            elif state not in ("head_down_short", "head_down_persistent", "head_supported"):
                state = "head_down_short"
            elif state == "pose_inconclusive":
                state = "head_down_short" if dur < promote else "head_down_persistent"
            hs = {
                **hs,
                "state": state,
                "confidence": max(float(hs.get("confidence") or 0.0), 0.55),
                "reasons": list(hs.get("reasons") or []) + ["ui_continuity_head_down"],
                "note": hs.get("note") or "ui_continuity",
            }
        hs["duration_seconds"] = round(dur if state.startswith("head_down") or state == "head_supported" else 0.0, 2)
        return hs

    def _tick_head_down_duration(self, cache: TrackAnalyticsCache, *, now: float) -> None:
        """Alinha head_down_since ao estado do pose (mesmo sem face)."""
        hs = str((cache.head_state or {}).get("state") or "")
        reasons = list((cache.head_state or {}).get("reasons") or [])
        q_status = str((cache.observation_quality or {}).get("status") or "")
        if hs in ("head_down_short", "head_down_persistent", "head_supported"):
            if cache.head_down_since is None:
                cache.head_down_since = now
            dur = now - float(cache.head_down_since)
            cache.head_down_accum_seconds = dur
            cache.head_down_last_tick = now
            promote_after = self._short_to_persistent_seconds()
            if hs == "head_down_short" and dur >= promote_after:
                cache.head_state = {
                    **dict(cache.head_state or {}),
                    "state": "head_down_persistent",
                    "duration_seconds": round(dur, 2),
                }
        elif hs in ("head_forward", "head_turned"):
            # partially_observable sozinho NÃO conta como face_gone: no LIVE a
            # qualidade fica partial com rosto grande à câmera e regravava
            # head_down após pose forward (evento sticky 23s+/minutos).
            face_gone = (cache.facial_features or {}).get("status") in (
                "inconclusive",
                "unavailable",
                "error",
            ) or cache.eyes_unobservable_since is not None
            if face_gone and cache.head_down_since is not None:
                # Mantém acumulador: pose mentiu "forward" sem face observável plena
                hold = float(
                    getattr(self.settings, "head_down_inconclusive_hold_seconds", 4.0) or 4.0
                )
                last = float(cache.head_down_last_tick or cache.head_down_since)
                if (now - last) <= hold:
                    dur = now - float(cache.head_down_since)
                    cache.head_down_accum_seconds = dur
                    cache.head_down_last_tick = now
                    promote_after = self._short_to_persistent_seconds()
                    cache.head_state = {
                        **dict(cache.head_state or {}),
                        "state": (
                            "head_down_persistent" if dur >= promote_after else "head_down_short"
                        ),
                        "confidence": max(float((cache.head_state or {}).get("confidence") or 0.0), 0.55),
                        "reasons": list(reasons) + ["reject_forward_without_face"],
                        "duration_seconds": round(dur, 2),
                    }
                else:
                    cache.head_down_since = None
                    cache.head_down_accum_seconds = 0.0
                    cache.head_down_last_tick = None
            else:
                cache.head_down_since = None
                cache.head_down_accum_seconds = 0.0
                cache.head_down_last_tick = None
        elif hs == "pose_inconclusive":
            # Oclusão pura: zera. Flicker com geom look-down / qualidade parcial: hold.
            geom_continuity = any(
                str(r).startswith("nose_shoulder_ratio=")
                or "chest_keep" in str(r)
                or "hysteresis" in str(r)
                or "face_missing_untrusted_nose" in str(r)
                or "shoulders_without_face_look_down" in str(r)
                or "prefer_look_down" in str(r)
                for r in reasons
            )
            if "suppressed_by_face_occlusion" in reasons and not geom_continuity:
                cache.head_down_since = None
                cache.head_down_accum_seconds = 0.0
                cache.head_down_last_tick = None
            elif cache.head_down_since is not None and cache.head_down_last_tick is not None:
                hold = float(
                    getattr(self.settings, "head_down_inconclusive_hold_seconds", 4.0) or 4.0
                )
                gap = now - float(cache.head_down_last_tick)
                face_gone = (cache.facial_features or {}).get("status") in (
                    "inconclusive",
                    "unavailable",
                    "error",
                ) or cache.eyes_unobservable_since is not None
                # NÃO usar partially_observable aqui — reabria head_down sticky no LIVE.
                reasons_all = reasons + list((cache.pose or {}).get("reasons") or [])
                geom_hint = any(
                    str(r).startswith("nose_shoulder_ratio=") for r in reasons_all
                ) or "body_geom_look_down" in reasons_all or "face_missing_untrusted_nose" in reasons_all
                geom_hint = geom_hint or (
                    "shoulders_without_face_look_down" in reasons_all
                    and "ears_above_shoulders" in reasons_all
                )
                geom_hint = geom_hint or any(
                    x in reasons_all
                    for x in (
                        "head_down_hold_through_inconclusive",
                        "reject_forward_without_face",
                        "wrist_near_chest_keep_head_down",
                    )
                ) or any("hysteresis" in str(r) for r in reasons_all)
                if "suppressed_by_face_occlusion" in reasons and geom_continuity:
                    reasons = [r for r in reasons if r != "suppressed_by_face_occlusion"]
                    cache.head_state = {
                        **dict(cache.head_state or {}),
                        "reasons": list(reasons) + ["hold_despite_occlusion_geom"],
                    }
                if gap <= hold and (face_gone or geom_hint or geom_continuity):
                    dur = now - float(cache.head_down_since)
                    cache.head_down_accum_seconds = dur
                    cache.head_down_last_tick = now
                    promote_after = self._short_to_persistent_seconds()
                    new_st = (
                        "head_down_persistent" if dur >= promote_after else "head_down_short"
                    )
                    cache.head_state = {
                        **dict(cache.head_state or {}),
                        "state": new_st,
                        "confidence": max(float((cache.head_state or {}).get("confidence") or 0.0), 0.5),
                        "reasons": list((cache.head_state or {}).get("reasons") or reasons)
                        + ["head_down_hold_through_inconclusive"],
                        "duration_seconds": round(dur, 2),
                        "note": "continuity_hold",
                    }
                else:
                    cache.head_down_since = None
                    cache.head_down_accum_seconds = 0.0
                    cache.head_down_last_tick = None
            else:
                cache.head_down_since = None
                cache.head_down_accum_seconds = 0.0
                cache.head_down_last_tick = None

    def _body_head_geom_active(self, cache: TrackAnalyticsCache) -> bool:
        """True se pose corporal (nariz+ombros) indica look-down — não face mesh ausente."""
        reasons = list((cache.head_state or {}).get("reasons") or [])
        pose_reasons = list((cache.pose or {}).get("reasons") or [])
        all_r = reasons + pose_reasons
        if "face_missing_look_down_proxy" in all_r:
            return False
        if "wrist_near_prefer_occlusion" in all_r or "suppressed_by_face_occlusion" in all_r:
            return False
        if any(str(r).startswith("nose_shoulder_ratio=") for r in all_r):
            return True
        if "body_geom_look_down" in all_r:
            return True
        if "face_missing_untrusted_nose" in all_r:
            return True
        if "wrist_near_chest_keep_head_down" in all_r:
            return True
        if any("hysteresis" in str(r) for r in all_r):
            return True
        if "shoulders_without_face_look_down" in all_r and "ears_above_shoulders" in all_r:
            return True
        return False

    def _arbitrate_occlusion_vs_head(
        self, cache: TrackAnalyticsCache, *, face_visible: bool, now: float
    ) -> None:
        """Porta única: oclusão > inconclusivo > cabeça baixa (ver occlusion_head_arbitration)."""
        from app.pipeline.occlusion_head_arbitration import resolve_occlusion_vs_head_down

        if not face_visible:
            if cache.eyes_unobservable_since is None:
                cache.eyes_unobservable_since = now
        else:
            # Face voltou: limpa oclusão genérica sem punho
            occ = cache.face_occlusion or {}
            reasons = list(occ.get("reasons") or [])
            has_wrist = any("wrist" in str(r) for r in reasons)
            if (
                str(occ.get("state") or "none")
                in ("possible_face_occlusion_by_hand", "persistent_possible_face_occlusion")
                and not has_wrist
                and any("face_not_observable" in str(r) for r in reasons)
            ):
                cache.face_occlusion = {
                    "state": "none",
                    "confidence": 0.0,
                    "reasons": ["cleared_face_visible"],
                }

        result = resolve_occlusion_vs_head_down(
            face_visible=face_visible,
            head_state=dict(cache.head_state or {}),
            face_occlusion=dict(cache.face_occlusion or {}),
            facial_features=cache.facial_features,
            hands=cache.hands,
            body_head_geom=self._body_head_geom_active(cache),
            now=now,
            head_down_since=cache.head_down_since,
            head_down_accum_seconds=float(cache.head_down_accum_seconds or 0.0),
            short_to_persistent_seconds=self._short_to_persistent_seconds(),
            require_landmarks_quality=float(
                getattr(self.settings, "head_down_require_landmarks_quality", 0.45) or 0.45
            ),
            suppress_when_occlusion=bool(
                getattr(self.settings, "head_down_suppress_when_occlusion", True)
            ),
            allow_face_missing_proxy=bool(
                getattr(self.settings, "head_down_allow_face_missing_proxy", False)
            ),
        )
        prev_since = cache.head_down_since
        prev_reasons = list((cache.head_state or {}).get("reasons") or [])
        cache.head_state = dict(result.head_state)
        cache.face_occlusion = dict(result.face_occlusion)
        if result.suppressed_head_down:
            # Continuidade look-down só com face realmente ausente + geom.
            # partially_observable sozinho NÃO reabre head_down (sticky LIVE).
            geom_keep = any(
                str(r).startswith("nose_shoulder_ratio=")
                or "chest_keep" in str(r)
                or "hysteresis" in str(r)
                or "face_missing_untrusted_nose" in str(r)
                or "shoulders_without_face" in str(r)
                for r in prev_reasons + list((cache.head_state or {}).get("reasons") or [])
            )
            face_really_gone = (cache.facial_features or {}).get("status") in (
                "inconclusive",
                "unavailable",
                "error",
            ) or cache.eyes_unobservable_since is not None
            if prev_since is not None and geom_keep and face_really_gone:
                cache.head_down_since = prev_since
            else:
                cache.head_down_since = None
                cache.head_down_accum_seconds = 0.0
                cache.head_down_last_tick = None
        elif str((cache.head_state or {}).get("state") or "") in (
            "head_down_short",
            "head_down_persistent",
            "head_supported",
        ):
            if cache.head_down_since is None and result.decision in (
                "head_down_body_geom",
                "legacy_face_missing_proxy",
            ):
                cache.head_down_since = float(cache.eyes_unobservable_since or now)
            dur = float((cache.head_state or {}).get("duration_seconds") or 0.0)
            if dur > 0:
                cache.head_down_accum_seconds = max(float(cache.head_down_accum_seconds or 0.0), dur)

    def _apply_face_not_observable_occlusion(
        self, cache: TrackAnalyticsCache, *, face_visible: bool, now: float
    ) -> None:
        """Compat: delega à arbitragem única oclusão vs cabeça baixa."""
        self._arbitrate_occlusion_vs_head(cache, face_visible=face_visible, now=now)

    def _suppress_false_occlusion_if_face_clear(
        self, cache: TrackAnalyticsCache, *, face_visible: bool, now: Optional[float] = None
    ) -> None:
        """
        Limpa oclusão só quando landmarks estão claros E não há evidência recente de punho.
        MediaPipe prevê landmarks mesmo com mão na cara — não usar landmarks sozinhos
        para anular oclusão confirmada por punho.
        """
        if not face_visible:
            return
        if not bool(getattr(self.settings, "face_occlusion_suppress_when_landmarks_clear", True)):
            return
        # G: olhos fechados (eyes_unobservable) com face VISÍVEL não devem travar
        # limpeza de oclusão fantasma — só bloqueia se há evidência de mão.
        if cache.eyes_unobservable_since is not None:
            if cache.hand_near_since is not None or str(
                (cache.hands or {}).get("state") or ""
            ) == "hand_near_face":
                return
            # sem punho: pode limpar oclusão indevida sob olhos fechados
        # Punho ainda confirmado ou no hold → nunca limpar (evita alerta sumir em ~10s)
        if cache.hand_near_since is not None:
            return
        hand_hold = float(
            getattr(self.settings, "face_occlusion_clear_hold_seconds", 4.0) or 4.0
        )
        face_missing_hold = float(
            getattr(self.settings, "face_occlusion_face_missing_hold_seconds", 15.0) or 15.0
        )
        effective_hold = max(hand_hold, face_missing_hold) if not face_visible else hand_hold
        ts = float(now if now is not None else time.time())
        if cache.hand_near_last_seen is not None and (ts - float(cache.hand_near_last_seen)) < effective_hold:
            return
        if str((cache.hands or {}).get("state") or "") == "hand_near_face":
            return
        # Continuity: oclusão com reason de hold/wrist não é anulada por landmarks
        reasons_early = list((cache.face_occlusion or {}).get("reasons") or [])
        if any(
            x in str(r)
            for r in reasons_early
            for x in ("wrist", "elbow", "occlusion_hold", "face_missing_continuity", "head_zone")
        ):
            return
        ff = cache.facial_features or {}
        if ff.get("status") != "available":
            return
        lq = float(ff.get("landmarks_quality") or 0.0)
        ear = ff.get("average_eye_openness")
        # Exigir landmarks realmente bons (mão na cara costuma baixar qualidade)
        if lq < 0.62 or ear is None:
            return
        occ = str((cache.face_occlusion or {}).get("state") or "none")
        if occ not in (
            "possible_face_occlusion_by_hand",
            "persistent_possible_face_occlusion",
        ):
            return
        # Só limpa oclusão sem reason de wrist (nunca anular wrist_near com landmarks)
        reasons = list((cache.face_occlusion or {}).get("reasons") or [])
        if any("wrist" in str(r) for r in reasons):
            return
        cache.hand_near_since = None
        cache.hand_near_last_seen = None
        cache.hand_near_candidate_since = None
        cache.hands = dict(cache.hands or {})
        cache.hands["state"] = "not_near_face"
        cache.face_occlusion = {
            "state": "none",
            "confidence": 0.0,
            "reasons": ["suppressed_face_landmarks_clear"],
            "note": "eyes_and_landmarks_observable",
        }

    def _apply_pitch_head_state(
        self, cache: TrackAnalyticsCache, *, face_visible: bool, now: float
    ) -> None:
        if not face_visible:
            return
        # Oclusão ativa: pitch não promove cabeça baixa
        occ = str((cache.face_occlusion or {}).get("state") or "none")
        if occ in ("possible_face_occlusion_by_hand", "persistent_possible_face_occlusion"):
            return
        from app.pipeline.occlusion_head_arbitration import pitch_may_promote_head_down

        thr = float(getattr(self.settings, "head_down_pitch_threshold", 0.45) or 0.45)
        min_lq = float(getattr(self.settings, "head_down_require_landmarks_quality", 0.45) or 0.45)
        ff = cache.facial_features or {}
        if not pitch_may_promote_head_down(
            ff, pitch_threshold=thr, require_landmarks_quality=min_lq
        ):
            return
        hs = str((cache.head_state or {}).get("state") or "pose_inconclusive")
        if hs in ("head_down_short", "head_down_persistent", "head_supported"):
            return
        pitch = float(ff.get("pitch") or 0.0)
        dur = (now - cache.head_down_since) if cache.head_down_since else 0.0
        promote_after = self._short_to_persistent_seconds()
        new_state = "head_down_persistent" if dur >= promote_after else "head_down_short"
        reasons = list((cache.head_state or {}).get("reasons") or [])
        reasons.append(f"facial_pitch={pitch:.2f}")
        cache.head_state = {
            **dict(cache.head_state or {}),
            "state": new_state,
            "confidence": max(float((cache.head_state or {}).get("confidence") or 0.0), 0.68),
            "reasons": reasons,
        }
        if cache.head_down_since is None:
            cache.head_down_since = now

    def _suppress_occlusion_for_phone(
        self, tracks_out: List[dict], frame: np.ndarray, now: float
    ) -> None:
        """Celular associado perto da pessoa não deve gerar oclusão facial por punho."""
        expr_mode = str(getattr(self.settings, "module_expression_mode", "disabled")).lower()
        lm_mode = str(getattr(self.settings, "module_face_landmarks_mode", "disabled")).lower()
        pose_mode = str(getattr(self.settings, "module_pose_mode", "disabled")).lower()
        fusion_mode = str(getattr(self.settings, "module_temporal_fusion_mode", "disabled")).lower()
        a_iv = float(getattr(self.settings, "analytics_interval_seconds", 0.5) or 0.5)

        for t in tracks_out:
            ph = t.get("phone") or {}
            state = str(ph.get("state") or "not_detected")
            if state not in PHONE_OCCLUSION_SUPPRESS_STATES:
                continue

            tid = str(t.get("person_track_id") or t.get("track_id"))
            cache = self._get_cache(tid)
            occ = str((cache.face_occlusion or {}).get("state") or "none")
            if occ not in (
                "possible_face_occlusion_by_hand",
                "persistent_possible_face_occlusion",
            ):
                continue

            cache.hand_near_since = None
            cache.hand_near_last_seen = None
            cache.hand_near_candidate_since = None
            cache.hands = dict(cache.hands or {})
            cache.hands["state"] = "not_near_face"
            cache.face_occlusion = {
                "state": "none",
                "confidence": 0.0,
                "reasons": ["suppressed_phone_near_person"],
                "note": "phone_detected_near_person",
            }
            t["face_occlusion"] = dict(cache.face_occlusion)
            t["hands"] = dict(cache.hands)

            ident = t.get("identity") or {}
            face_visible = bool(ident.get("face_visible"))
            fb = t.get("face_bbox")
            face_bbox = tuple(fb[:4]) if fb and len(fb) >= 4 else None
            crop = _clip_crop(frame, face_bbox) if face_bbox else None

            if cache.observation_quality:
                cache.observation_quality = self._enrich_quality_from_pose(
                    cache.observation_quality,
                    pose=cache.pose,
                    face_occlusion=cache.face_occlusion,
                    phone=cache.phone,
                    face_visible=face_visible,
                    person_visible=True,
                )
                t["observation_quality"] = dict(cache.observation_quality)

            if face_visible and expr_mode != "disabled" and crop is not None:
                cache.expression = self._compute_expression(crop, cache, now)
                t["expression"] = dict(cache.expression)

            if lm_mode != "disabled" or pose_mode != "disabled" or fusion_mode != "disabled":
                if now - cache.last_attention_ts >= a_iv:
                    cache.visual_attention, cache.drowsiness = self._compute_attention_drowsiness(
                        cache, now, face_visible=face_visible
                    )
                    cache.last_attention_ts = now
                t["visual_attention"] = dict(cache.visual_attention)
                t["drowsiness"] = dict(cache.drowsiness)

    def _close_all_events_for_track(self, tid: str, now: float) -> None:
        for key in list(self._open_events.keys()):
            if not key.startswith(str(tid) + ":"):
                continue
            ev = self._open_events.pop(key)
            ev["ended_at"] = now
            ev["duration_seconds"] = round(now - ev["started_at"], 2)
            ev["lifecycle"] = "closed"
            self._emit_event("closed", ev)

    def _provenance(self) -> Dict[str, Any]:
        try:
            from app.runtime_mode import get_runtime_mode, is_demo

            runtime = get_runtime_mode().value
            simulated = is_demo()
        except Exception:
            runtime = "rtsp"
            simulated = False
        return {
            "provider": "realtime_analytics_engine",
            "model_name": "fusion-rules",
            "model_version": "analytics-v1",
            "rule_engine_version": getattr(self.settings, "rule_engine_version", "rules-v0-baseline"),
            "threshold_profile": getattr(self.settings, "threshold_profile", "presence-yaml-2026-07-23"),
            "camera_calibration_version": getattr(
                self.settings, "camera_calibration_version", "uncalibrated"
            ),
            "runtime_mode": runtime,
            "is_simulated": bool(simulated),
        }

    def _emit_event(self, lifecycle: str, event: Dict[str, Any]) -> None:
        msg = {
            "type": f"behavioral_event_{lifecycle}",
            "payload": event,
            "runtime_mode": event.get("provenance", {}).get("runtime_mode"),
            "is_simulated": event.get("provenance", {}).get("is_simulated", False),
        }
        self._ws_events.append(msg)
        if self._event_sink:
            try:
                self._event_sink(lifecycle, event)
            except Exception as e:
                logger.warning("analytics_event_sink_error", error=str(e))

    SENSITIVE_EVENT_TYPES = frozenset(
        {
            "possible_drowsiness",
            "probable_drowsiness",
            "possible_phone_interaction",
            "probable_phone_interaction",
            "low_visual_attention",
            "head_down_persistent",
        }
    )
    TECHNICAL_EVENT_TYPES = frozenset({"face_occluded_persistent"})

    def _attribution_for_track(self, track, etype):
        identity = track.get("identity") or {}
        id_state = str(identity.get("identity_state") or "unknown")
        sid = identity.get("student_id") or track.get("student_id")
        bcc = float(identity.get("body_continuity_confidence") or 0.0)
        ambiguous = bool(identity.get("ambiguity_reasons") or identity.get("revalidation_required"))
        conf = float(identity.get("confidence") or identity.get("identity_confidence") or 0.0)
        now_ts = time.time()
        if etype in self.TECHNICAL_EVENT_TYPES or etype not in self.SENSITIVE_EVENT_TYPES:
            return {
                "attribution_status": "track_only",
                "candidate_student_id": sid,
                "confirmed_student_id": None,
                "attribution_confidence": conf,
                "attribution_updated_at": now_ts,
                "identity_state": id_state,
            }
        confirmable = id_state == "face_confirmed" or (
            id_state == "body_continuity" and bcc >= 0.45 and not ambiguous
        )
        if confirmable and sid:
            return {
                "attribution_status": "confirmed",
                "candidate_student_id": sid,
                "confirmed_student_id": sid,
                "attribution_confidence": conf if id_state == "face_confirmed" else bcc,
                "attribution_updated_at": now_ts,
                "identity_state": id_state,
            }
        if id_state in ("uncertain", "body_continuity", "face_confirmed") and sid:
            return {
                "attribution_status": "pending",
                "candidate_student_id": sid,
                "confirmed_student_id": None,
                "attribution_confidence": conf,
                "attribution_updated_at": now_ts,
                "identity_state": id_state,
            }
        return {
            "attribution_status": "track_only",
            "candidate_student_id": None,
            "confirmed_student_id": None,
            "attribution_confidence": 0.0,
            "attribution_updated_at": now_ts,
            "identity_state": id_state,
        }

    def live_event_buffer_snapshot(self):
        open_ev = [dict(e) for e in self._open_events.values()]
        closed = list(getattr(self, "_live_event_buffer", []))[-50:]
        return open_ev + closed

    def _sync_temporal_events(self, track, now):
        """Abre/atualiza/fecha eventos; attribution pendente se identity uncertain."""
        tid = str(track.get("track_id") or track.get("person_track_id") or "unknown")
        q = (track.get("observation_quality") or {}).get("status")
        quality = q or "unknown"
        identity = track.get("identity") or {}
        id_state = str(identity.get("identity_state") or "unknown")
        candidates = []

        cache = self._cache.get(tid)
        if cache and getattr(cache, "force_close_observation_gap", False):
            for key in list(self._open_events.keys()):
                if not key.startswith(tid + ":"):
                    continue
                etype = key.split(":", 1)[1]
                if "drowsiness" in etype or etype.startswith("possible_") or etype.startswith("probable_"):
                    ev = self._open_events.pop(key)
                    ev["ended_at"] = now
                    ev["closed_at"] = now
                    ev["duration_seconds"] = round(now - ev["started_at"], 2)
                    ev["lifecycle"] = "closed"
                    ev["end_reason"] = "inconclusive_observation_gap"
                    ev["is_inconclusive"] = True
                    self._emit_event("closed", ev)
                    self._live_event_buffer.append(dict(ev))
            cache.force_close_observation_gap = False

        dr = track.get("drowsiness") or {}
        if dr.get("state") == "possible":
            candidates.append(
                ("possible_drowsiness", "possible", float(dr.get("confidence") or 0.5), list(dr.get("reasons") or []))
            )
        elif dr.get("state") == "probable":
            candidates.append(
                ("probable_drowsiness", "probable", float(dr.get("confidence") or 0.7), list(dr.get("reasons") or []))
            )

        va = track.get("visual_attention") or {}
        if va.get("state") == "low" and float(va.get("duration_seconds") or 0) >= 8.0:
            candidates.append(
                (
                    "low_visual_attention",
                    "observed",
                    float(va.get("confidence") or 0.5),
                    list(va.get("reasons") or []),
                )
            )

        ph = track.get("phone") or {}
        if ph.get("status") == "available" and ph.get("state") in (
            "possible_phone_interaction",
            "probable_phone_interaction",
        ):
            candidates.append(
                (
                    str(ph["state"]),
                    "pending_review",
                    float(ph.get("confidence") or 0.5),
                    list(ph.get("reasons") or []),
                )
            )

        hs = track.get("head_state") or {}
        hd_dur = float(hs.get("duration_seconds") or 0.0)
        hd_min = float(getattr(self.settings, "head_down_event_min_seconds", 8.0) or 8.0)
        occ = track.get("face_occlusion") or {}
        occ_state = str(occ.get("state") or "none")
        occ_reasons = list(occ.get("reasons") or [])
        occ_has_wrist = any(
            any(
                k in str(r)
                for k in (
                    "wrist_near_face",
                    "elbow_raised",
                    "wrist_in_head_zone",
                    "occlusion_hold",
                    "face_missing_continuity",
                )
            )
            for r in occ_reasons
        )
        suppress_hd = bool(getattr(self.settings, "head_down_suppress_when_occlusion", True))
        occlusion_blocks_head_down = (
            suppress_hd and occ_state in (
                "possible_face_occlusion_by_hand",
                "persistent_possible_face_occlusion",
            )
            and occ_has_wrist
        )
        # Continuidade: usar since/accum mesmo se o frame atual piscou pose_inconclusive
        cache_pre = self._cache.get(tid)
        if cache_pre is not None and cache_pre.head_down_since is not None:
            cont = now - float(cache_pre.head_down_since)
            hd_dur = max(hd_dur, cont, float(cache_pre.head_down_accum_seconds or 0.0))
        hd_state = str(hs.get("state") or "")
        hd_active = hd_state in ("head_down_short", "head_down_persistent", "head_supported")
        hd_hold = hd_state == "pose_inconclusive" and hd_dur >= hd_min and (
            cache_pre is not None and cache_pre.head_down_since is not None
        )
        open_hd_key = f"{tid}:head_down_persistent"
        if (
            (hd_active or hd_hold or open_hd_key in self._open_events)
            and hd_dur >= hd_min
            and not occlusion_blocks_head_down
        ):
            candidates.append(
                (
                    "head_down_persistent",
                    "observed",
                    float(hs.get("confidence") or 0.5),
                    list(hs.get("reasons") or []) + [f"duration={hd_dur:.1f}s"],
                )
            )

        occ_dur = float(occ.get("duration_seconds") or 0.0)
        occ_persist = float(getattr(self.settings, "face_occlusion_persistent_seconds", 5.0) or 5.0)
        # Só evento de oclusão com evidência de mão/punho/continuidade (sem “rosto sumiu” sozinho)
        occ_has_hand_evidence = occ_has_wrist or any(
            any(k in str(r) for k in ("wrist", "elbow", "head_zone", "occlusion_hold", "face_missing_continuity"))
            for r in occ_reasons
        )
        if (
            occ.get("state") == "persistent_possible_face_occlusion"
            and occ_dur >= occ_persist
            and occ_has_hand_evidence
        ):
            candidates.append(
                (
                    "face_occluded_persistent",
                    "observed",
                    float(occ.get("confidence") or 0.4),
                    occ_reasons,
                )
            )

        cache = self._cache.get(tid)
        if cache is None:
            cache = self._get_cache(tid)

        active_types = {c[0] for c in candidates}
        _UPGRADE = {
            "probable_drowsiness": "possible_drowsiness",
            "probable_phone_interaction": "possible_phone_interaction",
        }
        for new_t, old_t in _UPGRADE.items():
            if new_t not in active_types:
                continue
            old_key = f"{tid}:{old_t}"
            new_key = f"{tid}:{new_t}"
            if old_key in self._open_events and new_key not in self._open_events:
                ev = self._open_events.pop(old_key)
                ev["event_type"] = new_t
                ev["status"] = "probable" if "drowsiness" in new_t else "pending_review"
                ev["lifecycle"] = "updated"
                ev["updated_at"] = now
                ev["duration_seconds"] = round(now - float(ev.get("started_at") or now), 2)
                ev.setdefault("reasons", [])
                if "upgraded_from_possible" not in ev["reasons"]:
                    ev["reasons"] = list(ev["reasons"]) + ["upgraded_from_possible"]
                self._open_events[new_key] = ev
                if cache is not None:
                    cache.event_clear_since.pop(old_t, None)
                self._emit_event("updated", {k: v for k, v in ev.items() if k != "_last_update_emit"})

        # Hold de fechamento: olhos/celular precisam de mais tempo (piscar não gera N episódios)
        def _clear_hold_for(etype: str) -> float:
            base = float(
                getattr(self.settings, "behavioral_event_clear_hold_seconds", None)
                or getattr(self.settings, "face_occlusion_clear_hold_seconds", 0.5)
                or 0.5
            )
            if "phone" in etype:
                return max(
                    base,
                    float(
                        getattr(self.settings, "behavioral_event_clear_hold_phone_seconds", 2.5)
                        or 2.5
                    ),
                )
            if "drowsiness" in etype:
                return max(base, float(getattr(self.settings, "behavioral_event_clear_hold_drowsiness_seconds", 4.0) or 4.0))
            if etype == "face_occluded_persistent":
                # Mão na cara: não fechar o evento por flicker de pose / rosto sumido
                return max(
                    base,
                    float(getattr(self.settings, "face_occlusion_clear_hold_seconds", 4.0) or 4.0),
                    float(
                        getattr(self.settings, "face_occlusion_face_missing_hold_seconds", 15.0)
                        or 15.0
                    ),
                    8.0,
                )
            if etype == "head_down_persistent":
                # Continuidade: um episódio de cabeça baixa não deve virar N pedaços
                return max(base, 12.0)
            return base

        for key in list(self._open_events.keys()):
            if not key.startswith(tid + ":"):
                continue
            etype = key.split(":", 1)[1]
            if etype in active_types:
                if cache is not None:
                    cache.event_clear_since.pop(etype, None)
                continue
            # possible ainda aberto mas já upgradamos — ignorar
            if etype in _UPGRADE.values() and any(
                u in active_types and _UPGRADE[u] == etype for u in _UPGRADE
            ):
                continue
            clear_hold = _clear_hold_for(etype)
            since = (cache.event_clear_since if cache is not None else {}).get(etype)
            if since is None:
                if cache is not None:
                    cache.event_clear_since[etype] = now
                continue
            if (now - float(since)) < clear_hold:
                continue
            if cache is not None:
                cache.event_clear_since.pop(etype, None)
            ev = self._open_events.pop(key)
            ev["ended_at"] = now
            ev["closed_at"] = now
            ev["duration_seconds"] = round(now - ev["started_at"], 2)
            ev["lifecycle"] = "closed"
            ev.setdefault("end_reason", "state_cleared")
            self._emit_event("closed", ev)
            self._live_event_buffer.append(dict(ev))

        for etype, status, conf, reasons in candidates:
            key = f"{tid}:{etype}"
            attr = self._attribution_for_track(track, etype)
            if key not in self._open_events:
                from app.utils.ids import generate_event_id

                prov = self._provenance()
                # Cabeça baixa: started_at = início real do look-down (não o instante do open)
                started = now
                if etype == "head_down_persistent":
                    if cache is not None and cache.head_down_since is not None:
                        started = float(cache.head_down_since)
                    elif hd_dur > 0:
                        started = now - float(hd_dur)
                ev = {
                    "event_id": generate_event_id(),
                    "event_type": etype,
                    "person_track_id": tid,
                    "track_id": tid,
                    "student_id": attr.get("confirmed_student_id"),
                    "identity_state": id_state,
                    "opened_at": now,
                    "started_at": started,
                    "updated_at": now,
                    "closed_at": None,
                    "ended_at": None,
                    "duration_seconds": round(max(0.0, now - started), 2),
                    "severity": "attention"
                    if ("drowsiness" in etype or "phone" in etype)
                    else "informational",
                    "confidence": conf,
                    "quality": quality,
                    "observation_quality": quality,
                    "status": status,
                    "lifecycle": "opened",
                    "reasons": reasons,
                    "end_reason": None,
                    "is_inconclusive": False,
                    "runtime_mode": prov.get("runtime_mode"),
                    "is_simulated": prov.get("is_simulated"),
                    "provenance": prov,
                    "requires_human_review": etype.endswith("phone_interaction") or "drowsiness" in etype,
                    "storage": "live_event_buffer",
                    **attr,
                }
                self._open_events[key] = ev
                self._emit_event("opened", ev)
                self._live_event_buffer.append(dict(ev))
                if cache is not None:
                    cache.episode_counts[etype] = int(cache.episode_counts.get(etype, 0)) + 1
                    ev["episode_index"] = cache.episode_counts[etype]
            else:
                ev = self._open_events[key]
                ev["updated_at"] = now
                ev["ended_at"] = now
                if etype == "head_down_persistent" and cache is not None and cache.head_down_since is not None:
                    # Reancora ao since contínuo (evita banner de 2s após 40s reais)
                    anchor = float(cache.head_down_since)
                    prev_start = float(ev.get("started_at") or now)
                    ev["started_at"] = min(prev_start, anchor)
                ev["duration_seconds"] = round(now - float(ev.get("started_at") or now), 2)
                ev["confidence"] = conf
                ev["observation_quality"] = quality
                ev["quality"] = quality
                ev["reasons"] = reasons
                ev["lifecycle"] = "updated"
                ev["identity_state"] = id_state
                if attr.get("attribution_status") == "confirmed" and ev.get("person_track_id") == tid:
                    ev.update(attr)
                    ev["student_id"] = attr.get("confirmed_student_id")
                elif ev.get("attribution_status") != "confirmed":
                    ev["candidate_student_id"] = attr.get("candidate_student_id")
                    ev["confirmed_student_id"] = None
                    ev["attribution_status"] = attr.get("attribution_status")
                    ev["student_id"] = None
                last_u = float(ev.get("_last_update_emit") or 0)
                if now - last_u >= 2.0:
                    ev["_last_update_emit"] = now
                    self._emit_event("updated", {k: v for k, v in ev.items() if k != "_last_update_emit"})

    def classroom_counts(self, tracks: List[dict], present_count: int) -> Dict[str, Any]:
        display_tracks = filter_displayable_tracks(tracks)
        visible = len(display_tracks)
        observable = sum(
            1
            for t in display_tracks
            if (t.get("observation_quality") or {}).get("status") == "observable"
        )
        inconclusive = sum(
            1
            for t in display_tracks
            if (t.get("observation_quality") or {}).get("status")
            in ("inconclusive", "low_quality", "error", "partially_observable", "not_visible")
        )
        # attention aggregate only when states exist and not not_implemented
        attn_vals = []
        for t in display_tracks:
            va = t.get("visual_attention") or {}
            if va.get("status") in ("not_implemented", "disabled"):
                continue
            if va.get("state") in ("high", "moderate", "low") and va.get("confidence") is not None:
                attn_vals.append(float(va["confidence"]))
        climate = None
        expr_states = []
        for t in display_tracks:
            ex = t.get("expression") or {}
            if ex.get("status") == "available" and ex.get("smoothed_state") and ex.get("smoothed_state") != "inconclusive":
                expr_states.append(ex["smoothed_state"])
        climate_distribution: Dict[str, int] = {}
        if expr_states:
            from collections import Counter

            c = Counter(expr_states)
            climate = c.most_common(1)[0][0]
            climate_distribution = dict(c)

        return {
            "present": present_count,
            "visible": visible,
            "visible_raw": len(tracks),
            "observable": observable,
            "inconclusive": inconclusive,
            "attention_index": round(sum(attn_vals) / len(attn_vals), 3) if attn_vals else None,
            "climate": climate,
            "climate_distribution": climate_distribution,
            "attention_available": bool(attn_vals),
            "climate_available": climate is not None,
        }
