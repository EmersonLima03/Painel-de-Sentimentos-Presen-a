"""Gerador de embeddings faciais (pluggable)."""

import cv2
import numpy as np
from typing import List, Optional, Tuple
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_onnx_runtime_ok: Optional[bool] = None


def onnx_runtime_available() -> bool:
    """Testa import do onnxruntime (evita escolher ONNX quando a DLL falha no Windows)."""
    global _onnx_runtime_ok
    if _onnx_runtime_ok is not None:
        return _onnx_runtime_ok
    try:
        import onnxruntime as ort  # noqa: F401

        _ = ort.get_available_providers()
        _onnx_runtime_ok = True
    except Exception as e:
        logger.warning("onnx_runtime_unavailable", error=str(e))
        _onnx_runtime_ok = False
    return _onnx_runtime_ok


class FaceEmbedder:
    """Interface para gerador de embeddings."""
    
    def embed(
        self,
        face_roi: np.ndarray,
        *,
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[np.ndarray]:
        """
        Gera embedding para uma face.

        frame/bbox: usados pelo InsightFace para reutilizar cache do último detect().
        """
        raise NotImplementedError
    
    def get_embedding_dim(self) -> int:
        """Retorna dimensão do embedding."""
        raise NotImplementedError


class SimulationEmbedder(FaceEmbedder):
    """Embedder simulado para testes."""
    
    def __init__(self, dim: int = 512):
        self.dim = dim
        self.model_version = "emb-sim-v1"
        logger.info("embedder_initialized", type="simulation", dim=dim)
    
    def embed(
        self,
        face_roi: np.ndarray,
        *,
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[np.ndarray]:
        """Gera embedding simulado."""
        # Embedding aleatório normalizado
        embedding = np.random.randn(self.dim).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)
        return embedding
    
    def get_embedding_dim(self) -> int:
        return self.dim


class DeterministicEmbedder(FaceEmbedder):
    """Embedder determinístico baseado em hash da face (fallback para Windows)."""
    
    def __init__(self, dim: int = 512):
        self.dim = dim
        self.model_version = "emb-det-v1"  # deterministic
        import hashlib
        self.hashlib = hashlib
        logger.info("embedder_initialized", type="deterministic_hash", dim=dim)
    
    def embed(
        self,
        face_roi: np.ndarray,
        *,
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[np.ndarray]:
        """
        Gera embedding determinístico baseado em hash da face.
        
        Usa hash SHA256 do array de pixels normalizado para gerar vetor determinístico.
        Mesma face sempre gera mesmo embedding (útil para validar pipeline).
        """
        try:
            import hashlib
            
            # Normalizar face_roi para hash consistente
            if len(face_roi.shape) == 3:
                gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            else:
                gray = face_roi
            
            # Redimensionar para tamanho fixo para hash consistente
            resized = cv2.resize(gray, (64, 64))
            
            # Calcular hash
            face_bytes = resized.tobytes()
            hash_obj = hashlib.sha256(face_bytes)
            hash_hex = hash_obj.hexdigest()
            
            # Converter hash para vetor determinístico
            # Usar primeiros N bytes do hash para gerar vetor de dimensão fixa
            embedding = np.zeros(self.dim, dtype=np.float32)
            
            # Preencher embedding com valores derivados do hash
            for i in range(self.dim):
                # Usar diferentes partes do hash para cada dimensão
                hash_idx = (i * 2) % len(hash_hex)
                val = int(hash_hex[hash_idx:hash_idx+2], 16) / 255.0  # Normalizar 0-1
                embedding[i] = val
            
            # Normalizar vetor
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            
            return embedding.astype(np.float32)
            
        except Exception as e:
            logger.warning("deterministic_embedding_failed", error=str(e))
            return None
    
    def get_embedding_dim(self) -> int:
        return self.dim
    
    def get_model_version(self) -> str:
        """Retorna versão do modelo usado."""
        return self.model_version


class FaceNetEmbedder(FaceEmbedder):
    """Embedder usando FaceNet (facenet-pytorch) - 512D."""

    def __init__(self):
        try:
            from facenet_pytorch import MTCNN, InceptionResnetV1

            self.mtcnn = MTCNN(image_size=160, margin=0, min_face_size=20,
                              thresholds=[0.6, 0.7, 0.7], factor=0.709, post_process=False,
                              device='cpu')
            self.resnet = InceptionResnetV1(pretrained='vggface2').eval()
            self.dim = 512
            self.model_version = "facenet-pytorch-vggface2-512d-v1"
            
            logger.info("embedder_initialized", type="facenet", dim=self.dim, model="vggface2")
        except Exception as e:
            logger.error("facenet_init_failed", error=str(e))
            raise RuntimeError(f"Failed to initialize FaceNet: {e}")
    
    def embed(
        self,
        face_roi: np.ndarray,
        *,
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[np.ndarray]:
        """
        Gera embedding usando FaceNet.
        Input para InceptionResnetV1 deve ser 4D: [N, 3, 160, 160], float32, range 0..1.
        frame/bbox ignorados (compatibilidade com pipeline; InsightFace usa o cache).
        """
        try:
            import torch
            from PIL import Image
            import torchvision.transforms as transforms

            # Garantir numpy array
            if not isinstance(face_roi, np.ndarray):
                face_roi = np.asarray(face_roi)
            if face_roi.dtype != np.uint8:
                face_roi = np.clip(face_roi, 0, 255).astype(np.uint8)

            # [H,W,3] (OpenCV BGR) -> RGB para PIL
            if len(face_roi.shape) == 3:
                if face_roi.shape[2] == 3:
                    face_rgb = cv2.cvtColor(face_roi, cv2.COLOR_BGR2RGB)
                else:
                    face_rgb = face_roi
            else:
                face_rgb = np.stack([face_roi] * 3, axis=-1)

            pil_image = Image.fromarray(face_rgb)
            transform = transforms.ToTensor()

            try:
                face_tensor = self.mtcnn(pil_image)
                if face_tensor is None:
                    face_tensor = self.mtcnn.extract(pil_image, save_path=None)
                if face_tensor is None:
                    pil_resized = pil_image.resize((160, 160))
                    face_tensor = transform(pil_resized)
            except Exception:
                pil_resized = pil_image.resize((160, 160))
                face_tensor = transform(pil_resized)

            # Garantir 4D: [N, 3, 160, 160]. MTCNN pode retornar [3,160,160].
            if face_tensor.dim() == 3:
                face_tensor = face_tensor.unsqueeze(0)
            # Se por algum motivo vier [H,W,C], converter para [C,H,W]
            if face_tensor.dim() == 4 and face_tensor.shape[1] != 3 and face_tensor.shape[-1] == 3:
                face_tensor = face_tensor.permute(0, 3, 1, 2)
            face_tensor = face_tensor.to(torch.float32)
            if face_tensor.max() > 1.0:
                face_tensor = face_tensor / 255.0

            with torch.no_grad():
                embedding = self.resnet(face_tensor)

            embedding_np = embedding[0].cpu().numpy() if embedding.dim() > 1 else embedding.cpu().numpy()
            embedding_np = np.asarray(embedding_np, dtype=np.float32).flatten()
            # L2 normalize com EPS para evitar div por zero
            eps = 1e-12
            norm = np.linalg.norm(embedding_np) + eps
            embedding_np = embedding_np / norm
            return embedding_np
        except Exception as e:
            logger.warning(
                "facenet_embedding_failed",
                error=str(e),
                backend="facenet",
                input_shape=getattr(face_roi, "shape", None),
                input_dtype=getattr(face_roi, "dtype", None),
                input_min=float(face_roi.min()) if hasattr(face_roi, "min") else None,
                input_max=float(face_roi.max()) if hasattr(face_roi, "max") else None,
            )
            return None
    
    def get_embedding_dim(self) -> int:
        return self.dim
    
    def get_model_version(self) -> str:
        """Retorna versão do modelo usado."""
        return self.model_version


class InsightFaceEmbedder(FaceEmbedder):
    """Embedding ArcFace via sessão compartilhada (cache do detect no mesmo frame)."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.dim = 512
        self.model_version = "emb-insightface-buffalo_l-v1"
        logger.info("embedder_initialized", type="insightface", dim=self.dim)

    def embed(
        self,
        face_roi: np.ndarray,
        *,
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[np.ndarray]:
        cached = self.runtime.get_cached_embedding(frame, bbox)
        if cached is not None:
            return cached
        try:
            faces = self.runtime.app.get(face_roi)
            if len(faces) > 0:
                embedding = np.asarray(faces[0].normed_embedding, dtype=np.float32)
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm
                return embedding
            return None
        except Exception as e:
            logger.warning("embedding_failed", error=str(e))
            return None
    
    def get_embedding_dim(self) -> int:
        return self.dim
    
    def get_model_version(self) -> str:
        """Retorna versão do modelo usado."""
        return self.model_version


def create_embedder() -> FaceEmbedder:
    """Factory para criar embedder baseado em configuração."""
    from app.vision.detector import get_insightface_pair

    settings = get_settings()

    if settings.simulation:
        logger.info("using_simulation_embedder")
        return SimulationEmbedder()

    embed_backend = (getattr(settings, "vision_embedder_backend", None) or "").strip().lower()
    det_backend = (getattr(settings, "vision_detector_backend", None) or "full_range").strip().lower()

    if not settings.real and not settings.simulation and settings.cameras:
        # Câmeras configuradas sem SIMULATION: modo real implícito
        pass

    use_insightface = embed_backend == "insightface" or det_backend == "insightface"
    pair = get_insightface_pair()
    if use_insightface and pair is not None:
        logger.info("using_insightface_embedder", paired=True)
        return pair[1]

    if use_insightface:
        try:
            from app.vision.detector import _build_insightface_pair
            import app.vision.detector as det_mod

            det_mod._insightface_pair = _build_insightface_pair()
            logger.info("using_insightface_embedder", paired=True)
            return det_mod._insightface_pair[1]
        except Exception as e:
            logger.warning("insightface_embedder_failed", error=str(e))

    if embed_backend in ("onnx", "arcface", "onnxruntime"):
        if onnx_runtime_available():
            try:
                from app.vision.onnx_embedder import OnnxFaceEmbedder

                logger.info("using_onnx_embedder")
                return OnnxFaceEmbedder()
            except Exception as e:
                logger.warning("onnx_embedder_failed", error=str(e), fallback="facenet")
        else:
            logger.warning("onnx_runtime_missing", fallback="facenet")

    prefer_facenet = embed_backend == "facenet" or (
        embed_backend not in ("onnx", "arcface", "onnxruntime", "insightface")
        and not use_insightface
        and settings.real
    )

    if settings.real or (not settings.simulation and settings.cameras):
        if prefer_facenet:
            try:
                return FaceNetEmbedder()
            except Exception as e:
                logger.warning("facenet_failed", error=str(e), fallback="insightface")
        elif embed_backend == "insightface":
            pass  # tratado acima
        elif embed_backend in ("onnx", "arcface", "onnxruntime"):
            try:
                logger.warning("onnx_unavailable_using_facenet")
                return FaceNetEmbedder()
            except Exception as e:
                logger.warning("facenet_fallback_failed", error=str(e))
        try:
            from app.vision.detector import _build_insightface_pair
            import app.vision.detector as det_mod

            if det_mod._insightface_pair is None:
                det_mod._insightface_pair = _build_insightface_pair()
            return det_mod._insightface_pair[1]
        except Exception as e2:
            logger.warning("insightface_failed", error=str(e2), fallback="deterministic")
            return DeterministicEmbedder()

    if not settings.simulation:
        try:
            return FaceNetEmbedder()
        except Exception as e:
            logger.info("using_deterministic_embedder", reason=f"FaceNet unavailable: {e}")
            return DeterministicEmbedder()

    return SimulationEmbedder()
