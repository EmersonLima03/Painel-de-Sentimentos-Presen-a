#!/usr/bin/env python3
"""
Script de backup do HUB local (SQLite).

Cria ZIP comum contendo manifest.json + data/dulino_edge.db.
Depois criptografa o ZIP inteiro com passphrase+salt.
Resultado: backup_YYYYMMDD_HHMMSS.zip.enc
"""

import os
import sys
import json
import zipfile
import sqlite3
from datetime import datetime
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_settings
from app.logging import get_logger
from app import __version__
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64

logger = get_logger(__name__)

SQLITE_HEADER = b"SQLite format 3\x00"


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Deriva chave AES de uma passphrase usando PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def _get_manifest(db_path: str) -> dict:
    """Monta manifest com metadados do backup."""
    settings = get_settings()
    students_count = 0
    embeddings_count = 0

    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM students")
            students_count = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM face_embeddings")
            embeddings_count = cur.fetchone()[0]
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    return {
        "backup_date": datetime.utcnow().isoformat(),
        "app_version": __version__,
        "model_version": "facenet-pytorch-vggface2-512d-v1",
        "device_id": settings.device_id,
        "school_id": settings.school_id,
        "students_count": students_count,
        "embeddings_count": embeddings_count,
    }


def backup_hub(output_path: str, passphrase: str) -> bool:
    """
    Cria backup criptografado do SQLite.

    1. Cria ZIP comum: manifest.json + dulino_edge.db
    2. Criptografa o ZIP inteiro com passphrase+salt
    3. Grava em output_path (ex: backup_20260219.zip.enc)
    """
    settings = get_settings()
    db_path = settings.sqlite_path

    if not os.path.exists(db_path):
        logger.error("database_not_found", path=db_path)
        return False

    # Validar header SQLite
    with open(db_path, "rb") as f:
        header = f.read(16)
    if header != SQLITE_HEADER:
        logger.error("invalid_sqlite_db", path=db_path)
        return False

    # 1. Criar ZIP em memória
    zip_buffer = BytesIO()
    manifest = _get_manifest(db_path)

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zipf.write(db_path, "dulino_edge.db")

    zip_bytes = zip_buffer.getvalue()

    # 2. Criptografar ZIP inteiro
    salt = os.urandom(16)
    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(zip_bytes)

    # 3. Gravar: salt (16) + encrypted
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(salt)
        f.write(encrypted)

    logger.info(
        "backup_complete",
        output_path=output_path,
        students=manifest["students_count"],
        embeddings=manifest["embeddings_count"],
    )
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Backup criptografado do HUB (SQLite)")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Arquivo de saída (default: backup_YYYYMMDD_HHMMSS.zip.enc)",
    )
    parser.add_argument(
        "--passphrase", "-p",
        help="Passphrase (ou BACKUP_PASSPHRASE do .env)",
    )

    args = parser.parse_args()

    passphrase = args.passphrase
    if not passphrase:
        settings = get_settings()
        passphrase = getattr(settings, "backup_passphrase", None)
        if not passphrase:
            logger.error("passphrase_required", message="Use --passphrase ou BACKUP_PASSPHRASE no .env")
            sys.exit(1)

    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"backup_{ts}.zip.enc"

    success = backup_hub(output_path, passphrase)

    if success:
        print(f"Backup criado: {output_path}")
        sys.exit(0)
    else:
        print("Falha ao criar backup")
        sys.exit(1)


if __name__ == "__main__":
    main()
