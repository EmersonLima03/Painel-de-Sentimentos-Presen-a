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
    # expression smoothing
    expr_labels: Deque[Tuple[float, str, float]] = field(default_factory=lambda: deque(maxlen=64))
    # attention / drowsiness temporal
    attn_samples: Deque[Tuple[float, str, float]] = field(default_factory=lambda: deque(maxlen=64))
    eyes_closed_since: Optional[float] = None
    head_down_since: Optional[float] = None
    hand_near_since: Optional[float] = None
    forward_since: Optional[float] = None
    away_since: Optional[float] = None
    drowsiness_cooldown_until: float = 0.0
    drowsiness_state: str = "none"
    attention_state: str = "inconclusive"
    attention_started: Optional[float] = None
    track_first_seen: Optional[float] = None


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
        self._expression_health_reason = None
        self._phone_associator = None
        self._phone_status = "disabled"
        self._phone_reason = "phone_yolo_disabled"
        self._open_events: Dict[str, Dict[str, Any]] = {}  # key = f"{track}:{event_type}"
        self._event_sink = None  # callable(event_dict) | None
        self._ws_events: Deque[Dict[str, Any]] = deque(maxlen=64)
        self._identity_engine = None
        self._person_tracker_debug: Dict[str, Any] = {}
        self._phone_detector_debug: Dict[str, Any] = {}
        self._init_expression_provider()
        self._init_phone()
        self._init_identity_engine()

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
            return
        try:
            from app.vision.expressions import create_expression_provider
            from app.vision.emotion_engagement import emotion_backend_health

            name = getattr(self.settings, "expression_provider", "fer_legacy") or "fer_legacy"
            if name in ("none", "mock") and not self._is_demo():
                name = "fer_legacy"
            health = emotion_backend_health()
            self._expression_health_reason = health.get("reason")
            if health.get("status") != "available" and name in ("fer_legacy", "fer", "mini_xception"):
                self._expression_provider_status = health.get("status") or "unavailable"
                self._expression_provider = None
                return
            self._expression_provider = create_expression_provider(name)
            if hasattr(self._expression_provider, "health"):
                h2 = self._expression_provider.health(force=True)
                self._expression_provider_status = h2.get("status") or "unavailable"
                self._expression_health_reason = h2.get("reason")
                if self._expression_provider_status != "available":
                    self._expression_provider = None
                    return
            else:
                self._expression_provider_status = "available"
        except Exception as e:
            logger.warning("expression_provider_init_failed", error=str(e))
            self._expression_provider = None
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
        person_tracks: Optional[List[Any]] = None,
        person_tracker_debug: Optional[Dict[str, Any]] = None,
    ) -> List[dict]:
        """
        Person-first: person_tracks alimentam o motor.
        matches/boxes (faces do overlay de presença) só reconfirmam identidade.
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
                "note": "sem person_tracks — usando faces como proxy",
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
            id_states = self._identity_engine.update_continuity(
                now=now,
                person_tracks=persons,
                face_tracks=face_tracks,
                face_identities=face_identities,
            )

        # map face_id → face track
        faces_by_id = {f.track_id: f for f in face_tracks}

        tracks_out: List[dict] = []
        person_boxes: Dict[str, BBox] = {}
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
            # se associação ambígua mas há face candidata, ainda pode usar bbox espacialmente
            if face_bbox is None and assoc.get("face_track_id"):
                ft = faces_by_id.get(assoc["face_track_id"])
                if ft:
                    face_bbox = ft.face_bbox

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
            # crops: face se visível, senão ROI cabeça (topo do person)
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

            # --- landmarks (só se face observável) ---
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

                    pr = estimate_body_pose(
                        frame,
                        person_bbox,
                        face_bbox=face_bbox,
                        head_down_since=cache.head_down_since,
                        hand_near_since=cache.hand_near_since,
                        now=now,
                    )
                    cache.pose = pr.as_dict()
                    cache.hands = dict(pr.hands)
                    cache.face_occlusion = dict(pr.face_occlusion)
                    cache.head_state = {
                        "state": pr.head_state,
                        "confidence": pr.head_confidence,
                        "reasons": list(pr.reasons),
                    }
                    if pr.head_state in ("head_down_short", "head_down_persistent", "head_supported"):
                        if cache.head_down_since is None:
                            cache.head_down_since = now
                    else:
                        cache.head_down_since = None
                    if (pr.hands or {}).get("state") == "hand_near_face":
                        if cache.hand_near_since is None:
                            cache.hand_near_since = now
                    else:
                        cache.hand_near_since = None
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
                cache.expression = {
                    "status": "inconclusive",
                    "reason": "face_not_observable"
                    if not face_visible
                    else "possible_face_occlusion",
                    "normalized_state": "inconclusive",
                    "smoothed_state": "inconclusive",
                    "is_conclusive": False,
                    "confidence": 0.0,
                }
            elif expr_mode != "disabled":
                if now - cache.last_expression_ts >= e_iv:
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

            cache.latencies_ms["total_analytics"] = round((time.perf_counter() - t0) * 1000.0, 2)
            full_name = None
            if face_tid and face_tid in face_identities:
                full_name = face_identities[face_tid].get("full_name")

            pb_list = [int(person_bbox[0]), int(person_bbox[1]), int(person_bbox[2]), int(person_bbox[3])]
            fb_list = (
                [int(face_bbox[0]), int(face_bbox[1]), int(face_bbox[2]), int(face_bbox[3])]
                if face_bbox
                else None
            )
            track_age = now - (cache.track_first_seen or now)

            tracks_out.append(
                {
                    "person_track_id": key,
                    "track_age_seconds": round(track_age, 2),
                    "track_confidence": round(float(person.tracking_confidence or 0.0), 3),
                    "tracking_state": getattr(person, "tracking_state", "active") or "active",
                    "seconds_since_person_detection": round(
                        float(getattr(person, "seconds_since_person_detection", 0.0) or 0.0), 2
                    ),
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
                    "person_bbox": pb_list,
                    "face_bbox": fb_list,
                    "face_person_association": assoc,
                    "pose": dict(cache.pose or {}),
                    "hands": dict(cache.hands or {}),
                    "observation_quality": dict(cache.observation_quality),
                    "head_state": dict(cache.head_state or {}),
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
        )

        # close events for dead tracks
        for old_key in list(self._cache.keys()):
            if old_key not in active_keys:
                self._close_all_events_for_track(old_key, now)
                if self._identity_engine:
                    self._identity_engine.expire_track(old_key)
                self._cache.pop(old_key, None)

        for t in tracks_out:
            self._sync_temporal_events(t, now)
            tid = str(t.get("person_track_id") or t.get("track_id"))
            t["active_events"] = [
                {
                    "event_id": ev["event_id"],
                    "event_type": ev["event_type"],
                    "status": ev["lifecycle"],
                    "duration_seconds": round(now - ev["started_at"], 2),
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
                "smile_score": ff.smile_score,
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
        if self._expression_provider_status != "available" or self._expression_provider is None:
            return {
                "provider": "fer_legacy",
                "model_name": "mini-xception",
                "raw_label": None,
                "normalized_state": "inconclusive",
                "confidence": 0.0,
                "smoothed_state": "inconclusive",
                "is_conclusive": False,
                "status": self._expression_provider_status or "unavailable",
                "inference_ms": 0.0,
                "sample_count": 0,
                "reason": self._expression_health_reason or "provider_unavailable",
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
            # Prefer full probability distribution when provider exposes it
            raw = pred.raw_label or pred.label
            if getattr(pred, "probabilities", None):
                from app.vision.expressions.normalization import pick_label as _pick

                label2, conf2, ok2 = _pick(pred.probabilities, minimum_confidence=0.01)
                if label2 != "inconclusive":
                    raw = pred.raw_label or label2
                    # keep pred fields aligned
                    pred_label = label2
                    pred_conf = conf2
                else:
                    pred_label = pred.label
                    pred_conf = float(pred.confidence)
            else:
                pred_label = pred.label
                pred_conf = float(pred.confidence)
            norm = normalize_expression_label(pred_label)
            min_conf = float(getattr(self.settings, "expression_minimum_confidence", 0.60) or 0.60)
            conclusive = bool(pred.is_conclusive and pred_conf >= min_conf and norm != "inconclusive")
            if not conclusive and norm != "inconclusive" and pred_conf >= min_conf:
                conclusive = True
            # Aceita amostras com confiança razoável para smoothing
            if norm != "inconclusive" and pred_conf >= min(0.35, min_conf):
                cache.expr_labels.append((now, norm, pred_conf))
            win = float(getattr(self.settings, "expression_window_seconds", 8) or 8)
            while cache.expr_labels and now - cache.expr_labels[0][0] > win:
                cache.expr_labels.popleft()
            smoothed, sample_count = self._smooth_expression(cache.expr_labels, now)
            display = display_expression_pt(smoothed)
            try:
                from app.vision.emotion_engagement import emotion_backend_health

                h = emotion_backend_health()
                provider_name = "fer_legacy"
                model_name = h.get("model_name") or "mini-xception"
            except Exception:
                provider_name = pred.provider or "fer_legacy"
                model_name = "mini-xception"
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

        # Sem face observável / oclusão possível → atenção e sonolência inconclusivas
        if (
            not face_visible
            or occ in ("possible_face_occlusion_by_hand", "persistent_possible_face_occlusion")
            or (
                ff.get("status") in ("unavailable", "error", "inconclusive")
                and ff.get("average_eye_openness") is None
            )
        ):
            reasons = []
            if not face_visible:
                reasons.append("face_not_observable")
            if "occlusion" in occ:
                reasons.append(occ)
            if head_st in ("head_down_short", "head_down_persistent", "head_supported"):
                reasons.append(head_st)
            # sinais descritivos ok, mas state inconclusive
            attn = {
                "state": "inconclusive",
                "confidence": 0.0,
                "duration_seconds": 0.0,
                "sample_count": len(cache.attn_samples),
                "contributing_signals": {
                    "observation_quality": overall,
                    "head_state": head_st,
                    "face_occlusion": occ,
                },
                "reasons": reasons or ["insufficient_visual_evidence"],
                "descriptive_signals": [s for s in (head_st, occ) if s and s not in ("none", "pose_inconclusive")],
            }
            drow = {
                "state": "inconclusive",
                "confidence": 0.0,
                "duration_seconds": 0.0,
                "sample_count": len(cache.attn_samples),
                "reasons": ["eyes_not_observable"] + reasons,
            }
            cache.drowsiness_state = "inconclusive"
            return attn, drow

        yaw = ff.get("yaw")
        pitch = ff.get("pitch")
        ear = ff.get("average_eye_openness")
        gaze_h = ff.get("gaze_horizontal")
        gaze_reliable = ff.get("status") == "available" and yaw is not None

        eyes_closed = ear is not None and float(ear) < 0.18
        # head_down do pose tem prioridade; pitch facial é auxiliar
        head_down = head_st in ("head_down_short", "head_down_persistent", "head_supported") or (
            pitch is not None and float(pitch) > 0.35
        )
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

        # Sonolência: exige olhos observáveis; cabeça baixa sozinha NÃO gera possible/probable
        if ear is None:
            drow = {
                "state": "inconclusive",
                "confidence": 0.2,
                "duration_seconds": 0.0,
                "sample_count": len(cache.attn_samples),
                "reasons": ["eyes_not_observable"],
            }
        elif overall < min_q_dr:
            drow = {
                "state": "inconclusive",
                "confidence": 0.2,
                "duration_seconds": round(eyes_closed_s, 2),
                "sample_count": len(cache.attn_samples),
                "reasons": ["insufficient_observation_quality"],
            }
        else:
            head_supported = head_st == "head_supported"
            st = evaluate_apparent_drowsiness(
                eyes_closed_seconds=eyes_closed_s,
                head_pitch=float(pitch or 0.0),
                head_supported=head_supported,
                low_motion=False,
                sample_count=max(5, len(cache.attn_samples)),
                observation_quality=overall,
                min_duration_seconds=probable_after,
                min_samples=5,
                min_quality=min_q_dr,
                cooldown_active=now < cache.drowsiness_cooldown_until,
            )
            if eyes_closed_s < 2.5:
                st.state = "none"
                st.reasons = ["brief_blink_or_closed"]
            elif not eyes_closed:
                # sem olhos fechados → nunca possible/probable só por cabeça
                st.state = "none"
                if head_down:
                    st.reasons = ["head_down_without_closed_eyes_not_drowsiness"]
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

        if overall < min_q_attn:
            attn = {
                "state": "inconclusive",
                "confidence": 0.0,
                "duration_seconds": 0.0,
                "sample_count": len(cache.attn_samples),
                "contributing_signals": {"observation_quality": overall},
                "reasons": ["insufficient_observation_quality"],
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

        # cabeça baixa curta não vira low
        if head_st == "head_down_short" or (
            head_down and cache.head_down_since and (now - cache.head_down_since) < 2.5
        ):
            if attn_eval.state == "low":
                attn_eval.state = "moderate"
                attn_eval.reasons = list(attn_eval.reasons) + ["short_look_down"]
        # cabeça baixa persistente: sinal descritivo, não forçar low automático
        if head_st == "head_down_persistent" and attn_eval.state == "low":
            attn_eval.reasons = list(attn_eval.reasons) + ["head_down_persistent_descriptive"]

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
        wrists: Optional[Dict[str, List[Tuple[float, float]]]] = None,
        head_looking_down: Optional[Dict[str, bool]] = None,
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

            phones = detect_phones(frame)
            self._phone_detector_debug = get_phone_detector_debug()
            phone_boxes = [(p[0], p[1], p[2], p[3], p[4] if len(p) > 4 else 0.5) for p in phones]
            states = self._phone_associator.update(
                now=now,
                person_tracks=person_boxes,
                phone_boxes=phone_boxes,
                wrists=wrists or {},
                head_looking_down=head_looking_down or {},
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

    def _sync_temporal_events(self, track: Dict[str, Any], now: float) -> None:
        """Abre/atualiza/fecha eventos a partir dos estados do motor (sem duplicar legado)."""
        tid = str(track.get("track_id") or "unknown")
        sid = track.get("student_id")
        q = (track.get("observation_quality") or {}).get("status")
        quality = q or "unknown"
        candidates: List[Tuple[str, str, float, List[str]]] = []

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
        if hs.get("state") == "head_down_persistent":
            candidates.append(
                (
                    "head_down_persistent",
                    "observed",
                    float(hs.get("confidence") or 0.5),
                    list(hs.get("reasons") or []),
                )
            )

        occ = track.get("face_occlusion") or {}
        if occ.get("state") == "persistent_possible_face_occlusion":
            candidates.append(
                (
                    "face_occluded_persistent",
                    "observed",
                    float(occ.get("confidence") or 0.4),
                    list(occ.get("reasons") or []),
                )
            )

        active_types = {c[0] for c in candidates}
        # close missing
        for key in list(self._open_events.keys()):
            if not key.startswith(tid + ":"):
                continue
            etype = key.split(":", 1)[1]
            if etype not in active_types:
                ev = self._open_events.pop(key)
                ev["ended_at"] = now
                ev["duration_seconds"] = round(now - ev["started_at"], 2)
                ev["lifecycle"] = "closed"
                self._emit_event("closed", ev)

        for etype, status, conf, reasons in candidates:
            key = f"{tid}:{etype}"
            if key not in self._open_events:
                from app.utils.ids import generate_event_id

                ev = {
                    "event_id": generate_event_id(),
                    "event_type": etype,
                    "track_id": tid,
                    "student_id": sid,
                    "started_at": now,
                    "ended_at": None,
                    "duration_seconds": 0.0,
                    "confidence": conf,
                    "observation_quality": quality,
                    "status": status,
                    "lifecycle": "opened",
                    "reasons": reasons,
                    "provenance": self._provenance(),
                    "requires_human_review": etype.endswith("phone_interaction")
                    or "drowsiness" in etype,
                }
                self._open_events[key] = ev
                self._emit_event("opened", ev)
            else:
                ev = self._open_events[key]
                ev["ended_at"] = now
                ev["duration_seconds"] = round(now - ev["started_at"], 2)
                ev["confidence"] = conf
                ev["observation_quality"] = quality
                ev["reasons"] = reasons
                ev["lifecycle"] = "updated"
                # throttle updates ~2s
                last_u = float(ev.get("_last_update_emit") or 0)
                if now - last_u >= 2.0:
                    ev["_last_update_emit"] = now
                    self._emit_event("updated", {k: v for k, v in ev.items() if k != "_last_update_emit"})

    def classroom_counts(self, tracks: List[dict], present_count: int) -> Dict[str, Any]:
        visible = len(tracks)
        observable = sum(
            1 for t in tracks if (t.get("observation_quality") or {}).get("status") == "observable"
        )
        inconclusive = sum(
            1
            for t in tracks
            if (t.get("observation_quality") or {}).get("status")
            in ("inconclusive", "low_quality", "error", "partially_observable", "not_visible")
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
            if ex.get("status") == "available" and ex.get("smoothed_state") and ex.get("smoothed_state") != "inconclusive":
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
