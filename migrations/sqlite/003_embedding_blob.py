#!/usr/bin/env python3
"""
Migration 003: face_embeddings embedding_vector (JSON) -> embedding_blob (BLOB)

Estratégia: create new table + copy + rename.
Idempotente: se já possui embedding_blob e não possui embedding_vector, não refaz.
Sempre cria backup do DB antes de migrar (data/dulino_edge.db.bak.TIMESTAMP).
"""

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Adicionar projeto ao path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import get_settings
from app.utils.embedding_io import serialize_embedding
import numpy as np


SQLITE_HEADER = b"SQLite format 3\0"


def get_columns(conn: sqlite3.Connection, table: str) -> list:
    """Retorna lista de nomes de colunas da tabela."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def run_migration(db_path: str) -> bool:
    """
    Executa migração. Retorna True se ok ou se já estava migrado.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='face_embeddings'"
        )
        if cur.fetchone() is None:
            conn.close()
            return True  # Tabela não existe, nada a migrar

        columns = get_columns(conn, "face_embeddings")
        has_blob = "embedding_blob" in columns
        has_vector = "embedding_vector" in columns

        # Idempotente: já migrado
        if has_blob and not has_vector:
            return True

        # Schema novo: apenas embedding_blob
        if not has_vector:
            conn.close()
            return True

        # Backup do DB antes de migrar (não destrutivo)
        backup_path = f"{db_path}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            shutil.copy2(db_path, backup_path)
        except Exception as e:
            conn.close()
            raise RuntimeError(f"Backup do DB falhou ({backup_path}): {e}") from e

        # Migrar: embedding_vector -> embedding_blob
        conn.execute("BEGIN")

        # Criar tabela nova com schema correto
        conn.execute("""
            CREATE TABLE face_embeddings_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                school_id TEXT NOT NULL,
                room_id TEXT,
                embedding_dim INTEGER NOT NULL DEFAULT 512,
                embedding_blob BLOB NOT NULL,
                model_name TEXT,
                model_version TEXT,
                quality_score REAL,
                created_at TEXT,
                FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
            )
        """)

        # Copiar dados: JSON -> np.float32 -> bytes
        cur = conn.execute(
            "SELECT id, student_id, device_id, school_id, room_id, "
            "embedding_vector, embedding_dim, model_name, model_version, "
            "quality_score, created_at FROM face_embeddings"
        )
        for row in cur:
            try:
                vec = json.loads(row["embedding_vector"])
                arr = np.array(vec, dtype=np.float32)
                dim = int(row["embedding_dim"] or 512)
                if len(arr) != dim:
                    if len(arr) < dim:
                        arr = np.pad(arr, (0, dim - len(arr)), constant_values=0)
                    else:
                        arr = arr[:dim]
                blob = serialize_embedding(arr)
            except Exception:
                continue  # Pular linhas corrompidas

            conn.execute("""
                INSERT INTO face_embeddings_new
                (id, student_id, device_id, school_id, room_id, embedding_dim,
                 embedding_blob, model_name, model_version, quality_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["id"],
                row["student_id"],
                row["device_id"],
                row["school_id"],
                row["room_id"],
                dim,
                blob,
                row["model_name"],
                row["model_version"],
                row["quality_score"],
                row["created_at"],
            ))

        # Dropar tabela antiga e renomear
        conn.execute("DROP TABLE face_embeddings")
        conn.execute("ALTER TABLE face_embeddings_new RENAME TO face_embeddings")

        # Recriar índices
        conn.execute("CREATE INDEX IF NOT EXISTS idx_face_embeddings_student_id ON face_embeddings(student_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_face_embeddings_device_id ON face_embeddings(device_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_face_embeddings_school_id ON face_embeddings(school_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_face_embeddings_school_room ON face_embeddings(school_id, room_id)")

        conn.execute("COMMIT")
        return True

    except Exception as e:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def main():
    settings = get_settings()
    db_path = settings.sqlite_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    if not Path(db_path).exists():
        print("Database not found, migration skipped (tables will be created on first run)")
        return 0

    try:
        run_migration(db_path)
        print("Migration 003: embedding_blob applied successfully")
        return 0
    except Exception as e:
        print(f"Migration 003 failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
