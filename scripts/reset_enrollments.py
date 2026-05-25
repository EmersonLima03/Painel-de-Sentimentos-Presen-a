#!/usr/bin/env python3
"""
Remove todos os alunos, embeddings e cache de presença para recadastrar do zero.
Faz backup do banco antes. Depois de rodar, reinicie o servidor para o matcher recarregar.

Uso: python scripts/reset_enrollments.py
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Adicionar raiz do projeto ao path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.config import get_settings
from app.db.init_db import get_session, init_database
from app.db.models import Student, FaceEmbedding, AttendanceCache


def main():
    settings = get_settings()
    db_path = Path(settings.sqlite_path)
    if not db_path.is_absolute():
        db_path = project_root / db_path
    if not db_path.exists():
        print("Banco não encontrado:", db_path)
        return 1

    # Backup
    backup_name = f"dulino_edge.db.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_path = db_path.parent / backup_name
    shutil.copy2(db_path, backup_path)
    print("Backup criado:", backup_path)

    init_database()
    session = get_session()

    try:
        n_emb = session.query(FaceEmbedding).delete()
        n_att = session.query(AttendanceCache).delete()
        n_stu = session.query(Student).delete()
        session.commit()
        print("Removidos: face_embeddings=%d, attendance_cache=%d, students=%d" % (n_emb, n_att, n_stu))
        print("Pronto. Reinicie o servidor e cadastre de novo (POST /enroll/webcam).")
    except Exception as e:
        session.rollback()
        print("Erro:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
