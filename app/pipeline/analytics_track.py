"""Analytics por track no runtime real (RTSP/webcam) — sem mocks."""

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


def _clip_crop(frame: np.ndarray, bbox: BBox) -> Optional[np.ndarray]:
    ih, iw = frame.shape[:2]
    x, y, w, h = bbox[:4]
    x1, y1 = max(0, int(x)), max(0, int(y))
    x2, y2 = min(iw, x1 + int(w)), min(ih, y1 + int(h))
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
    """cv2.putText não desenha acentos — usar ASCII no bitmap."""
    repl = {
        "á": "a", "à": "a", "â": "a", "ã": "a", "ä": "a",
        "é": "e", "ê": "e", "è": "e",
        "í": "i", "ì": "i",
        "ó": "o", "ô": "o", "õ": "o", "ò": "o",
        "ú": "u", "ù": "u",
        "ç": "c",
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U", "Ç": "C",
        "ñ": "n", "Ñ": "N",
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
    observation_quality: Dict[str, Any] = field(default_factory=dict)
    facial_features: Dict[str, Any] = field(default_factory=dict)
    expression: Dict[str, Any] = field(default_factory=dict)
    visual_attention: Dict[str, Any] = field(default_factory=dict)
    drowsiness: Dict[str, Any] = field(default_factory=dict)
    phone: Dict[str, Any] = field(default_factory=dict)
    latencies_ms: Dict[str, Any] = field(default_factory=dict)
    # expression smoothing
    expr_labels: Deque[Tuple[float, str, float]] = field(default_factory=lambda: deque(maxlen=64))
    # attention / drowsiness temporal
    attn_samples: Deque[Tuple[float, str, float]] = field(default_factory=lambda: deque(maxlen=64))
    eyes_closed_since: Optional[float] = None
    head_down_since: Optional[float] = None
    forward_since: Optional[float] = None
    away_since: Optional[float] = None
    drowsiness_cooldown_until: float = 0.0
    drowsiness_state: str = "none"
    attention_state: str = "inconclusive"
    attention_started: Optional[float] = None


class RealtimeAnalyticsEngine:
    """
    Motor único de analytics por track no modo RTSP.
    FusionEngine legado permanece disponível; este engine é o oficial no runtime.
    """

    def __init__(self, settings):
        self.settings = settings
        self._cache: Dict[str, TrackAnalyticsCache] = {}
        self._expression_provider = None
        self._expression_provider_status = "not_loaded"
        self._phone_associator = None
        self._phone_status = "disabled"
        self._phone_reason = "phone_yolo_disabled"
        self._init_expression_provider()
        self._init_phone()

    def _init_expression_provider(self) -> None:
        mode = str(getattr(self.settings, "module_expression_mode", "disabled") or "disabled").lower()
        if mode == "disabled":
            self._expression_provider_status = "disabled"
            return
        try:
            from app.vision.expressions import create_expression_provider
            from app.vision.emotion_engagement import is_emotion_backend_available

            name = getattr(self.settings, "expression_provider", "fer_legacy") or "fer_legacy"
            if name in ("none", "mock") and not self._is_demo():
                name = "fer_legacy"
            if not is_emotion_backend_available() and name in ("fer_legacy", "fer", "mini_xception"):
                self._expression_provider_status = "unavailable"
                self._expression_provider = None
                return
            self._expression_provider = create_expression_provider(name)
            self._expression_provider_status = "available"
        except Exception as e:
            logger.warning("expression_provider_init_failed", error=str(e))
            self._expression_provider = None
            self._expression_provider_status = "unavailable"

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

            self._phone_associator = PersonPhoneAssociator()
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
    ) -> List[dict]:
        now = now if now is not None else time.time()
        q_iv = float(getattr(self.settings, "analytics_quality_interval_seconds", 0.5) or 0.5)
        l_iv = float(getattr(self.settings, "analytics_landmarks_interval_seconds", 0.5) or 0.5)
        e_iv = float(getattr(self.settings, "expression_interval_seconds", 1.0) or 1.0)
        a_iv = float(getattr(self.settings, "visual_attention_interval_seconds", 0.5) or 0.5)

        n = max(len(matches), len(boxes))
        tracks_out: List[dict] = []
        person_boxes: Dict[str, BBox] = {}

        for i in range(n):
            m = matches[i] if i < len(matches) else {}
            bbox = boxes[i] if i < len(boxes) else (m.get("bbox") or m.get("box") or [0, 0, 0, 0])
            bbox_t = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            sid = m.get("student_id")
            conf = float(m.get("confidence") or 0.0)
            key = str(sid or f"{camera_id}:t{i}")
            person_boxes[key] = bbox_t
            cache = self._get_cache(key)

            t0 = time.perf_counter()
            crop = _clip_crop(frame, bbox_t)

            # --- quality ---
            if now - cache.last_quality_ts >= q_iv or not cache.observation_quality:
                tq0 = time.perf_counter()
                cache.observation_quality = self._compute_quality(crop, bbox_t, frame.shape)
                cache.latencies_ms["quality"] = round((time.perf_counter() - tq0) * 1000.0, 2)
                cache.last_quality_ts = now

            # --- landmarks ---
            if now - cache.last_landmarks_ts >= l_iv or not cache.facial_features:
                tl0 = time.perf_counter()
                cache.facial_features = self._compute_landmarks(crop, key, cache.observation_quality)
                cache.latencies_ms["landmarks"] = round((time.perf_counter() - tl0) * 1000.0, 2)
                cache.last_landmarks_ts = now
                # enrich quality with landmarks_quality when available
                lq = cache.facial_features.get("landmarks_quality")
                if lq is not None and cache.observation_quality:
                    cache.observation_quality["landmarks_quality"] = lq

            # --- expression ---
            expr_mode = str(getattr(self.settings, "module_expression_mode", "disabled")).lower()
            if expr_mode != "disabled":
                if now - cache.last_expression_ts >= e_iv:
                    te0 = time.perf_counter()
                    cache.expression = self._compute_expression(crop, cache, now)
                    cache.latencies_ms["expression"] = round((time.perf_counter() - te0) * 1000.0, 2)
                    cache.last_expression_ts = now
            else:
                cache.expression = {"status": "disabled"}

            # --- attention + drowsiness (motor único neste engine) ---
            lm_mode = str(getattr(self.settings, "module_face_landmarks_mode", "disabled")).lower()
            pose_mode = str(getattr(self.settings, "module_pose_mode", "disabled")).lower()
            fusion_mode = str(getattr(self.settings, "module_temporal_fusion_mode", "disabled")).lower()
            if lm_mode != "disabled" or pose_mode != "disabled" or fusion_mode != "disabled":
                if now - cache.last_attention_ts >= a_iv:
                    ta0 = time.perf_counter()
                    cache.visual_attention, cache.drowsiness = self._compute_attention_drowsiness(cache, now)
                    cache.latencies_ms["attention_drowsiness"] = round((time.perf_counter() - ta0) * 1000.0, 2)
                    cache.last_attention_ts = now
            else:
                cache.visual_attention = {"status": "disabled"}
                cache.drowsiness = {"status": "disabled"}

            cache.latencies_ms["total_analytics"] = round((time.perf_counter() - t0) * 1000.0, 2)

            tracks_out.append(
                {
                    "track_id": key,
                    "student_id": sid,
                    "full_name": m.get("full_name"),
                    "identity_confidence": conf if sid else None,
                    "confidence": conf,
                    "bbox": [int(bbox_t[0]), int(bbox_t[1]), int(bbox_t[2]), int(bbox_t[3])],
                    "observation_quality": dict(cache.observation_quality),
                    "facial_features": dict(cache.facial_features),
                    "latencies_ms": dict(cache.latencies_ms),
                    "expression": dict(cache.expression),
                    "visual_attention": dict(cache.visual_attention),
                    "drowsiness": dict(cache.drowsiness),
                    "phone": dict(cache.phone),
                }
            )

        # phone association (batch)
        self._update_phones(frame, person_boxes, tracks_out, now)

        # prune stale caches
        active = {t["track_id"] for t in tracks_out}
        for k in list(self._cache.keys()):
            if k not in active and ":" in k and k.startswith(camera_id):
                # keep student_id keys a bit
                pass
        return tracks_out

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
            "occlusion_score": None,  # não estimamos oclusão sem modelo
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

        # probe mediapipe
        try:
            import mediapipe as mp  # noqa: F401

            if not hasattr(mp, "solutions"):
                base["status"] = "unavailable"
                base["reason"] = "mediapipe_solutions_missing"
                base["provider"] = "unavailable"
                return base
        except Exception as e:
            base["status"] = "unavailable"
            base["reason"] = f"mediapipe_import_failed:{e}"
            return base

        try:
            from app.vision.landmarks_adapter import facial_features_from_roi

            ff = facial_features_from_roi(crop, track_id)
            # analyze_face_roi may return poor sample without mesh
            provider = "mediapipe"
            status = "available"
            reason = None
            if ff.yaw is None and ff.average_eye_openness is None and ff.landmarks_quality <= 0:
                status = "inconclusive"
                reason = "no_landmarks"
            return {
                "left_eye_openness": ff.left_eye_openness,
                "right_eye_openness": ff.right_eye_openness,
                "average_eye_openness": ff.average_eye_openness,
                "blink_score": ff.blink_score,
                "mouth_open_score": ff.mouth_open_score,
                "possible_yawn_score": None if ff.mouth_open_score is None else (
                    float(ff.mouth_open_score) if ff.mouth_open_score >= 0.55 else 0.0
                ),
                "smile_score": ff.smile_score,
                "yaw": ff.yaw,
                "pitch": ff.pitch,
                "roll": ff.roll,
                "gaze_horizontal": ff.gaze_horizontal if ff.gaze_horizontal is not None else ff.yaw,
                "gaze_vertical": ff.gaze_vertical if ff.gaze_vertical is not None else ff.pitch,
                "landmarks_quality": ff.landmarks_quality if ff.landmarks_quality else None,
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
        if q.get("overall_score") is not None and float(q["overall_score"]) < min_q:
            return {
                "provider": getattr(self.settings, "expression_provider", "fer_legacy"),
                "model_name": "mini-xception",
                "raw_label": None,
                "normalized_state": "inconclusive",
                "confidence": 0.0,
                "smoothed_state": "inconclusive",
                "is_conclusive": False,
                "status": "inconclusive",
                "inference_ms": 0.0,
                "sample_count": len(cache.expr_labels),
                "reason": "insufficient_observation_quality",
            }
        if self._expression_provider_status == "unavailable" or self._expression_provider is None:
            return {
                "provider": "fer_legacy",
                "model_name": "mini-xception",
                "raw_label": None,
                "normalized_state": "inconclusive",
                "confidence": 0.0,
                "smoothed_state": "inconclusive",
                "is_conclusive": False,
                "status": "unavailable",
                "inference_ms": 0.0,
                "sample_count": 0,
                "reason": "provider_unavailable",
            }
        if crop is None:
            return {
                "provider": "fer_legacy",
                "status": "inconclusive",
                "normalized_state": "inconclusive",
                "smoothed_state": "inconclusive",
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
            if pred is None:
                return {
                    "provider": "fer_legacy",
                    "status": "error",
                    "reason": "empty_prediction",
                    "normalized_state": "inconclusive",
                    "smoothed_state": "inconclusive",
                    "is_conclusive": False,
                    "confidence": 0.0,
                    "inference_ms": 0.0,
                    "sample_count": len(cache.expr_labels),
                }
            raw = pred.raw_label or pred.label
            norm = normalize_expression_label(pred.label)
            min_conf = float(getattr(self.settings, "expression_minimum_confidence", 0.60) or 0.60)
            conclusive = bool(pred.is_conclusive and pred.confidence >= min_conf and norm != "inconclusive")
            if conclusive:
                cache.expr_labels.append((now, norm, float(pred.confidence)))
            # prune window
            win = float(getattr(self.settings, "expression_window_seconds", 8) or 8)
            while cache.expr_labels and now - cache.expr_labels[0][0] > win:
                cache.expr_labels.popleft()
            smoothed, sample_count = self._smooth_expression(cache.expr_labels, now)
            display = display_expression_pt(smoothed)
            return {
                "provider": pred.provider or "fer_legacy",
                "model_name": "mini-xception",
                "raw_label": raw,
                "normalized_state": norm if conclusive else "inconclusive",
                "confidence": round(float(pred.confidence), 3),
                "smoothed_state": smoothed,
                "smoothed_display_pt": display,
                "is_conclusive": conclusive and smoothed != "inconclusive",
                "status": "available" if conclusive else "inconclusive",
                "inference_ms": round(float(pred.inference_ms), 2),
                "sample_count": sample_count,
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
        self, buf: Deque[Tuple[float, str, float]], now: float
    ) -> Tuple[str, int]:
        min_samples = int(getattr(self.settings, "expression_minimum_samples", 4) or 4)
        if len(buf) < min_samples:
            return "inconclusive", len(buf)
        counts: Dict[str, float] = {}
        for _, label, conf in buf:
            counts[label] = counts.get(label, 0.0) + conf
        best = max(counts.items(), key=lambda kv: kv[1])[0]
        # map to predominantly_*
        mapping = {
            "positive": "predominantly_positive",
            "neutral": "predominantly_neutral",
            "negative": "predominantly_negative",
            "surprise": "surprise",
            "inconclusive": "inconclusive",
        }
        return mapping.get(best, "inconclusive"), len(buf)

    def _compute_attention_drowsiness(
        self, cache: TrackAnalyticsCache, now: float
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        from app.analytics.attention_drowsiness import (
            evaluate_apparent_drowsiness,
            evaluate_visual_attention,
        )

        q = cache.observation_quality or {}
        ff = cache.facial_features or {}
        overall = float(q.get("overall_score") or 0.0)
        min_q_attn = float(getattr(self.settings, "visual_attention_minimum_observation_quality", 0.55) or 0.55)
        min_q_dr = float(getattr(self.settings, "drowsiness_minimum_observation_quality", 0.60) or 0.60)

        yaw = ff.get("yaw")
        pitch = ff.get("pitch")
        ear = ff.get("average_eye_openness")
        gaze_h = ff.get("gaze_horizontal")
        gaze_reliable = ff.get("status") == "available" and yaw is not None

        # drowsiness timing
        eyes_closed = ear is not None and float(ear) < 0.18
        head_down = pitch is not None and float(pitch) > 0.35
        if eyes_closed:
            if cache.eyes_closed_since is None:
                cache.eyes_closed_since = now
        else:
            cache.eyes_closed_since = None
        if head_down:
            if cache.head_down_since is None:
                cache.head_down_since = now
        else:
            cache.head_down_since = None

        eyes_closed_s = (now - cache.eyes_closed_since) if cache.eyes_closed_since else 0.0
        possible_after = float(getattr(self.settings, "drowsiness_possible_after_seconds", 6) or 6)
        probable_after = float(getattr(self.settings, "drowsiness_probable_after_seconds", 10) or 10)
        cooldown = float(getattr(self.settings, "drowsiness_cooldown_seconds", 20) or 20)

        if overall < min_q_dr or ff.get("status") in ("unavailable", "error"):
            drow = {
                "state": "inconclusive",
                "confidence": 0.2,
                "duration_seconds": round(eyes_closed_s, 2),
                "sample_count": len(cache.attn_samples),
                "reasons": ["insufficient_observation_quality"]
                if overall < min_q_dr
                else [ff.get("reason") or "landmarks_unavailable"],
            }
        else:
            st = evaluate_apparent_drowsiness(
                eyes_closed_seconds=eyes_closed_s,
                head_pitch=float(pitch or 0.0),
                head_supported=False,
                low_motion=False,
                sample_count=max(5, len(cache.attn_samples)),
                observation_quality=overall,
                min_duration_seconds=probable_after,
                min_samples=5,
                min_quality=min_q_dr,
                cooldown_active=now < cache.drowsiness_cooldown_until,
            )
            # override short blink
            if eyes_closed_s < 2.5:
                st.state = "none"
                st.reasons = ["brief_blink_or_closed"]
            elif st.state == "none" and eyes_closed_s >= possible_after:
                st.state = "possible"
                st.reasons.append("eyes_closed_duration")
            if st.state in ("possible", "probable"):
                cache.drowsiness_cooldown_until = now + cooldown
            drow = {
                "state": st.state,
                "confidence": round(st.confidence, 3),
                "duration_seconds": round(eyes_closed_s, 2),
                "sample_count": len(cache.attn_samples),
                "reasons": st.reasons,
                "contributing_signals": st.contributing_signals,
            }
        cache.drowsiness_state = drow["state"]

        # attention
        if overall < min_q_attn or ff.get("status") in ("unavailable", "error"):
            attn = {
                "state": "inconclusive",
                "confidence": 0.0,
                "duration_seconds": 0.0,
                "sample_count": len(cache.attn_samples),
                "contributing_signals": {"observation_quality": overall},
                "reasons": ["insufficient_observation_quality"]
                if overall < min_q_attn
                else [ff.get("reason") or "landmarks_unavailable"],
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

        # temporal: short look-down (<2.5s) should not persist as low
        if head_down and cache.head_down_since and (now - cache.head_down_since) < 2.5:
            if attn_eval.state == "low":
                attn_eval.state = "moderate"
                attn_eval.reasons = list(attn_eval.reasons) + ["short_look_down"]

        # duration tracking
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
            },
            "reasons": attn_eval.reasons,
        }
        return attn, drow

    def _update_phones(
        self,
        frame: np.ndarray,
        person_boxes: Dict[str, BBox],
        tracks_out: List[dict],
        now: float,
    ) -> None:
        if self._phone_status != "available" or self._phone_associator is None:
            for t in tracks_out:
                t["phone"] = {
                    "status": self._phone_status,
                    "state": "not_detected",
                    "provider": "yolo",
                    "confidence": None,
                    "duration_seconds": None,
                    "reasons": [self._phone_reason] if self._phone_reason else [],
                    "reason": self._phone_reason,
                }
                self._get_cache(t["track_id"]).phone = t["phone"]
            return
        try:
            from app.vision.phone_yolo import detect_phones

            phones = detect_phones(frame)
            phone_boxes = [(p[0], p[1], p[2], p[3], p[4] if len(p) > 4 else 0.5) for p in phones]
            states = self._phone_associator.update(
                now=now, person_tracks=person_boxes, phone_boxes=phone_boxes
            )
            by_id = {s.person_track_id: s for s in states}
            for t in tracks_out:
                s = by_id.get(t["track_id"])
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
                    # map legacy short names
                    if level in ("possible",):
                        level = "possible_phone_interaction"
                    elif level in ("probable",):
                        level = "probable_phone_interaction"
                    t["phone"] = {
                        "status": "available",
                        "state": level if level != "none" else (
                            "phone_near_person" if s.phone_near_person else (
                                "phone_visible" if s.phone_visible else "not_detected"
                            )
                        ),
                        "provider": "yolo",
                        "confidence": round(s.confidence, 3),
                        "duration_seconds": round(s.duration_seconds, 2),
                        "reasons": s.reasons,
                    }
                self._get_cache(t["track_id"]).phone = t["phone"]
        except Exception as e:
            for t in tracks_out:
                t["phone"] = {
                    "status": "error",
                    "state": "not_detected",
                    "provider": "yolo",
                    "reason": str(e),
                    "reasons": [str(e)],
                }

    def classroom_counts(self, tracks: List[dict], present_count: int) -> Dict[str, Any]:
        visible = len(tracks)
        observable = sum(
            1 for t in tracks if (t.get("observation_quality") or {}).get("status") == "observable"
        )
        inconclusive = sum(
            1
            for t in tracks
            if (t.get("observation_quality") or {}).get("status") in ("inconclusive", "low_quality", "error")
        )
        # attention aggregate only when states exist and not not_implemented
        attn_vals = []
        for t in tracks:
            va = t.get("visual_attention") or {}
            if va.get("status") in ("not_implemented", "disabled"):
                continue
            if va.get("state") in ("high", "moderate", "low") and va.get("confidence") is not None:
                attn_vals.append(float(va["confidence"]))
        climate = None
        expr_states = []
        for t in tracks:
            ex = t.get("expression") or {}
            if ex.get("status") in ("available", "inconclusive") and ex.get("smoothed_state"):
                expr_states.append(ex["smoothed_state"])
        if expr_states:
            from collections import Counter

            climate = Counter(expr_states).most_common(1)[0][0]

        return {
            "present": present_count,
            "visible": visible,
            "observable": observable,
            "inconclusive": inconclusive,
            "attention_index": round(sum(attn_vals) / len(attn_vals), 3) if attn_vals else None,
            "climate": climate,
            "attention_available": bool(attn_vals),
            "climate_available": climate is not None,
        }
