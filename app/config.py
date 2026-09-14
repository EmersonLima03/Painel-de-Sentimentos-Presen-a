"""Configuração centralizada do aplicativo."""

import os
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field
import yaml


class CameraConfig:
    """Configuração de uma câmera."""
    
    def __init__(
        self,
        camera_id: str,
        room_id: str,
        rtsp_url: str,
        enabled: bool = True,
        webcam_width: Optional[int] = None,
        webcam_height: Optional[int] = None,
    ):
        self.camera_id = camera_id
        self.room_id = room_id
        self.rtsp_url = rtsp_url
        self.enabled = enabled
        # Só aplicado quando rtsp_url é índice numérico (webcam local/USB)
        self.webcam_width = webcam_width
        self.webcam_height = webcam_height


class Settings(BaseSettings):
    """Configurações do aplicativo via .env e YAML."""
    
    # Device
    device_id: str = Field(default="edge-001", env="DEVICE_ID")
    device_token: str = Field(default="", env="DEVICE_TOKEN")
    school_id: str = Field(default="1", env="SCHOOL_ID")
    
    # Supabase
    supabase_ingest_url: str = Field(default="", env="SUPABASE_INGEST_URL")
    supabase_anon_key: str = Field(default="", env="SUPABASE_ANON_KEY")  # Para passar validação inicial
    
    # Database
    sqlite_path: str = Field(default="./data/dulino_edge.db", env="SQLITE_PATH")
    
    # Modes
    simulation: bool = Field(default=True, env="SIMULATION")
    real: bool = Field(default=False, env="REAL")
    
    # RTSP
    presence_sampling_seconds: int = Field(default=2, env="PRESENCE_SAMPLING_SECONDS")
    engagement_sampling_seconds: int = Field(default=5, env="ENGAGEMENT_SAMPLING_SECONDS")
    presence_threshold: float = Field(default=0.75, env="PRESENCE_THRESHOLD")
    presence_match_margin: float = Field(default=0.08, env="PRESENCE_MATCH_MARGIN")
    presence_th_on: float = Field(default=0.75, env="PRESENCE_TH_ON")
    presence_th_off: float = Field(default=0.68, env="PRESENCE_TH_OFF")
    face_min_size: int = Field(default=50, env="FACE_MIN_SIZE")
    track_ttl_seconds: float = Field(default=2.0, env="TRACK_TTL_SECONDS")
    max_templates_per_student: int = Field(default=7, env="MAX_TEMPLATES_PER_STUDENT")
    default_camera_index: int = Field(default=0, env="DEFAULT_CAMERA_INDEX")
    camera_connect_timeout_seconds: int = Field(default=15, env="CAMERA_CONNECT_TIMEOUT_SECONDS")
    
    # Presence
    presence_dedup_mode: str = Field(default="day", env="PRESENCE_DEDUP_MODE")
    presence_active_windows: str = Field(default="07:00-07:20,13:00-13:20", env="PRESENCE_ACTIVE_WINDOWS")
    presence_always_on: bool = Field(default=False, env="PRESENCE_ALWAYS_ON")  # Dev mode: ignora janelas
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # Disable RTSP (para debug)
    disable_rtsp: bool = Field(default=False, env="DISABLE_RTSP")
    
    # Debug snapshot e viewer (opcional, DEV ONLY)
    enable_debug_snapshot: bool = Field(default=False, env="ENABLE_DEBUG_SNAPSHOT")
    enable_debug_ui: bool = Field(default=False, env="ENABLE_DEBUG_UI")
    
    # Whitelist de tipos de eventos para enviar (separado por vírgula)
    # Ex: "attendance_checkin,engagement_window"
    # Se vazio, envia todos
    event_types_whitelist: str = Field(default="", env="EVENT_TYPES_WHITELIST")
    
    # Backup (DAT: embeddings + fila, opcional AES-256)
    backup_passphrase: Optional[str] = Field(default=None, env="BACKUP_PASSPHRASE")
    backup_dir: Optional[str] = Field(default=None, env="BACKUP_DIR")  # ex: D:\backups ou ./backups
    
    # Sync settings (defaults, can be overridden by YAML)
    sync_batch_size: int = Field(default=10)
    sync_retry_attempts: int = Field(default=3)
    sync_retry_backoff_seconds: int = Field(default=5)
    sync_interval_seconds: int = Field(default=10)
    
    # Cameras (loaded from YAML)
    cameras: List[CameraConfig] = []

    # Enrollment (cadastro por webcam): mais frames = mais precisão (média de embeddings)
    enroll_num_frames: int = Field(default=15, env="ENROLL_NUM_FRAMES")
    enroll_frames_used: int = Field(default=10, env="ENROLL_FRAMES_USED")
    enroll_capture_duration: float = Field(default=5.0, env="ENROLL_CAPTURE_DURATION")

    # Visão: multi-pessoa / distância (YAML vision.* ou env VISION_*)
    vision_detector_backend: str = Field(default="yunet", env="VISION_DETECTOR_BACKEND")
    vision_embedder_backend: str = Field(default="facenet", env="VISION_EMBEDDER_BACKEND")
    vision_max_faces: int = Field(default=16, env="VISION_MAX_FACES")
    vision_mediapipe_min_confidence: float = Field(default=0.45, env="VISION_MEDIAPIPE_MIN_CONFIDENCE")
    vision_insightface_det_size: int = Field(default=960, env="VISION_INSIGHTFACE_DET_SIZE")
    vision_insightface_min_det_score: float = Field(default=0.45, env="VISION_INSIGHTFACE_MIN_DET_SCORE")
    vision_yunet_score_threshold: float = Field(default=0.62, env="VISION_YUNET_SCORE_THRESHOLD")
    vision_min_face_area_ratio: float = Field(default=0.0015, env="VISION_MIN_FACE_AREA_RATIO")
    vision_face_relative_min_fraction: float = Field(default=0.22, env="VISION_FACE_RELATIVE_MIN_FRACTION")
    vision_face_aspect_min: float = Field(default=0.45, env="VISION_FACE_ASPECT_MIN")
    vision_face_aspect_max: float = Field(default=1.55, env="VISION_FACE_ASPECT_MAX")
    vision_single_subject_mode: bool = Field(default=False, env="VISION_SINGLE_SUBJECT_MODE")
    vision_dnn_conf_threshold: float = Field(default=0.35, env="VISION_DNN_CONF_THRESHOLD")
    vision_engagement_backend: str = Field(default="head_pose", env="VISION_ENGAGEMENT_BACKEND")
    vision_engagement_model_version: str = Field(default="eng-v2-headpose", env="VISION_ENGAGEMENT_MODEL_VERSION")
    vision_engagement_window_seconds: int = Field(default=10, env="VISION_ENGAGEMENT_WINDOW_SECONDS")

    # Módulo emoções / clima / sessão
    climate_use_fer: bool = Field(default=False, env="CLIMATE_USE_FER")
    climate_window_seconds: int = Field(default=15, env="CLIMATE_WINDOW_SECONDS")
    behavioral_signals_enabled: bool = Field(default=True, env="BEHAVIORAL_SIGNALS_ENABLED")
    presence_periodic_enabled: bool = Field(default=True, env="PRESENCE_PERIODIC_ENABLED")
    require_consent: bool = Field(default=False, env="REQUIRE_CONSENT")
    api_auth_token: str = Field(default="", env="API_AUTH_TOKEN")
    data_retention_days: int = Field(default=90, env="DATA_RETENTION_DAYS")
    phone_yolo_enabled: bool = Field(default=False, env="PHONE_YOLO_ENABLED")
    phone_yolo_model_path: str = Field(default="", env="PHONE_YOLO_MODEL_PATH")
    phone_yolo_conf_threshold: float = Field(default=0.30, env="PHONE_YOLO_CONF")
    phone_yolo_max_height_width_ratio: float = Field(default=2.7, env="PHONE_YOLO_MAX_HW_RATIO")
    phone_yolo_max_width_height_ratio: float = Field(default=4.0, env="PHONE_YOLO_MAX_WH_RATIO")
    phone_yolo_torso_pass_enabled: bool = Field(default=True, env="PHONE_YOLO_TORSO_PASS")
    phone_yolo_torso_conf_threshold: float = Field(default=0.30, env="PHONE_YOLO_TORSO_CONF")

    face_occlusion_wrist_near_ratio: float = Field(default=0.65, env="FACE_OCCLUSION_WRIST_NEAR_RATIO")
    face_occlusion_confirm_seconds: float = Field(default=0.7, env="FACE_OCCLUSION_CONFIRM_SECONDS")
    face_occlusion_clear_hold_seconds: float = Field(default=4.0, env="FACE_OCCLUSION_CLEAR_HOLD_SECONDS")
    # Com rosto sumido (mão cobrindo), mantém oclusão ~15s sem exigir punho a cada frame
    face_occlusion_face_missing_hold_seconds: float = Field(
        default=15.0, env="FACE_OCCLUSION_FACE_MISSING_HOLD"
    )
    face_occlusion_persistent_seconds: float = Field(default=5.0, env="FACE_OCCLUSION_PERSISTENT_SECONDS")
    face_occlusion_suppress_when_landmarks_clear: bool = Field(
        default=True, env="FACE_OCCLUSION_SUPPRESS_LANDMARKS"
    )
    behavioral_event_clear_hold_seconds: float = Field(
        default=0.5, env="BEHAVIORAL_EVENT_CLEAR_HOLD_SECONDS"
    )
    behavioral_event_clear_hold_drowsiness_seconds: float = Field(
        default=4.0, env="BEHAVIORAL_EVENT_CLEAR_HOLD_DROWSINESS_SECONDS"
    )
    # Celular: hold curto anti-flicker YOLO — NÃO manter magenta/evento >~2–3s sem aparelho.
    behavioral_event_clear_hold_phone_seconds: float = Field(
        default=2.5, env="BEHAVIORAL_EVENT_CLEAR_HOLD_PHONE_SECONDS"
    )
    head_down_pitch_threshold: float = Field(default=0.45, env="HEAD_DOWN_PITCH_THRESHOLD")
    head_down_event_min_seconds: float = Field(default=8.0, env="HEAD_DOWN_EVENT_MIN_SECONDS")
    # Alinha short→persistent ao evento (antes hardcoded 2.5s → FP "prolongada" cedo)
    head_down_short_to_persistent_seconds: float = Field(
        default=8.0, env="HEAD_DOWN_SHORT_TO_PERSISTENT_SECONDS"
    )
    # Visibility gate (DMS/DashSentinel): pitch só com landmarks confiáveis
    head_down_require_landmarks_quality: float = Field(
        default=0.45, env="HEAD_DOWN_REQUIRE_LANDMARKS_QUALITY"
    )
    head_down_suppress_when_occlusion: bool = Field(
        default=True, env="HEAD_DOWN_SUPPRESS_WHEN_OCCLUSION"
    )
    # Desligado: "rosto sumiu" ≠ cabeça baixa (mão/objeto/fora de campo)
    head_down_allow_face_missing_proxy: bool = Field(
        default=False, env="HEAD_DOWN_ALLOW_FACE_MISSING_PROXY"
    )
    # Flicker pose_inconclusive durante look-down extremo: mantém acumulador
    head_down_inconclusive_hold_seconds: float = Field(
        default=12.0, env="HEAD_DOWN_INCONCLUSIVE_HOLD_SECONDS"
    )

    # Runtime: demo | offline | rtsp
    runtime_mode: str = Field(default="demo", env="RUNTIME_MODE")
    demo_db_path: str = Field(default="./data/demo/dulino_edge_demo.db", env="DEMO_DB_PATH")
    validation_db_path: str = Field(default="./data/validation/validation.db", env="VALIDATION_DB_PATH")
    experimental_sqlite_005_enabled: bool = Field(default=False, env="EXPERIMENTAL_SQLITE_005")
    longitudinal_approval_recorded: bool = Field(default=False, env="LONGITUDINAL_APPROVAL_RECORDED")

    # Módulos multimodais (disabled|debug|shadow|production)
    module_expression_mode: str = Field(default="disabled", env="MODULE_EXPRESSION_MODE")
    module_face_landmarks_mode: str = Field(default="disabled", env="MODULE_FACE_LANDMARKS_MODE")
    module_person_tracking_mode: str = Field(default="disabled", env="MODULE_PERSON_TRACKING_MODE")
    module_phone_mode: str = Field(default="disabled", env="MODULE_PHONE_MODE")
    module_pose_mode: str = Field(default="disabled", env="MODULE_POSE_MODE")
    module_temporal_fusion_mode: str = Field(default="disabled", env="MODULE_TEMPORAL_FUSION_MODE")
    module_educational_dashboard_mode: str = Field(
        default="production", env="MODULE_EDUCATIONAL_DASHBOARD_MODE"
    )
    module_lxp_mode: str = Field(default="disabled", env="MODULE_LXP_MODE")
    expression_provider: str = Field(default="none", env="EXPRESSION_PROVIDER")
    # Backend oficial de emoção (2026-09-09): hsemotion_vgaf = worker async + VGAF.
    # Rollback simples: EXPRESSION_EMOTION_BACKEND=fer_onnx (ou emotion_backend: fer_onnx).
    # fer_onnx permanece disponível como fallback explícito (não removido).
    expression_emotion_backend: str = Field(
        default="hsemotion_vgaf", env="EXPRESSION_EMOTION_BACKEND"
    )
    expression_hsemotion_interval_seconds: float = Field(
        default=2.0, env="EXPRESSION_HSEMOTION_INTERVAL"
    )
    expression_hsemotion_max_batch: int = Field(
        default=5, env="EXPRESSION_HSEMOTION_MAX_BATCH"
    )
    debug_vision_allow_remote: bool = Field(default=False, env="DEBUG_VISION_ALLOW_REMOTE")
    rule_engine_version: str = Field(default="rules-v0-baseline", env="RULE_ENGINE_VERSION")
    threshold_profile: str = Field(default="presence-yaml-2026-07-23", env="THRESHOLD_PROFILE")
    camera_calibration_version: str = Field(
        default="cam-vip-5440-01-uncalibrated", env="CAMERA_CALIBRATION_VERSION"
    )

    # Analytics intervals / thresholds (runtime real)
    analytics_quality_interval_seconds: float = Field(default=0.5, env="ANALYTICS_QUALITY_INTERVAL")
    analytics_landmarks_interval_seconds: float = Field(default=0.5, env="ANALYTICS_LANDMARKS_INTERVAL")
    expression_interval_seconds: float = Field(default=1.0, env="EXPRESSION_INTERVAL")
    expression_window_seconds: float = Field(default=8.0, env="EXPRESSION_WINDOW")
    expression_minimum_samples: int = Field(default=4, env="EXPRESSION_MIN_SAMPLES")
    expression_minimum_confidence: float = Field(default=0.60, env="EXPRESSION_MIN_CONF")
    expression_minimum_confidence_positive: float = Field(
        default=0.55, env="EXPRESSION_MIN_CONF_POSITIVE"
    )
    expression_minimum_confidence_negative: float = Field(
        default=0.42, env="EXPRESSION_MIN_CONF_NEGATIVE"
    )
    expression_minimum_negative_samples: int = Field(
        default=2, env="EXPRESSION_MIN_NEGATIVE_SAMPLES"
    )
    expression_negative_min_seconds: float = Field(
        default=6.0, env="EXPRESSION_NEGATIVE_MIN_SECONDS"
    )
    expression_smile_boost_enabled: bool = Field(default=False, env="EXPRESSION_SMILE_BOOST")
    expression_frown_boost_enabled: bool = Field(default=True, env="EXPRESSION_FROWN_BOOST")
    expression_ab_secondary: Optional[str] = Field(default=None, env="EXPRESSION_AB_SECONDARY")
    expression_fallback_chain: Optional[str] = Field(
        default="hsemotion,deepface,fer_legacy", env="EXPRESSION_FALLBACK_CHAIN"
    )
    expression_minimum_observation_quality: float = Field(default=0.55, env="EXPRESSION_MIN_QUALITY")
    visual_attention_interval_seconds: float = Field(default=0.5, env="ATTENTION_INTERVAL")
    visual_attention_window_seconds: float = Field(default=10.0, env="ATTENTION_WINDOW")
    visual_attention_minimum_observation_quality: float = Field(default=0.55, env="ATTENTION_MIN_QUALITY")
    drowsiness_possible_after_seconds: float = Field(default=6.0, env="DROWSINESS_POSSIBLE_AFTER")
    drowsiness_probable_after_seconds: float = Field(default=30.0, env="DROWSINESS_PROBABLE_AFTER")
    drowsiness_minimum_observation_quality: float = Field(default=0.60, env="DROWSINESS_MIN_QUALITY")
    drowsiness_cooldown_seconds: float = Field(default=20.0, env="DROWSINESS_COOLDOWN")
    drowsiness_eye_closed_ear_threshold: float = Field(default=0.18, env="DROWSINESS_EAR_THRESHOLD")
    drowsiness_head_down_possible_multiplier: float = Field(
        default=2.0, env="DROWSINESS_HEAD_DOWN_POSSIBLE_MULT"
    )
    drowsiness_head_down_probable_seconds: float = Field(
        default=45.0, env="DROWSINESS_HEAD_DOWN_PROBABLE_AFTER"
    )
    drowsiness_observation_gap_inconclusive_seconds: float = Field(
        default=8.0, env="DROWSINESS_OBS_GAP_INCONCLUSIVE"
    )
    phone_possible_after_seconds: float = Field(default=5.0, env="PHONE_POSSIBLE_AFTER")
    phone_probable_after_seconds: float = Field(default=12.0, env="PHONE_PROBABLE_AFTER")
    phone_interaction_requires_in_hand: bool = Field(default=True, env="PHONE_INTERACTION_REQUIRES_IN_HAND")
    phone_association_clear_hold_seconds: float = Field(
        default=2.0, env="PHONE_ASSOCIATION_CLEAR_HOLD_SECONDS"
    )
    experimental_perclos_enabled: bool = Field(default=False, env="EXPERIMENTAL_PERCLOS")
    experimental_perclos_window_seconds: float = Field(default=60.0, env="PERCLOS_WINDOW")
    experimental_perclos_min_coverage: float = Field(default=0.50, env="PERCLOS_MIN_COVERAGE")

    # Person-first tracking / identity continuity (analytics only — não altera presença)
    # face_missing_ttl = stale facial (UI/decay facial); NÃO expira body_continuity sozinho
    identity_face_missing_ttl_seconds: float = Field(default=12.0, env="IDENTITY_FACE_MISSING_TTL")
    identity_minimum_new_confidence: float = Field(default=0.75, env="IDENTITY_MIN_NEW_CONF")
    identity_minimum_margin: float = Field(default=0.10, env="IDENTITY_MIN_MARGIN")
    identity_confirmations_before_switch: int = Field(default=3, env="IDENTITY_CONFIRMATIONS")
    identity_switch_cooldown_seconds: float = Field(default=10.0, env="IDENTITY_SWITCH_COOLDOWN")
    identity_confidence_decay_per_second: float = Field(default=0.04, env="IDENTITY_CONF_DECAY")
    identity_body_continuity_uncertain_threshold: float = Field(
        default=0.45, env="IDENTITY_BODY_CONT_UNCERTAIN"
    )
    identity_temporarily_lost_uncertain_seconds: float = Field(
        default=4.0, env="IDENTITY_TEMP_LOST_UNCERTAIN"
    )
    person_tracking_enabled: bool = Field(default=True, env="PERSON_TRACKING_ENABLED")
    person_tracking_prefer_bytetrack: bool = Field(default=True, env="PERSON_TRACKING_BYTETRACK")
    person_tracking_model_path: str = Field(default="data/models/yolov8n.pt", env="PERSON_TRACKING_MODEL")
    person_tracking_ttl_seconds: float = Field(default=8.0, env="PERSON_TRACKING_TTL")
    person_tracking_max_time_lost_seconds: float = Field(default=8.0, env="PERSON_TRACKING_MAX_LOST")
    person_tracking_weak_max_time_lost_seconds: float = Field(
        default=2.0, env="PERSON_TRACKING_WEAK_MAX_LOST"
    )
    person_tracking_min_detection_confidence: float = Field(default=0.40, env="PERSON_TRACKING_MIN_CONF")
    person_tracking_min_reassociation_iou: float = Field(default=0.30, env="PERSON_TRACKING_MIN_IOU")
    person_tracking_max_center_distance_ratio: float = Field(default=0.35, env="PERSON_TRACKING_MAX_DIST")
    person_tracking_bytetrack_yaml: str = Field(
        default="data/trackers/bytetrack_person.yaml", env="PERSON_TRACKING_BT_YAML"
    )
    pose_body_enabled: bool = Field(default=True, env="POSE_BODY_ENABLED")
    pose_body_model_path: str = Field(
        default="data/mediapipe_models/pose_landmarker_lite.task", env="POSE_BODY_MODEL"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    def load_yaml_config(self, yaml_path: Optional[str] = None) -> None:
        """Carrega configurações adicionais de YAML."""
        if yaml_path is None:
            yaml_path = "config.yaml"
        
        yaml_file = Path(yaml_path)
        if not yaml_file.exists():
            return
        
        with open(yaml_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        # Device overrides
        if "device" in config:
            dev = config["device"]
            if "device_id" in dev:
                object.__setattr__(self, "device_id", dev["device_id"])
            if "school_id" in dev:
                object.__setattr__(self, "school_id", str(dev["school_id"]))
            if "default_camera_index" in dev:
                object.__setattr__(self, "default_camera_index", int(dev["default_camera_index"]))
            if "camera_connect_timeout_seconds" in dev:
                object.__setattr__(
                    self,
                    "camera_connect_timeout_seconds",
                    int(dev["camera_connect_timeout_seconds"]),
                )
        
        # Cameras (rtsp_url pode ser null → usa default_camera_index)
        if "cameras" in config:
            settings = self
            default_idx = str(getattr(settings, "default_camera_index", 0))
            cameras_list = []
            for cam in config["cameras"]:
                if cam.get("enabled", True):
                    rtsp_url = cam.get("rtsp_url")
                    if rtsp_url is None or (isinstance(rtsp_url, str) and rtsp_url.strip() == ""):
                        rtsp_url = default_idx
                    elif not isinstance(rtsp_url, str):
                        rtsp_url = str(rtsp_url)
                    w = cam.get("webcam_width")
                    h = cam.get("webcam_height")
                    cameras_list.append(CameraConfig(
                        camera_id=cam["camera_id"],
                        room_id=cam["room_id"],
                        rtsp_url=rtsp_url,
                        enabled=True,
                        webcam_width=int(w) if w is not None else None,
                        webcam_height=int(h) if h is not None else None,
                    ))
            object.__setattr__(self, "cameras", cameras_list)
        
        # Vision config
        if "vision" in config:
            vision = config["vision"]
            if "detector" in vision:
                object.__setattr__(self, "vision_detector_backend", str(vision["detector"]))
            if "embedder" in vision:
                object.__setattr__(self, "vision_embedder_backend", str(vision["embedder"]))
            if "max_faces" in vision:
                object.__setattr__(self, "vision_max_faces", int(vision["max_faces"]))
            if "mediapipe_min_confidence" in vision:
                object.__setattr__(
                    self, "vision_mediapipe_min_confidence", float(vision["mediapipe_min_confidence"])
                )
            if "insightface_det_size" in vision:
                object.__setattr__(self, "vision_insightface_det_size", int(vision["insightface_det_size"]))
            if "insightface_min_det_score" in vision:
                object.__setattr__(
                    self, "vision_insightface_min_det_score", float(vision["insightface_min_det_score"])
                )
            if "yunet_score_threshold" in vision:
                object.__setattr__(self, "vision_yunet_score_threshold", float(vision["yunet_score_threshold"]))
            if "min_face_area_ratio" in vision:
                object.__setattr__(self, "vision_min_face_area_ratio", float(vision["min_face_area_ratio"]))
            if "face_relative_min_fraction" in vision:
                object.__setattr__(
                    self, "vision_face_relative_min_fraction", float(vision["face_relative_min_fraction"])
                )
            if "single_subject_mode" in vision:
                object.__setattr__(self, "vision_single_subject_mode", bool(vision["single_subject_mode"]))
            if "face_aspect_min" in vision:
                object.__setattr__(self, "vision_face_aspect_min", float(vision["face_aspect_min"]))
            if "face_aspect_max" in vision:
                object.__setattr__(self, "vision_face_aspect_max", float(vision["face_aspect_max"]))
            if "presence" in vision:
                pres = vision["presence"]
                if "sampling_seconds" in pres:
                    object.__setattr__(self, "presence_sampling_seconds", pres["sampling_seconds"])
                if "threshold" in pres:
                    object.__setattr__(self, "presence_threshold", pres["threshold"])
                if "min_face_size" in pres:
                    object.__setattr__(self, "face_min_size", pres["min_face_size"])
                if "dedup_mode" in pres:
                    object.__setattr__(self, "presence_dedup_mode", pres["dedup_mode"])
                if "always_on" in pres:
                    object.__setattr__(self, "presence_always_on", bool(pres["always_on"]))
                if "match_margin" in pres:
                    object.__setattr__(self, "presence_match_margin", float(pres["match_margin"]))
                if "th_on" in pres:
                    object.__setattr__(self, "presence_th_on", float(pres["th_on"]))
                if "th_off" in pres:
                    object.__setattr__(self, "presence_th_off", float(pres["th_off"]))
                if "track_ttl_seconds" in pres:
                    object.__setattr__(self, "track_ttl_seconds", float(pres["track_ttl_seconds"]))
                if "max_templates_per_student" in pres:
                    object.__setattr__(self, "max_templates_per_student", int(pres["max_templates_per_student"]))
            
            if "dnn_conf_threshold" in vision:
                object.__setattr__(self, "vision_dnn_conf_threshold", float(vision["dnn_conf_threshold"]))
            if "engagement" in vision:
                eng = vision["engagement"]
                if "sampling_seconds" in eng:
                    object.__setattr__(self, "engagement_sampling_seconds", eng["sampling_seconds"])
                if "window_seconds" in eng:
                    object.__setattr__(self, "vision_engagement_window_seconds", int(eng["window_seconds"]))
                if "backend" in eng:
                    object.__setattr__(self, "vision_engagement_backend", str(eng["backend"]))
                if "model_version" in eng:
                    object.__setattr__(self, "vision_engagement_model_version", str(eng["model_version"]))
            if "climate" in vision:
                cl = vision["climate"]
                if "use_fer" in cl:
                    object.__setattr__(self, "climate_use_fer", bool(cl["use_fer"]))
                if "window_seconds" in cl:
                    object.__setattr__(self, "climate_window_seconds", int(cl["window_seconds"]))
            if "behavioral" in vision:
                beh = vision["behavioral"]
                if "enabled" in beh:
                    object.__setattr__(self, "behavioral_signals_enabled", bool(beh["enabled"]))
            if "phone_yolo" in vision:
                py = vision["phone_yolo"]
                if "enabled" in py:
                    object.__setattr__(self, "phone_yolo_enabled", bool(py["enabled"]))
                if "model_path" in py:
                    object.__setattr__(self, "phone_yolo_model_path", str(py["model_path"]))
                if "conf_threshold" in py:
                    object.__setattr__(self, "phone_yolo_conf_threshold", float(py["conf_threshold"]))
                if "max_height_width_ratio" in py:
                    object.__setattr__(self, "phone_yolo_max_height_width_ratio", float(py["max_height_width_ratio"]))
                if "max_width_height_ratio" in py:
                    object.__setattr__(self, "phone_yolo_max_width_height_ratio", float(py["max_width_height_ratio"]))
                if "torso_pass_enabled" in py:
                    object.__setattr__(self, "phone_yolo_torso_pass_enabled", bool(py["torso_pass_enabled"]))
                if "torso_conf_threshold" in py:
                    object.__setattr__(self, "phone_yolo_torso_conf_threshold", float(py["torso_conf_threshold"]))
        
        # Enrollment config
        if "enrollment" in config:
            enroll = config["enrollment"]
            if "num_frames" in enroll:
                object.__setattr__(self, "enroll_num_frames", int(enroll["num_frames"]))
            if "frames_used" in enroll:
                object.__setattr__(self, "enroll_frames_used", int(enroll["frames_used"]))
            if "capture_duration_seconds" in enroll:
                object.__setattr__(self, "enroll_capture_duration", float(enroll["capture_duration_seconds"]))

        # Sync config
        if "sync" in config:
            sync = config["sync"]
            # Usar object.__setattr__ para bypassar validação do Pydantic durante carregamento
            object.__setattr__(self, "sync_batch_size", sync.get("batch_size", self.sync_batch_size))
            object.__setattr__(self, "sync_retry_attempts", sync.get("retry_attempts", self.sync_retry_attempts))
            object.__setattr__(self, "sync_retry_backoff_seconds", sync.get("retry_backoff_seconds", self.sync_retry_backoff_seconds))
            object.__setattr__(self, "sync_interval_seconds", sync.get("sync_interval_seconds", self.sync_interval_seconds))

        # Backup (DAT): dir pode vir do YAML; passphrase apenas por env (segurança)
        if "backup" in config:
            bk = config["backup"]
            if "dir" in bk:
                object.__setattr__(self, "backup_dir", str(bk["dir"]))

        # Runtime / experimental
        if "runtime" in config and isinstance(config["runtime"], dict):
            rm = config["runtime"]
            if "mode" in rm:
                object.__setattr__(self, "runtime_mode", str(rm["mode"]).lower())
        if "experimental" in config and isinstance(config["experimental"], dict):
            exp = config["experimental"]
            if "sqlite_005_enabled" in exp:
                object.__setattr__(self, "experimental_sqlite_005_enabled", bool(exp["sqlite_005_enabled"]))
            if "longitudinal_approval_recorded" in exp:
                object.__setattr__(
                    self, "longitudinal_approval_recorded", bool(exp["longitudinal_approval_recorded"])
                )
            if "perclos_enabled" in exp:
                object.__setattr__(self, "experimental_perclos_enabled", bool(exp["perclos_enabled"]))
            if "perclos_window_seconds" in exp:
                object.__setattr__(
                    self, "experimental_perclos_window_seconds", float(exp["perclos_window_seconds"])
                )
            if "perclos_min_coverage" in exp:
                object.__setattr__(
                    self, "experimental_perclos_min_coverage", float(exp["perclos_min_coverage"])
                )

        # Módulos (modos) + provenance
        if "modules" in config:
            mods = config["modules"] or {}
            mapping = {
                "expression": "module_expression_mode",
                "face_landmarks": "module_face_landmarks_mode",
                "person_tracking": "module_person_tracking_mode",
                "phone": "module_phone_mode",
                "pose": "module_pose_mode",
                "temporal_fusion": "module_temporal_fusion_mode",
                "educational_dashboard": "module_educational_dashboard_mode",
                "lxp": "module_lxp_mode",
            }
            for key, attr in mapping.items():
                block = mods.get(key)
                if isinstance(block, dict) and "mode" in block:
                    object.__setattr__(self, attr, str(block["mode"]).lower())
                elif isinstance(block, str):
                    object.__setattr__(self, attr, block.lower())
        if "expression" in config and isinstance(config["expression"], dict):
            ex = config["expression"]
            if "provider" in ex:
                object.__setattr__(self, "expression_provider", str(ex["provider"]))
            if "emotion_backend" in ex:
                object.__setattr__(
                    self, "expression_emotion_backend", str(ex["emotion_backend"]).strip().lower()
                )
            if "hsemotion_interval_seconds" in ex:
                object.__setattr__(
                    self,
                    "expression_hsemotion_interval_seconds",
                    float(ex["hsemotion_interval_seconds"]),
                )
            if "hsemotion_max_batch" in ex:
                object.__setattr__(
                    self, "expression_hsemotion_max_batch", int(ex["hsemotion_max_batch"])
                )
            for yk, attr in (
                ("interval_seconds", "expression_interval_seconds"),
                ("window_seconds", "expression_window_seconds"),
                ("minimum_samples", "expression_minimum_samples"),
                ("minimum_confidence", "expression_minimum_confidence"),
                ("minimum_confidence_positive", "expression_minimum_confidence_positive"),
                ("minimum_confidence_negative", "expression_minimum_confidence_negative"),
                ("minimum_negative_samples", "expression_minimum_negative_samples"),
                ("negative_min_seconds", "expression_negative_min_seconds"),
                ("minimum_observation_quality", "expression_minimum_observation_quality"),
            ):
                if yk in ex:
                    object.__setattr__(self, attr, type(getattr(self, attr))(ex[yk]))
            if "smile_boost_enabled" in ex:
                object.__setattr__(self, "expression_smile_boost_enabled", bool(ex["smile_boost_enabled"]))
            if "frown_boost_enabled" in ex:
                object.__setattr__(self, "expression_frown_boost_enabled", bool(ex["frown_boost_enabled"]))
            if "ab_secondary" in ex:
                object.__setattr__(
                    self,
                    "expression_ab_secondary",
                    None if ex["ab_secondary"] in (None, "", "none") else str(ex["ab_secondary"]),
                )
            if "fallback_chain" in ex:
                fc = ex["fallback_chain"]
                if isinstance(fc, (list, tuple)):
                    object.__setattr__(self, "expression_fallback_chain", ",".join(str(x) for x in fc))
                else:
                    object.__setattr__(self, "expression_fallback_chain", str(fc))
        if "analytics" in config and isinstance(config["analytics"], dict):
            an = config["analytics"]
            if "quality_interval_seconds" in an:
                object.__setattr__(self, "analytics_quality_interval_seconds", float(an["quality_interval_seconds"]))
            if "landmarks_interval_seconds" in an:
                object.__setattr__(
                    self, "analytics_landmarks_interval_seconds", float(an["landmarks_interval_seconds"])
                )
        if "visual_attention" in config and isinstance(config["visual_attention"], dict):
            va = config["visual_attention"]
            if "window_seconds" in va:
                object.__setattr__(self, "visual_attention_window_seconds", float(va["window_seconds"]))
            if "minimum_observation_quality" in va:
                object.__setattr__(
                    self,
                    "visual_attention_minimum_observation_quality",
                    float(va["minimum_observation_quality"]),
                )
        if "drowsiness" in config and isinstance(config["drowsiness"], dict):
            dr = config["drowsiness"]
            for yk, attr in (
                ("possible_after_seconds", "drowsiness_possible_after_seconds"),
                ("probable_after_seconds", "drowsiness_probable_after_seconds"),
                ("minimum_observation_quality", "drowsiness_minimum_observation_quality"),
                ("cooldown_seconds", "drowsiness_cooldown_seconds"),
                ("eye_closed_ear_threshold", "drowsiness_eye_closed_ear_threshold"),
                ("head_down_possible_multiplier", "drowsiness_head_down_possible_multiplier"),
                ("head_down_probable_seconds", "drowsiness_head_down_probable_seconds"),
                ("observation_gap_inconclusive_seconds", "drowsiness_observation_gap_inconclusive_seconds"),
            ):
                if yk in dr:
                    object.__setattr__(self, attr, float(dr[yk]))
        if "phone" in config and isinstance(config["phone"], dict):
            ph = config["phone"]
            if "possible_after_seconds" in ph:
                object.__setattr__(self, "phone_possible_after_seconds", float(ph["possible_after_seconds"]))
            if "probable_after_seconds" in ph:
                object.__setattr__(self, "phone_probable_after_seconds", float(ph["probable_after_seconds"]))
            if "interaction_requires_in_hand" in ph:
                object.__setattr__(self, "phone_interaction_requires_in_hand", bool(ph["interaction_requires_in_hand"]))
            if "association_clear_hold_seconds" in ph:
                object.__setattr__(
                    self,
                    "phone_association_clear_hold_seconds",
                    float(ph["association_clear_hold_seconds"]),
                )
        if "provenance" in config and isinstance(config["provenance"], dict):
            pr = config["provenance"]
            for k, attr in (
                ("rule_engine_version", "rule_engine_version"),
                ("threshold_profile", "threshold_profile"),
                ("camera_calibration_version", "camera_calibration_version"),
            ):
                if k in pr:
                    object.__setattr__(self, attr, str(pr[k]))
        if "identity_binding" in config and isinstance(config["identity_binding"], dict):
            ib = config["identity_binding"]
            for yk, attr in (
                ("face_missing_ttl_seconds", "identity_face_missing_ttl_seconds"),
                ("minimum_new_identity_confidence", "identity_minimum_new_confidence"),
                ("minimum_identity_margin", "identity_minimum_margin"),
                ("confirmations_before_switch", "identity_confirmations_before_switch"),
                ("identity_switch_cooldown_seconds", "identity_switch_cooldown_seconds"),
                ("confidence_decay_per_second", "identity_confidence_decay_per_second"),
                ("body_continuity_uncertain_threshold", "identity_body_continuity_uncertain_threshold"),
                ("temporarily_lost_uncertain_seconds", "identity_temporarily_lost_uncertain_seconds"),
            ):
                if yk in ib:
                    object.__setattr__(self, attr, type(getattr(self, attr))(ib[yk]))
        if "person_tracking" in config and isinstance(config["person_tracking"], dict):
            pt = config["person_tracking"]
            if "enabled" in pt:
                object.__setattr__(self, "person_tracking_enabled", bool(pt["enabled"]))
            if "prefer_bytetrack" in pt:
                object.__setattr__(self, "person_tracking_prefer_bytetrack", bool(pt["prefer_bytetrack"]))
            if "model_path" in pt:
                object.__setattr__(self, "person_tracking_model_path", str(pt["model_path"]))
            if "ttl_seconds" in pt:
                object.__setattr__(self, "person_tracking_ttl_seconds", float(pt["ttl_seconds"]))
            if "max_time_lost_seconds" in pt:
                object.__setattr__(self, "person_tracking_max_time_lost_seconds", float(pt["max_time_lost_seconds"]))
            if "weak_max_time_lost_seconds" in pt:
                object.__setattr__(
                    self,
                    "person_tracking_weak_max_time_lost_seconds",
                    float(pt["weak_max_time_lost_seconds"]),
                )
            if "minimum_detection_confidence" in pt:
                object.__setattr__(
                    self, "person_tracking_min_detection_confidence", float(pt["minimum_detection_confidence"])
                )
            if "minimum_reassociation_iou" in pt:
                object.__setattr__(
                    self, "person_tracking_min_reassociation_iou", float(pt["minimum_reassociation_iou"])
                )
            if "maximum_center_distance_ratio" in pt:
                object.__setattr__(
                    self,
                    "person_tracking_max_center_distance_ratio",
                    float(pt["maximum_center_distance_ratio"]),
                )
            if "bytetrack_yaml" in pt:
                object.__setattr__(self, "person_tracking_bytetrack_yaml", str(pt["bytetrack_yaml"]))
        if "face_occlusion" in config and isinstance(config["face_occlusion"], dict):
            fo = config["face_occlusion"]
            mapping = {
                "wrist_near_ratio": "face_occlusion_wrist_near_ratio",
                "confirm_seconds": "face_occlusion_confirm_seconds",
                "clear_hold_seconds": "face_occlusion_clear_hold_seconds",
                "face_missing_hold_seconds": "face_occlusion_face_missing_hold_seconds",
                "persistent_seconds": "face_occlusion_persistent_seconds",
                "suppress_when_landmarks_clear": "face_occlusion_suppress_when_landmarks_clear",
            }
            for k, attr in mapping.items():
                if k in fo:
                    val = fo[k]
                    object.__setattr__(self, attr, bool(val) if k.startswith("suppress") else float(val))
        if "behavioral_events" in config and isinstance(config["behavioral_events"], dict):
            be = config["behavioral_events"]
            if "clear_hold_seconds" in be:
                object.__setattr__(
                    self, "behavioral_event_clear_hold_seconds", float(be["clear_hold_seconds"])
                )
            if "clear_hold_drowsiness_seconds" in be:
                object.__setattr__(
                    self,
                    "behavioral_event_clear_hold_drowsiness_seconds",
                    float(be["clear_hold_drowsiness_seconds"]),
                )
            if "clear_hold_phone_seconds" in be:
                object.__setattr__(
                    self,
                    "behavioral_event_clear_hold_phone_seconds",
                    float(be["clear_hold_phone_seconds"]),
                )
        if "head_down" in config and isinstance(config["head_down"], dict):
            hd = config["head_down"]
            if "pitch_threshold" in hd:
                object.__setattr__(self, "head_down_pitch_threshold", float(hd["pitch_threshold"]))
            if "event_min_seconds" in hd:
                object.__setattr__(self, "head_down_event_min_seconds", float(hd["event_min_seconds"]))
            if "short_to_persistent_seconds" in hd:
                object.__setattr__(
                    self,
                    "head_down_short_to_persistent_seconds",
                    float(hd["short_to_persistent_seconds"]),
                )
            if "require_landmarks_quality" in hd:
                object.__setattr__(
                    self,
                    "head_down_require_landmarks_quality",
                    float(hd["require_landmarks_quality"]),
                )
            if "suppress_when_occlusion" in hd:
                object.__setattr__(
                    self,
                    "head_down_suppress_when_occlusion",
                    bool(hd["suppress_when_occlusion"]),
                )
            if "allow_face_missing_proxy" in hd:
                object.__setattr__(
                    self,
                    "head_down_allow_face_missing_proxy",
                    bool(hd["allow_face_missing_proxy"]),
                )
            if "inconclusive_hold_seconds" in hd:
                object.__setattr__(
                    self,
                    "head_down_inconclusive_hold_seconds",
                    float(hd["inconclusive_hold_seconds"]),
                )
        if "pose_body" in config and isinstance(config["pose_body"], dict):
            pb = config["pose_body"]
            if "enabled" in pb:
                object.__setattr__(self, "pose_body_enabled", bool(pb["enabled"]))
            if "model_path" in pb:
                object.__setattr__(self, "pose_body_model_path", str(pb["model_path"]))
        if "privacy" in config and isinstance(config["privacy"], dict):
            priv = config["privacy"]
            if "demo_db_path" in priv and not os.environ.get("DEMO_DB_PATH"):
                object.__setattr__(self, "demo_db_path", str(priv["demo_db_path"]))

        self._validate_inference_module_modes()

    def _validate_inference_module_modes(self) -> None:
        """Inferência real não pode ir a production sem aprovação longitudinal."""
        from app.module_modes import parse_module_mode, ModuleMode

        inference_attrs = (
            "module_expression_mode",
            "module_face_landmarks_mode",
            "module_person_tracking_mode",
            "module_phone_mode",
            "module_pose_mode",
            "module_temporal_fusion_mode",
        )
        for attr in inference_attrs:
            mode = parse_module_mode(getattr(self, attr, "disabled"))
            if mode == ModuleMode.PRODUCTION and not self.longitudinal_approval_recorded:
                # Rebaixa silenciosamente para shadow (não derruba app)
                object.__setattr__(self, attr, ModuleMode.SHADOW.value)


# Singleton global
_settings: Optional[Settings] = None


def _resolve_yaml_paths() -> list:
    """Base config.yaml + overlay opcional (ex.: config.tri.yaml via PRESENCA_CONFIG_OVERLAY)."""
    import os

    base = os.environ.get("PRESENCA_CONFIG") or os.environ.get("CONFIG_YAML") or "config.yaml"
    paths = [base]
    overlay = (os.environ.get("PRESENCA_CONFIG_OVERLAY") or "").strip()
    if overlay:
        paths.append(overlay)
    return paths


def _apply_expression_env_overrides(settings: "Settings") -> None:
    """Reaplica env de expressão após YAML (permite TRI sem editar config.yaml).

    Nomes aceitos (exatos):
      EXPRESSION_PROVIDER
      EXPRESSION_FALLBACK_CHAIN
      MODULE_EXPRESSION_MODE
    """
    import os

    prov = os.environ.get("EXPRESSION_PROVIDER")
    if prov is not None and str(prov).strip() != "":
        object.__setattr__(settings, "expression_provider", str(prov).strip())
    mode = os.environ.get("MODULE_EXPRESSION_MODE")
    if mode is not None and str(mode).strip() != "":
        object.__setattr__(settings, "module_expression_mode", str(mode).strip().lower())
    chain = os.environ.get("EXPRESSION_FALLBACK_CHAIN")
    if chain is not None and str(chain).strip() != "":
        object.__setattr__(settings, "expression_fallback_chain", str(chain).strip())
    elif prov is not None and str(prov).strip().lower() in ("fer_onnx", "ferplus", "emotion_ferplus"):
        # Evita fallback silencioso para HSEmotion/DeepFace quando só o provider TRI é setado via env
        object.__setattr__(settings, "expression_fallback_chain", "fer_onnx")
    backend = os.environ.get("EXPRESSION_EMOTION_BACKEND")
    if backend is not None and str(backend).strip() != "":
        object.__setattr__(
            settings, "expression_emotion_backend", str(backend).strip().lower()
        )
    hs_iv = os.environ.get("EXPRESSION_HSEMOTION_INTERVAL")
    if hs_iv is not None and str(hs_iv).strip() != "":
        object.__setattr__(
            settings, "expression_hsemotion_interval_seconds", float(hs_iv)
        )


def _log_settings_loaded(settings: "Settings", paths: list) -> None:
    """Registra quais YAMLs e provider de expressão ficaram ativos."""
    import logging
    from pathlib import Path

    resolved = []
    missing = []
    for p in paths:
        path = Path(p)
        if path.is_file():
            resolved.append(str(path.resolve()))
        else:
            missing.append(str(p))
    logging.getLogger("app.config").info(
        "settings_loaded base_and_overlay=%s missing=%s expression_provider=%s "
        "expression_fallback_chain=%s module_expression_mode=%s overlay_env=%s",
        resolved,
        missing or None,
        getattr(settings, "expression_provider", None),
        getattr(settings, "expression_fallback_chain", None),
        getattr(settings, "module_expression_mode", None),
        __import__("os").environ.get("PRESENCA_CONFIG_OVERLAY") or None,
    )


def get_settings() -> Settings:
    """Retorna instância singleton das configurações."""
    global _settings
    if _settings is None:
        paths = _resolve_yaml_paths()
        _settings = Settings()
        for path in paths:
            _settings.load_yaml_config(path)
        _apply_expression_env_overrides(_settings)
        _settings._validate_inference_module_modes()
        _log_settings_loaded(_settings, paths)
    return _settings


def reload_settings() -> Settings:
    """Recarrega as configurações."""
    global _settings
    paths = _resolve_yaml_paths()
    _settings = Settings()
    for path in paths:
        _settings.load_yaml_config(path)
    _apply_expression_env_overrides(_settings)
    _settings._validate_inference_module_modes()
    _log_settings_loaded(_settings, paths)
    return _settings
