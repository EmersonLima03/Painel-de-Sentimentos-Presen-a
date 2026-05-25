"""
Utilitários para serialização/deserialização de embeddings faciais.
"""

import numpy as np
from typing import Union


def serialize_embedding(arr: np.ndarray, dtype=np.float32) -> bytes:
    """
    Serializa embedding numpy para bytes (BLOB).

    Args:
        arr: Array numpy (ex: 512 float32)
        dtype: Tipo numérico de saída

    Returns:
        Bytes do array (ex: 512 * 4 = 2048 bytes para float32)
    """
    return arr.astype(dtype).tobytes()


def deserialize_embedding(raw: bytes, dim: int = 512, dtype=np.float32) -> np.ndarray:
    """
    Deserializa bytes para array numpy.

    Args:
        raw: Bytes do embedding
        dim: Dimensão esperada
        dtype: Tipo numérico

    Returns:
        Array numpy float32 normalizado

    Raises:
        ValueError: Se len(raw) != dim * 4 (bytes por float32)
    """
    expected_bytes = dim * 4  # 4 bytes por float32
    if len(raw) != expected_bytes:
        raise ValueError(
            f"embedding blob size mismatch: expected {expected_bytes} bytes, got {len(raw)}"
        )
    arr = np.frombuffer(raw, dtype=dtype).copy()
    # L2 normalize (EPS para evitar div por zero)
    eps = 1e-12
    norm = np.linalg.norm(arr) + eps
    arr = arr / norm
    return arr
