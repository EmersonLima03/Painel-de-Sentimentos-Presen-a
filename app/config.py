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
    camera_connect_timeout_seconds: int = Field(default=3, env="CAMERA_CONNECT_TIMEOUT_SECONDS")
    
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


# Singleton global
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Retorna instância singleton das configurações."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.load_yaml_config()
    return _settings


def reload_settings() -> Settings:
    """Recarrega as configurações."""
    global _settings
    _settings = Settings()
    _settings.load_yaml_config()
    return _settings
