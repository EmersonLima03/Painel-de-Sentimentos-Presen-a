"""Orquestrador principal do pipeline."""

import asyncio
import time
from typing import Dict, Optional
import numpy as np

from app.rtsp.reader import RTSPReader
from app.rtsp.watchdog import RTSPWatchdog
from app.vision.detector import create_detector
from app.vision.embedder import create_embedder
from app.vision.matcher import (
    FaceMatcher,
    FAISSMatcher,
    load_embeddings_from_face_embeddings,
)
from app.pipeline.presence import PresencePipeline
from app.pipeline.analytics import EngagementAnalytics
from app.db.init_db import get_session
from app.db.repo import (
    EventRepository,
    AttendanceRepository,
    FaceEmbeddingRepository,
)
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Orquestra processamento de múltiplas câmeras."""
    
    def __init__(self):
        self.settings = get_settings()
        self.running = False
        
        # RTSP readers
        self.readers: Dict[str, RTSPReader] = {}
        self.watchdog: Optional[RTSPWatchdog] = None
        
        # Pipelines por câmera
        self.presence_pipelines: Dict[str, PresencePipeline] = {}
        self.engagement_analytics: Dict[str, EngagementAnalytics] = {}
        
        # Timers de sampling
        self.last_presence_sample: Dict[str, float] = {}
        self.last_engagement_sample: Dict[str, float] = {}
        
        # Métricas por câmera
        self.faces_detected_last: Dict[str, int] = {}
        self.last_presence_match: Dict[str, dict] = {}  # {camera_id: list of {student_id, confidence, timestamp}}
        self.last_presence_event_id: Dict[str, Optional[str]] = {}  # event_id do último check-in (ou None)
    
    def initialize(self) -> None:
        """Inicializa todos os componentes."""
        logger.info("orchestrator_initializing")
        
        # Pular RTSP se desabilitado
        if getattr(self.settings, 'disable_rtsp', False) or not self.settings.cameras:
            logger.info("rtsp_disabled_by_config", cameras_count=len(self.settings.cameras))
            self.watchdog = None
            return
        
        default_idx = getattr(self.settings, "default_camera_index", 0)
        for cam_config in self.settings.cameras:
            reader = RTSPReader(
                camera_id=cam_config.camera_id,
                rtsp_url=cam_config.rtsp_url,
                default_camera_index=default_idx,
                webcam_width=getattr(cam_config, "webcam_width", None),
                webcam_height=getattr(cam_config, "webcam_height", None),
            )
            self.readers[cam_config.camera_id] = reader
            self.last_presence_sample[cam_config.camera_id] = 0.0
            self.last_engagement_sample[cam_config.camera_id] = 0.0
        
        # Criar watchdog apenas se há readers
        if self.readers:
            self.watchdog = RTSPWatchdog(self.readers)
        else:
            self.watchdog = None
        
        # Criar componentes de visão (compartilhados)
        detector = create_detector()
        embedder = create_embedder()
        
        # Criar pipelines por câmera
        session = get_session()
        event_repo = EventRepository(session)
        attendance_repo = AttendanceRepository(session)
        face_embedding_repo = FaceEmbeddingRepository(session)

        face_embeddings = face_embedding_repo.get_all_active_embeddings(
            school_id=self.settings.school_id
        )
        embeddings = load_embeddings_from_face_embeddings(face_embeddings)
        logger.info("orchestrator_loading_embeddings", source="face_embeddings", count=len(embeddings))
        
        # Criar matcher (tentar FAISS, fallback para linear)
        try:
            if len(embeddings) > 0:
                embedding_dim = len(embeddings[0][1])
                base_matcher = FAISSMatcher(embeddings, dim=embedding_dim)
                logger.info("orchestrator_using_faiss", count=len(embeddings), dim=embedding_dim)
            else:
                base_matcher = FAISSMatcher([], dim=512)  # Dimensão padrão
                logger.info("orchestrator_using_faiss_empty")
        except Exception as e:
            logger.warning("FAISS disabled: %s (using linear fallback)", str(e))
            base_matcher = FaceMatcher(embeddings)
        
        for cam_config in self.settings.cameras:
            camera_id = cam_config.camera_id
            room_id = cam_config.room_id
            
            # Pipeline de presença
            presence_pipeline = PresencePipeline(
                detector=detector,
                embedder=embedder,
                matcher=base_matcher,
                event_repo=event_repo,
                attendance_repo=attendance_repo,
                face_embedding_repo=face_embedding_repo,
                camera_id=camera_id,
                room_id=room_id,
                device_id=self.settings.device_id,
                school_id=self.settings.school_id
            )
            self.presence_pipelines[camera_id] = presence_pipeline
            
            # Analytics de engajamento
            engagement = EngagementAnalytics(
                detector=detector,
                event_repo=event_repo,
                camera_id=camera_id,
                room_id=room_id,
                device_id=self.settings.device_id,
                school_id=self.settings.school_id,
                window_seconds=10
            )
            self.engagement_analytics[camera_id] = engagement
        
        logger.info("orchestrator_initialized", num_cameras=len(self.readers))
    
    async def start(self) -> None:
        """Inicia processamento assíncrono."""
        self.running = True
        
        # Se não há readers (RTSP desabilitado), apenas manter rodando
        if not self.readers:
            logger.info("orchestrator_no_cameras", message="RTSP desabilitado ou sem câmeras")
            while self.running:
                await asyncio.sleep(10)  # Sleep longo quando não há câmeras
            return
        
        # Conectar todos os readers em thread com timeout (evita travar se câmera não responder)
        loop = asyncio.get_event_loop()
        connect_timeout = getattr(self.settings, "camera_connect_timeout_seconds", 15)
        for camera_id, reader in self.readers.items():
            try:
                await asyncio.wait_for(loop.run_in_executor(None, reader.connect), timeout=connect_timeout)
            except asyncio.TimeoutError:
                logger.warning("rtsp_connect_timeout", camera_id=camera_id, timeout_seconds=connect_timeout)
            except Exception as e:
                logger.warning("rtsp_connect_error", camera_id=camera_id, error=str(e))
        
        logger.info("orchestrator_started")
        
        # Loop principal
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                # Verificar conexões em thread (evita bloquear)
                if self.watchdog:
                    await loop.run_in_executor(None, self.watchdog.check_all)
                
                # Processar cada câmera (só se há readers)
                if self.readers:
                    for camera_id, reader in self.readers.items():
                        if not reader.is_connected:
                            continue
                        
                        # Ler frame em thread (evita bloquear event loop / CTRL+C)
                        ret, frame = await loop.run_in_executor(None, reader.read_frame)
                        if not ret or frame is None:
                            continue
                        
                        current_time = time.time()
                        
                        # Detectar faces para métricas (sempre, mesmo se não for processar presença)
                        pipeline = self.presence_pipelines.get(camera_id)
                        if pipeline:
                            try:
                                faces = pipeline.detector.detect(frame)
                                self.faces_detected_last[camera_id] = len(faces)
                                
                                # Log periódico para debug (a cada 5 segundos)
                                if int(current_time) % 5 == 0 and int(current_time) != int(self.last_presence_sample.get(camera_id, 0)):
                                    logger.debug("face_detection_debug", 
                                               camera_id=camera_id, 
                                               faces_detected=len(faces),
                                               detector_type=type(pipeline.detector).__name__)
                            except Exception as e:
                                logger.warning("face_detection_error", camera_id=camera_id, error=str(e))
                        
                        # Sampling de presença
                        if current_time - self.last_presence_sample.get(camera_id, 0) >= self.settings.presence_sampling_seconds:
                            if pipeline:
                                try:
                                    result = pipeline.process_frame(frame)
                                    # Atualizar métrica apenas quando houver match (não sobrescrever com [] em "faces sem match")
                                    if result and "matches" in result:
                                        match_list = result["matches"]
                                        if match_list:
                                            self.last_presence_match[camera_id] = [
                                                {
                                                    "student_id": m.get("student_id"),
                                                    "confidence": m.get("confidence", 0.0),
                                                    "timestamp": current_time,
                                                    "bbox": m.get("bbox"),
                                                }
                                                for m in match_list
                                            ]
                                            logger.info("presence_match_detected", 
                                                       camera_id=camera_id,
                                                       student_ids=[m.get("student_id") for m in match_list])
                                except Exception as e:
                                    logger.warning("presence_pipeline_error", camera_id=camera_id, error=str(e))
                            self.last_presence_sample[camera_id] = current_time
                        
                        # Sampling de engajamento
                        if current_time - self.last_engagement_sample.get(camera_id, 0) >= self.settings.engagement_sampling_seconds:
                            analytics = self.engagement_analytics.get(camera_id)
                            if analytics:
                                analytics.process_frame(frame)
                            self.last_engagement_sample[camera_id] = current_time
                
                # Sleep curto para não sobrecarregar CPU
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error("orchestrator_error", error=str(e))
                await asyncio.sleep(1.0)
    
    def stop(self) -> None:
        """Para processamento."""
        self.running = False
        for reader in self.readers.values():
            reader.disconnect()
        logger.info("orchestrator_stopped")
    
    def get_status(self) -> dict:
        """Retorna status do orchestrator."""
        camera_status = {}
        for camera_id, reader in self.readers.items():
            camera_status[camera_id] = {
                **reader.get_status(),
                "faces_detected_last": self.faces_detected_last.get(camera_id, 0),
                "last_presence_match": self.last_presence_match.get(camera_id),
                "last_presence_event_id": self.last_presence_event_id.get(camera_id),
            }
        
        return {
            "running": self.running,
            "cameras": camera_status
        }
    
    def get_vision_backends(self) -> dict:
        """Retorna backends de visão (detector, embedder, faiss) para observabilidade."""
        if not self.presence_pipelines:
            return {
                "detector_backend": "none",
                "embedder_backend": "none",
                "faiss_enabled": False,
            }
        pipeline = next(iter(self.presence_pipelines.values()))
        detector = pipeline.detector
        embedder = pipeline.embedder
        matcher = pipeline.matcher
        
        # Mapear classes para strings amigáveis (mediapipe_tasks = Tasks API)
        detector_map = {
            "MediaPipeDetector": "mediapipe_tasks",
            "InsightFaceDetector": "insightface",
            "YuNetDetector": "yunet",
            "OpenCVHaarDetector": "opencv_haar",
            "SimulationDetector": "simulation",
        }
        embedder_map = {
            "FaceNetEmbedder": "facenet",
            "InsightFaceEmbedder": "insightface",
            "DeterministicEmbedder": "deterministic",
            "SimulationEmbedder": "simulation",
        }
        
        detector_backend = detector_map.get(type(detector).__name__, type(detector).__name__.lower())
        embedder_backend = embedder_map.get(type(embedder).__name__, type(embedder).__name__.lower())
        faiss_enabled = type(matcher).__name__ == "FAISSMatcher"
        
        return {
            "detector_backend": detector_backend,
            "embedder_backend": embedder_backend,
            "faiss_enabled": faiss_enabled,
        }
