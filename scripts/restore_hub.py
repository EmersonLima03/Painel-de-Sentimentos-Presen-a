#!/usr/bin/env python3
"""
Script de restore do HUB local (SQLite).

Descriptografa backup .zip.enc, valida que é ZIP,
extrai dulino_edge.db, valida header SQLite,
faz backup do DB atual e substitui.
"""

import os
import sys
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_settings
from app.logging import get_logger
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64

logger = get_logger(__name__)

SQLITE_HEADER = b"SQLite format 3\x00"
ZIP_MAGIC = b"PK"  # ZIP files start with PK


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


def restore_hub(backup_path: str, passphrase: str, dry_run: bool = False) -> bool:
    """
    Restaura backup no SQLite.

    1. Lê arquivo: salt (16 bytes) + encrypted
    2. Descriptografa
    3. Valida que é ZIP (magic bytes PK)
    4. Extrai dulino_edge.db
    5. Valida header SQLite (bytes[:16] == b"SQLite format 3\\0")
    6. Backup do DB atual (se existir)
    7. Substitui data/dulino_edge.db
    """
    if not os.path.exists(backup_path):
        logger.error("backup_not_found", path=backup_path)
        return False

    settings = get_settings()
    db_path = settings.sqlite_path
    db_dir = Path(db_path).parent

    try:
        with open(backup_path, "rb") as f:
            data = f.read()

        if len(data) < 17:
            logger.error("backup_too_small")
            return False

        salt = data[:16]
        encrypted = data[16:]

        key = _derive_key(passphrase, salt)
        fernet = Fernet(key)
        zip_bytes = fernet.decrypt(encrypted)

        # Validar que é ZIP
        if not zip_bytes.startswith(ZIP_MAGIC):
            logger.error("invalid_zip_after_decrypt", magic=zip_bytes[:4])
            return False

        # Extrair ZIP
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zipf:
            names = zipf.namelist()
            if "dulino_edge.db" not in names:
                logger.error("dulino_edge_db_not_in_zip", files=names)
                return False
            db_content = zipf.read("dulino_edge.db")

        # Validar header SQLite
        if len(db_content) < 16:
            logger.error("extracted_db_too_small")
            return False
        if db_content[:16] != SQLITE_HEADER:
            logger.error("invalid_sqlite_header", got=db_content[:16])
            return False

        if dry_run:
            logger.info(
                "dry_run_ok",
                backup_path=backup_path,
                db_size=len(db_content),
            )
            return True

        # Backup do DB atual com timestamp antes de sobrescrever
        if os.path.exists(db_path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_current = f"{db_path}.bak.{ts}"
            shutil.copy2(db_path, backup_current)
            logger.info("current_db_backed_up", path=backup_current)

        # Restaurar para arquivo temporário e depois swap (evita escrita parcial)
        db_dir.mkdir(parents=True, exist_ok=True)
        temp_path = f"{db_path}.tmp"
        with open(temp_path, "wb") as f:
            f.write(db_content)
        os.replace(temp_path, db_path)

        logger.info("restore_complete", db_path=db_path)
        return True

    except Exception as e:
        logger.error("restore_failed", error=str(e), exc_info=True)
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Restore do HUB a partir de backup .zip.enc")
    parser.add_argument("backup_path", help="Arquivo de backup (.zip.enc)")
    parser.add_argument(
        "--passphrase", "-p",
        help="Passphrase (ou BACKUP_PASSPHRASE do .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas validar backup sem restaurar",
    )

    args = parser.parse_args()

    passphrase = args.passphrase
    if not passphrase:
        settings = get_settings()
        passphrase = getattr(settings, "backup_passphrase", None)
        if not passphrase:
            logger.error("passphrase_required", message="Use --passphrase ou BACKUP_PASSPHRASE no .env")
            sys.exit(1)

    success = restore_hub(args.backup_path, passphrase, dry_run=args.dry_run)

    if success:
        if args.dry_run:
            print("Backup valido (dry-run)")
        else:
            print("Restore completo")
        sys.exit(0)
    else:
        print("Falha ao restaurar backup")
        sys.exit(1)


if __name__ == "__main__":
    main()
