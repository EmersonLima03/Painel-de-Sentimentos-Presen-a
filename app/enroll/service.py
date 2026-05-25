"""Serviço de enrollment de faces."""

import cv2
import numpy as np
import time
from typing import Optional, Dict
from app.vision.detector import create_detector
from app.vision.embedder import create_embedder
from app.vision.quality import calculate_face_quality
from app.db.init_db import get_session
from app.db.repo import StudentRepository, FaceEmbeddingRepository
from app.rtsp.reader import RTSPReader
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


class EnrollmentService:
    """Serviço para cadastrar faces de alunos."""
    
    def __init__(self):
        self.detector = create_detector()
        self.embedder = create_embedder()
    
    def enroll_from_image(self, image_path: str, student_id: str) -> bool:
        """
        Cadastra face a partir de imagem local.
        
        Retorna: True se sucesso.
        """
        try:
            # Carregar imagem
            image = cv2.imread(image_path)
            if image is None:
                logger.error("enroll_image_not_found", path=image_path)
                return False
            
            return self.enroll_from_frame(image, student_id)
            
        except Exception as e:
            logger.error("enroll_error", student_id=student_id, error=str(e))
            return False
    
    def enroll_from_frame(self, frame: np.ndarray, student_id: str) -> bool:
        """
        Cadastra face a partir de frame.
        
        Retorna: True se sucesso.
        """
        try:
            # Detectar face
            faces = self.detector.detect(frame)
            if not faces:
                logger.warning("enroll_no_face_detected", student_id=student_id)
                return False
            
            # Usar primeira face detectada
            x, y, w, h = faces[0]
            face_roi = frame[y:y+h, x:x+w]
            
            # Gerar embedding
            embedding = self.embedder.embed(face_roi)
            if embedding is None:
                logger.warning("enroll_embedding_failed", student_id=student_id)
                return False
            
            # Salvar no banco
            session = get_session()
            settings = get_settings()
            student_repo = StudentRepository(session)
            embedding_repo = FaceEmbeddingRepository(session)

            student_repo.create_student(
                student_id=student_id,
                school_id=settings.school_id,
                room_id=None,
                is_active=True
            )
            embedding_repo.create_embedding(
                student_id=student_id,
                device_id=settings.device_id,
                school_id=settings.school_id,
                embedding_vector=embedding.tolist(),
                room_id=None,
                embedding_dim=len(embedding),
                model_name="facenet",
                model_version=self.embedder.get_model_version() if hasattr(self.embedder, 'get_model_version') else "facenet-pytorch-vggface2-512d-v1",
                quality_score=None
            )

            logger.info("enroll_success", student_id=student_id)
            return True
            
        except Exception as e:
            logger.error("enroll_error", student_id=student_id, error=str(e))
            return False
    
    def enroll_from_webcam(
        self,
        camera_id: str,
        student_id: str,
        full_name: Optional[str] = None,
        num_frames: Optional[int] = None,
        frames_used: Optional[int] = None,
        capture_duration: Optional[float] = None,
        append_template: bool = False,
        dry_run: bool = False,
        min_quality_score: float = 0.45,
        min_good_frames: int = 3,
        reader=None
    ) -> Dict:
        """
        Cadastra face capturando múltiplos frames; média dos melhores embeddings.
        append_template=False: substitui todos os templates do aluno por este (comportamento atual).
        append_template=True: adiciona mais um template (até max_templates_per_student); ex.: óculos/sem óculos.
        """
        settings = get_settings()
        num_frames = num_frames if num_frames is not None else getattr(settings, "enroll_num_frames", 15)
        frames_used = frames_used if frames_used is not None else getattr(settings, "enroll_frames_used", 10)
        capture_duration = capture_duration if capture_duration is not None else getattr(settings, "enroll_capture_duration", 5.0)
        max_templates = getattr(settings, "max_templates_per_student", 7)
        should_disconnect = False
        
        # Se não forneceu reader, criar novo
        if reader is None:
            # Buscar câmera no config (camera_id "0" = primeira câmera com rtsp_url "0")
            rtsp_url = None
            w_res = h_res = None
            for cam_config in settings.cameras:
                if cam_config.camera_id == camera_id:
                    rtsp_url = cam_config.rtsp_url
                    w_res = getattr(cam_config, "webcam_width", None)
                    h_res = getattr(cam_config, "webcam_height", None)
                    break
            if not rtsp_url and camera_id == "0":
                for cam_config in settings.cameras:
                    if str(cam_config.rtsp_url) == "0":
                        rtsp_url = "0"
                        camera_id = cam_config.camera_id
                        break
            if not rtsp_url:
                return {
                    "status": "error",
                    "error": f"Camera {camera_id} not found in config. Use camera_id from config.yaml (e.g. cam-web)."
                }
            
            try:
                # Criar reader temporário
                reader = RTSPReader(
                    camera_id=camera_id,
                    rtsp_url=rtsp_url,
                    default_camera_index=getattr(settings, "default_camera_index", 0),
                    webcam_width=w_res,
                    webcam_height=h_res,
                )
                if not reader.connect():
                    return {
                        "status": "error",
                        "error": "Failed to connect to camera"
                    }
                should_disconnect = True
            except Exception as e:
                logger.error("enroll_webcam_connect_error", student_id=student_id, error=str(e), exc_info=True)
                return {
                    "status": "error",
                    "error": f"Failed to connect to camera: {str(e)}"
                }
        elif not reader.is_connected:
            # Se reader fornecido mas não conectado, tentar conectar
            if not reader.connect():
                return {
                    "status": "error",
                    "error": "Camera reader not connected"
                }
        
        try:
            # Capturar múltiplos frames
            frames_captured = []
            start_time = time.time()
            frame_interval = capture_duration / num_frames
            
            logger.info("enroll_webcam_start", student_id=student_id, camera_id=camera_id, 
                       num_frames=num_frames)
            
            while len(frames_captured) < num_frames and (time.time() - start_time) < capture_duration:
                ret, frame = reader.read_frame()
                if ret and frame is not None:
                    # Detectar face
                    faces = self.detector.detect(frame)
                    if faces:
                        # Usar primeira face detectada
                        x, y, w, h = faces[0]
                        face_roi = frame[y:y+h, x:x+w]
                        
                        # Calcular qualidade
                        quality_label, quality_score = calculate_face_quality(face_roi, min_size=50)
                        
                        frames_captured.append({
                            "frame": face_roi,
                            "quality_score": quality_score,
                            "quality_label": quality_label,
                            "bbox": (x, y, w, h)
                        })
                
                time.sleep(frame_interval)
            
            # Desconectar apenas se criamos o reader
            if should_disconnect and reader:
                reader.disconnect()
            
            if not frames_captured:
                return {
                    "status": "error",
                    "error": "No faces detected in captured frames"
                }
            
            # Métricas de qualidade para validação automática do cadastro
            good_frames = [f for f in frames_captured if f["quality_label"] == "good"]
            fair_frames = [f for f in frames_captured if f["quality_label"] == "fair"]
            poor_frames = [f for f in frames_captured if f["quality_label"] == "poor"]

            # Escolher melhor frame (maior quality_score)
            best_frame = max(frames_captured, key=lambda f: f["quality_score"])
            avg_quality = float(np.mean([f["quality_score"] for f in frames_captured])) if frames_captured else 0.0

            quality_ok = float(best_frame["quality_score"]) >= float(min_quality_score) and len(good_frames) >= int(min_good_frames)
            quality_recommendation = (
                "OK para cadastrar"
                if quality_ok
                else "Qualidade insuficiente. Aproxime o rosto, melhore iluminação e mantenha o olhar de frente."
            )
            
            logger.info("enroll_webcam_best_frame", student_id=student_id, 
                       quality_score=best_frame["quality_score"],
                       quality_label=best_frame["quality_label"])
            
            # Preview/validação sem gravar no banco (para UX de cadastro guiado)
            if dry_run:
                return {
                    "status": "success" if quality_ok else "warning",
                    "dry_run": True,
                    "student_id": student_id,
                    "camera_id": camera_id,
                    "quality_ok": quality_ok,
                    "quality_recommendation": quality_recommendation,
                    "quality_score": float(best_frame["quality_score"]),
                    "quality_label": best_frame["quality_label"],
                    "quality_avg": avg_quality,
                    "frames_captured": len(frames_captured),
                    "good_frames": len(good_frames),
                    "fair_frames": len(fair_frames),
                    "poor_frames": len(poor_frames),
                    "min_quality_score_required": float(min_quality_score),
                    "min_good_frames_required": int(min_good_frames),
                    "message": "Pré-visualização concluída. Se quality_ok=true, pode cadastrar com segurança."
                }

            # Bloqueio automático: não cadastrar com qualidade ruim
            if not quality_ok:
                return {
                    "status": "error",
                    "error": "Enrollment bloqueado por baixa qualidade.",
                    "quality_ok": False,
                    "quality_recommendation": quality_recommendation,
                    "quality_score": float(best_frame["quality_score"]),
                    "quality_label": best_frame["quality_label"],
                    "quality_avg": avg_quality,
                    "frames_captured": len(frames_captured),
                    "good_frames": len(good_frames),
                    "fair_frames": len(fair_frames),
                    "poor_frames": len(poor_frames),
                    "min_quality_score_required": float(min_quality_score),
                    "min_good_frames_required": int(min_good_frames),
                }

            # Gerar embeddings para os melhores frames (top N por qualidade; mais = média mais estável)
            top_k = min(frames_used, len(frames_captured))
            sorted_frames = sorted(frames_captured, key=lambda f: f["quality_score"], reverse=True)[:top_k]
            
            embeddings_list = []
            for frame_data in sorted_frames:
                embedding = self.embedder.embed(frame_data["frame"])
                if embedding is not None:
                    embeddings_list.append(embedding)
            
            if not embeddings_list:
                return {
                    "status": "error",
                    "error": "Failed to generate embeddings from captured frames"
                }
            
            # Calcular média dos embeddings (melhor que usar apenas 1)
            embedding_mean = np.mean(embeddings_list, axis=0)
            # Normalizar L2
            norm = np.linalg.norm(embedding_mean)
            if norm > 0:
                embedding_mean = embedding_mean / norm
            
            # Salvar no banco
            session = get_session()
            settings = get_settings()
            student_repo = StudentRepository(session)
            existing_student = student_repo.get_student(student_id)

            # 1. Criar/atualizar student
            student_repo.create_student(
                student_id=student_id,
                school_id=settings.school_id,
                room_id=None,  # Pode ser configurado depois
                full_name=full_name,
                external_ref=None,  # Futuro mapeamento LXP
                is_active=True
            )

            # 2. Salvar embedding (multi-template: append ou substituir)
            embedding_repo = FaceEmbeddingRepository(session)
            if not append_template:
                removed = embedding_repo.delete_embeddings_for_student(
                    student_id, device_id=settings.device_id, school_id=settings.school_id
                )
                if removed:
                    logger.info("enroll_templates_replaced", student_id=student_id, removed=removed)
            embedding_repo.create_embedding(
                student_id=student_id,
                device_id=settings.device_id,
                school_id=settings.school_id,
                embedding_vector=embedding_mean.tolist(),
                room_id=None,
                embedding_dim=len(embedding_mean),
                model_name="facenet",
                model_version=self.embedder.get_model_version() if hasattr(self.embedder, 'get_model_version') else "facenet-pytorch-vggface2-512d-v1",
                quality_score=float(best_frame["quality_score"])
            )
            if append_template:
                embedding_repo.prune_oldest_templates(
                    student_id, max_templates, device_id=settings.device_id, school_id=settings.school_id
                )
            templates_count = embedding_repo.count_templates_for_student(
                student_id, device_id=settings.device_id, school_id=settings.school_id
            )
            
            logger.info("enroll_complete", 
                       student_id=student_id,
                       embeddings_generated=len(embeddings_list),
                       embedding_dim=len(embedding_mean),
                       quality_score=float(best_frame["quality_score"]))
            
            return {
                "status": "success",
                "student_id": student_id,
                "full_name": full_name,
                "student_updated": existing_student is not None,
                "append_template": append_template,
                "templates_count": templates_count,
                "quality_score": float(best_frame["quality_score"]),
                "quality_label": best_frame["quality_label"],
                "quality_avg": avg_quality,
                "frames_captured": len(frames_captured),
                "good_frames": len(good_frames),
                "fair_frames": len(fair_frames),
                "poor_frames": len(poor_frames),
                "frames_used": len(embeddings_list),
                "embedding_dim": len(embedding_mean),
                "model_version": self.embedder.get_model_version() if hasattr(self.embedder, 'get_model_version') else "facenet-pytorch-vggface2-512d-v1",
                "message": "Pessoa cadastrada. Certifique-se de que era a pessoa certa na câmera. Se errou, chame de novo com a pessoa certa para atualizar."
            }
            
        except Exception as e:
            logger.error("enroll_webcam_error", student_id=student_id, error=str(e), exc_info=True)
            if should_disconnect and reader:
                try:
                    reader.disconnect()
                except:
                    pass
            return {
                "status": "error",
                "error": str(e)
            }
