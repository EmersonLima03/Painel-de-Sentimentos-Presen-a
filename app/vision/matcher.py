"""Matcher de embeddings (nearest neighbor)."""

import numpy as np
from typing import List, Tuple, Optional
from app.logging import get_logger
from app.utils.embedding_io import deserialize_embedding

logger = get_logger(__name__)


def competitor_margin_from_topk(
    topk: List[Tuple[str, float]],
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Margem entre o 1º lugar e o melhor candidato de OUTRO aluno.
    Ignora 2º/3º templates do mesmo student_id (evita ? com score 0.95).
    """
    if not topk:
        return None, None, None
    top1_id, top1_sim = topk[0]
    best_other_sim: Optional[float] = None
    best_other_id: Optional[str] = None
    for sid, sim in topk[1:]:
        if sid == top1_id:
            continue
        if best_other_sim is None or sim > best_other_sim:
            best_other_sim = sim
            best_other_id = sid
    if best_other_sim is None:
        return None, None, None
    return top1_sim - best_other_sim, best_other_sim, best_other_id


# Tentar importar FAISS (opcional)
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError as e:
    FAISS_AVAILABLE = False
    logger.warning("FAISS disabled: faiss not installed", reason=str(e), fallback="linear")


class FaceMatcher:
    """Matcher de faces usando cosine similarity."""
    
    def __init__(self, embeddings: List[Tuple[str, np.ndarray]]):
        """
        Inicializa matcher com lista de (student_id, embedding).
        """
        self.embeddings = embeddings
        if len(embeddings) > 0:
            self.embedding_matrix = np.array([emb for _, emb in embeddings])
        else:
            self.embedding_matrix = np.array([])
    
    def find_match_topk(
        self,
        query_embedding: np.ndarray,
        k: int = 3,
    ) -> List[Tuple[str, float]]:
        """Retorna os top-k matches (student_id, similarity) ordenados por similaridade desc."""
        if self.embedding_matrix.size == 0:
            return []
        similarities = np.dot(self.embedding_matrix, query_embedding)
        if len(similarities) == 0:
            return []
        k_actual = min(k, len(similarities))
        top_indices = np.argsort(similarities)[-k_actual:][::-1]
        return [(self.embeddings[int(i)][0], float(similarities[i])) for i in top_indices]

    def find_match(
        self,
        query_embedding: np.ndarray,
        threshold: float = 0.75,
        margin: float = 0.0,
        k: int = 3,
    ) -> Optional[Tuple[str, float]]:
        """
        Encontra match usando top-k: top1 >= threshold e (se margin > 0) top1 - top2 >= margin.
        """
        topk = self.find_match_topk(query_embedding, k=k)
        if not topk:
            return None
        top1_id, top1_sim = topk[0]
        if top1_sim < threshold:
            return None
        if margin > 0:
            margin_val, _, _ = competitor_margin_from_topk(topk)
            if margin_val is not None and margin_val < margin:
                return None
        return (top1_id, top1_sim)

    def find_match_topk_extended(
        self,
        query_embedding: np.ndarray,
        k: int = 15,
    ) -> List[Tuple[str, float]]:
        """Top-k amplo para achar competidor de outro aluno (multi-template)."""
        if self.embedding_matrix.size == 0:
            return []
        similarities = np.dot(self.embedding_matrix, query_embedding)
        if len(similarities) == 0:
            return []
        k_actual = min(k, len(similarities))
        top_indices = np.argsort(similarities)[-k_actual:][::-1]
        return [(self.embeddings[int(i)][0], float(similarities[i])) for i in top_indices]
    
    def update_embeddings(self, embeddings: List[Tuple[str, np.ndarray]]) -> None:
        """Atualiza lista de embeddings."""
        self.embeddings = embeddings
        if len(embeddings) > 0:
            self.embedding_matrix = np.array([emb for _, emb in embeddings])
        else:
            self.embedding_matrix = np.array([])


def load_embeddings_from_face_embeddings(face_embeddings: List) -> List[Tuple[str, np.ndarray]]:
    """Carrega TODOS os templates da tabela (múltiplos por student_id para multi-template)."""
    embeddings = []
    for fe in sorted(face_embeddings, key=lambda x: (x.student_id, x.created_at or "")):
        try:
            dim = getattr(fe, "embedding_dim", None) or 512
            raw = fe.embedding_blob
            embedding_array = deserialize_embedding(raw, dim=dim)
            embeddings.append((fe.student_id, embedding_array))
        except Exception as e:
            logger.warning(
                "failed_to_load_face_embedding",
                student_id=fe.student_id,
                embedding_id=fe.id,
                error=str(e),
            )
    return embeddings


class FAISSMatcher:
    """Matcher usando FAISS para busca eficiente."""
    
    def __init__(self, embeddings: List[Tuple[str, np.ndarray]], dim: int = 512):
        """
        Inicializa matcher FAISS.
        
        Args:
            embeddings: Lista de (student_id, embedding_array)
            dim: Dimensão dos embeddings
        """
        if not FAISS_AVAILABLE:
            raise RuntimeError("FAISS not available. Install with: pip install faiss-cpu")
        
        self.embeddings = embeddings
        self.dim = dim
        self.student_ids = []
        
        if len(embeddings) == 0:
            # Criar índice vazio
            self.index = faiss.IndexFlatIP(dim)  # Inner Product (equivalente a cosine com L2 normalized)
            logger.info("faiss_matcher_initialized", count=0, dim=dim)
            return
        
        # Extrair student_ids e embeddings
        self.student_ids = [sid for sid, _ in embeddings]
        embedding_matrix = np.array([emb for _, emb in embeddings], dtype=np.float32)
        
        # Garantir que embeddings estão normalizados L2
        faiss.normalize_L2(embedding_matrix)
        
        # Criar índice FAISS (IndexFlatIP = Inner Product, equivalente a cosine similarity)
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(embedding_matrix)
        
        logger.info("faiss_matcher_initialized", 
                   count=len(embeddings), 
                   dim=dim,
                   index_type="IndexFlatIP")
    
    def find_match_topk(
        self,
        query_embedding: np.ndarray,
        k: int = 3,
    ) -> List[Tuple[str, float]]:
        """Retorna os top-k matches (student_id, similarity) ordenados por similaridade desc."""
        if self.index.ntotal == 0:
            return []
        query_norm = np.linalg.norm(query_embedding)
        if query_norm > 0:
            query_embedding = query_embedding / query_norm
        query_matrix = query_embedding.reshape(1, -1).astype(np.float32)
        k_search = min(max(k, 1), self.index.ntotal)
        similarities, indices = self.index.search(query_matrix, k_search)
        if len(similarities[0]) == 0:
            return []
        return [
            (self.student_ids[int(indices[0][i])], float(similarities[0][i]))
            for i in range(len(similarities[0]))
        ]

    def find_match(
        self,
        query_embedding: np.ndarray,
        threshold: float = 0.75,
        k: int = 3,
        margin: float = 0.0,
    ) -> Optional[Tuple[str, float]]:
        """
        Encontra match usando top-k: top1 >= threshold e (se margin > 0) top1 - top2 >= margin.
        """
        topk = self.find_match_topk(query_embedding, k=k)
        if not topk:
            return None
        top1_id, top1_sim = topk[0]
        if top1_sim < threshold:
            return None
        if margin > 0:
            margin_val, _, _ = competitor_margin_from_topk(topk)
            if margin_val is not None and margin_val < margin:
                return None
        return (top1_id, top1_sim)

    def find_match_topk_extended(
        self,
        query_embedding: np.ndarray,
        k: int = 15,
    ) -> List[Tuple[str, float]]:
        """Top-k amplo (até k) para margem entre alunos distintos."""
        return self.find_match_topk(query_embedding, k=min(k, max(self.index.ntotal, 1)))
    
    def update_embeddings(self, embeddings: List[Tuple[str, np.ndarray]]) -> None:
        """Atualiza embeddings e reconstrói índice FAISS."""
        self.embeddings = embeddings
        self.student_ids = [sid for sid, _ in embeddings]
        
        if len(embeddings) == 0:
            self.index.reset()
            return
        
        embedding_matrix = np.array([emb for _, emb in embeddings], dtype=np.float32)
        faiss.normalize_L2(embedding_matrix)
        
        # Recriar índice
        self.index.reset()
        self.index.add(embedding_matrix)
        
        logger.info("faiss_matcher_rebuilt", count=len(embeddings))
