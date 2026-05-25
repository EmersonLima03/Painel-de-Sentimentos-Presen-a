"""
Backup e criptografia de embeddings e fila de eventos (DAT).
- Export: embeddings + eventos (fila) para ficheiro; opcional AES-256.
- Import: restauração a partir de ficheiro (merge embeddings, opcional eventos).
"""

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from app.logging import get_logger

logger = get_logger(__name__)

MAGIC = b"PRESECA_BACKUP_V1"
SALT_LEN = 16
NONCE_LEN = 12
KEY_LEN = 32  # AES-256
PBKDF2_ITERATIONS = 100_000


@dataclass
class BackupResult:
    """Resultado de export/import."""
    path: str
    encrypted: bool
    embeddings_count: int
    events_count: int
    error: Optional[str] = None


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Deriva chave AES-256 a partir de passphrase e salt (PBKDF2-HMAC-SHA256)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LEN,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _encrypt(payload: bytes, passphrase: str) -> bytes:
    salt = os.urandom(SALT_LEN)
    key = _derive_key(passphrase, salt)
    aes = AESGCM(key)
    nonce = os.urandom(NONCE_LEN)
    ct = aes.encrypt(nonce, payload, None)
    return MAGIC + salt + nonce + ct


def _decrypt(data: bytes, passphrase: str) -> bytes:
    if not data.startswith(MAGIC):
        raise ValueError("Invalid backup file: missing magic")
    off = len(MAGIC)
    salt = data[off : off + SALT_LEN]
    off += SALT_LEN
    nonce = data[off : off + NONCE_LEN]
    off += NONCE_LEN
    ciphertext = data[off:]
    key = _derive_key(passphrase, salt)
    aes = AESGCM(key)
    return aes.decrypt(nonce, ciphertext, None)


def _embedding_to_dict(row: Any) -> Dict[str, Any]:
    """Converte linha FaceEmbedding para dict serializável (embedding_blob em b64)."""
    return {
        "student_id": row.student_id,
        "device_id": row.device_id,
        "school_id": row.school_id,
        "room_id": getattr(row, "room_id", None),
        "embedding_dim": getattr(row, "embedding_dim", 512),
        "embedding_blob_b64": base64.b64encode(row.embedding_blob).decode("ascii"),
        "model_name": getattr(row, "model_name", "facenet"),
        "model_version": getattr(row, "model_version", None),
        "quality_score": getattr(row, "quality_score", None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _event_to_dict(row: Any) -> Dict[str, Any]:
    """Converte linha Event para dict serializável."""
    return {
        "event_id": row.event_id,
        "event_type": row.event_type,
        "payload_json": row.payload_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "status": row.status,
        "retries": getattr(row, "retries", 0),
        "last_error": getattr(row, "last_error", None),
        "sent_at": row.sent_at.isoformat() if getattr(row, "sent_at", None) else None,
    }


def export_backup(
    embeddings: List[Any],
    events: List[Any],
    out_path: str,
    passphrase: Optional[str] = None,
) -> BackupResult:
    """
    Exporta embeddings e eventos para um ficheiro.
    Se passphrase for definida, o conteúdo é criptografado com AES-256-GCM.
    """
    payload = {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "embeddings": [_embedding_to_dict(e) for e in embeddings],
        "events": [_event_to_dict(e) for e in events],
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    encrypted = bool(passphrase)
    try:
        if passphrase:
            raw = _encrypt(raw, passphrase)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(raw)
        logger.info(
            "backup_exported",
            path=out_path,
            encrypted=encrypted,
            embeddings=len(embeddings),
            events=len(events),
        )
        return BackupResult(
            path=out_path,
            encrypted=encrypted,
            embeddings_count=len(embeddings),
            events_count=len(events),
        )
    except Exception as e:
        logger.exception("backup_export_failed", path=out_path, error=str(e))
        return BackupResult(
            path=out_path,
            encrypted=encrypted,
            embeddings_count=0,
            events_count=0,
            error=str(e),
        )


def import_backup(
    file_path: str,
    passphrase: Optional[str],
    session_factory,
    merge_embeddings: bool = True,
    merge_events: bool = False,
) -> BackupResult:
    """
    Importa backup: lê ficheiro (descriptografa se necessário) e insere no DB.
    - merge_embeddings: insere embeddings (por student_id + created_at evita duplicar).
    - merge_events: se True, re-insere eventos com status pending (fila).
    """
    path = Path(file_path)
    if not path.exists():
        return BackupResult(
            path=file_path,
            encrypted=False,
            embeddings_count=0,
            events_count=0,
            error="File not found",
        )
    raw = path.read_bytes()
    if raw.startswith(MAGIC):
        if not passphrase:
            return BackupResult(
                path=file_path,
                encrypted=True,
                embeddings_count=0,
                events_count=0,
                error="Backup is encrypted; passphrase required",
            )
        try:
            raw = _decrypt(raw, passphrase)
        except Exception as e:
            return BackupResult(
                path=file_path,
                encrypted=True,
                embeddings_count=0,
                events_count=0,
                error=f"Decryption failed: {e}",
            )
    else:
        passphrase = None  # plain backup

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return BackupResult(
            path=file_path,
            encrypted=bool(passphrase),
            embeddings_count=0,
            events_count=0,
            error=f"Invalid JSON: {e}",
        )

    embeddings_data = payload.get("embeddings", [])
    events_data = payload.get("events", [])

    from app.db.repo import FaceEmbeddingRepository, EventRepository
    from app.utils.embedding_io import deserialize_embedding

    session = session_factory()
    added_emb = 0
    added_ev = 0
    try:
        emb_repo = FaceEmbeddingRepository(session)
        ev_repo = EventRepository(session)

        if merge_embeddings and embeddings_data:
            for item in embeddings_data:
                try:
                    blob = base64.b64decode(item["embedding_blob_b64"])
                    dim = item.get("embedding_dim", 512)
                    arr = deserialize_embedding(blob, dim=dim)
                    emb_repo.create_embedding(
                        student_id=item["student_id"],
                        device_id=item["device_id"],
                        school_id=item["school_id"],
                        embedding_vector=arr,
                        room_id=item.get("room_id"),
                        embedding_dim=dim,
                        model_name=item.get("model_name", "facenet"),
                        model_version=item.get("model_version"),
                        quality_score=item.get("quality_score"),
                    )
                    added_emb += 1
                except Exception as e:
                    logger.warning("backup_import_embedding_skip", student_id=item.get("student_id"), error=str(e))

        if merge_events and events_data:
            for item in events_data:
                if item.get("status") != "pending":
                    continue
                try:
                    ev_repo.create_event(
                        event_id=item["event_id"],
                        event_type=item["event_type"],
                        payload_json=item["payload_json"],
                    )
                    added_ev += 1
                except Exception as e:
                    logger.warning("backup_import_event_skip", event_id=item.get("event_id"), error=str(e))
    except Exception as e:
        logger.exception("backup_import_failed", path=file_path, error=str(e))
        session.rollback()
        return BackupResult(
            path=file_path,
            encrypted=bool(passphrase),
            embeddings_count=0,
            events_count=0,
            error=str(e),
        )
    finally:
        session.close()

    logger.info(
        "backup_imported",
        path=file_path,
        embeddings_added=added_emb,
        events_added=added_ev,
    )
    return BackupResult(
        path=file_path,
        encrypted=bool(passphrase),
        embeddings_count=added_emb,
        events_count=added_ev,
    )