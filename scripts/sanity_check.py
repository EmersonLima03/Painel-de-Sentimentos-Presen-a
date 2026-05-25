#!/usr/bin/env python3
"""
Sanity check: valida FaceNet/embedding, serialize/deserialize, SQLite (temp DB) e FAISS/fallback.
Não suja o DB real: usa data/_sanity_temp.db para o teste de insert.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from app.utils.embedding_io import serialize_embedding, deserialize_embedding


def test_mediapipe_import():
    """0) Verificar que MediaPipe Tasks (face_detector) ou mp.solutions está disponível."""
    print("0. Testando import MediaPipe (Tasks ou solutions)...")
    try:
        import mediapipe as mp
        # Preferir Tasks API (google-ai-edge/mediapipe)
        if hasattr(mp, "tasks"):
            try:
                from mediapipe.tasks.python import vision
                if hasattr(vision, "FaceDetector"):
                    print("   [OK] MediaPipe Tasks FaceDetector disponivel")
                    return True
            except Exception:
                pass
        # Fallback: solutions API (PyPI mediapipe antigo)
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
            print("   [OK] MediaPipe mp.solutions.face_detection disponivel")
            return True
        print("   [FALHOU] MediaPipe instalado mas Tasks e solutions indisponiveis")
        print("   [DICA] Reinstale: pip install mediapipe")
        return False
    except ImportError as e:
        print(f"   [FALHOU] mediapipe nao instalado: {e}")
        return False
    except Exception as e:
        print(f"   [FALHOU] {e}")
        return False


def test_embedding_generation():
    """1) Imports torch/facenet e geração de 1 embedding com crop dummy 160x160."""
    print("1. Testando geração de embedding (crop dummy 160x160)...")
    try:
        from app.vision.embedder import create_embedder
    except Exception as e:
        print(f"   [FALHOU] import embedder: {e}")
        return False

    embedder = create_embedder()
    # Crop dummy 160x160 (formato FaceNet) sem depender de imagem
    dummy_crop = np.random.randint(0, 255, (160, 160, 3), dtype=np.uint8)
    embedding = embedder.embed(dummy_crop)

    if embedding is None:
        print("   [FALHOU] embedding e None")
        return False
    if len(embedding) == 0:
        print("   [FALHOU] embedding vazio")
        return False
    if embedding.dtype != np.float32:
        print(f"   [FALHOU] dtype esperado float32, obtido {embedding.dtype}")
        return False
    print(f"   [OK] Embedding: dim={len(embedding)}, dtype={embedding.dtype}, tipo={type(embedder).__name__}")
    return True


def test_serialize_deserialize():
    """2) Serialize/deserialize e checar shape/dtype."""
    print("2. Testando serialize/deserialize...")
    arr = np.random.randn(512).astype(np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    raw = serialize_embedding(arr)
    if len(raw) != 512 * 4:
        print(f"   [FALHOU] tamanho bytes esperado 2048, obtido {len(raw)}")
        return False
    back = deserialize_embedding(raw, dim=512)
    if back.shape != (512,):
        print(f"   [FALHOU] shape esperado (512,), obtido {back.shape}")
        return False
    if back.dtype != np.float32:
        print(f"   [FALHOU] dtype esperado float32, obtido {back.dtype}")
        return False
    print("   [OK] shape/dtype apos deserialize corretos")
    return True


def test_database_insert_temp_db():
    """3) Inserir e ler 1 student + 1 embedding em DB temporário (não suja o real)."""
    print("3. Testando insert/read em DB temporário...")
    temp_db = Path("data/_sanity_temp.db")
    temp_db.parent.mkdir(parents=True, exist_ok=True)
    old_sqlite = os.environ.get("SQLITE_PATH")
    os.environ["SQLITE_PATH"] = str(temp_db.resolve())

    try:
        from app.config import reload_settings, get_settings
        from app.db.init_db import init_database, get_session
        from app.db.repo import StudentRepository, FaceEmbeddingRepository

        reload_settings()
        init_database()
        session = get_session()
        settings = get_settings()

        student_repo = StudentRepository(session)
        embedding_repo = FaceEmbeddingRepository(session)
        test_student_id = "sanity-test-001"
        student_repo.create_student(
            student_id=test_student_id,
            school_id=settings.school_id,
            full_name="Sanity Test",
            is_active=True,
        )
        fake_embedding = np.random.randn(512).astype(np.float32)
        fake_embedding = fake_embedding / (np.linalg.norm(fake_embedding) + 1e-12)
        embedding_repo.create_embedding(
            student_id=test_student_id,
            device_id=settings.device_id,
            school_id=settings.school_id,
            embedding_vector=fake_embedding.tolist(),
            embedding_dim=512,
            model_name="facenet",
            model_version="test-v1",
            quality_score=0.9,
        )
        retrieved = embedding_repo.get_latest_embedding(test_student_id)
        if not retrieved:
            print("   [FALHOU] nao encontrou embedding apos insert")
            return False
        print(f"   [OK] student + embedding em temp DB: {test_student_id}")
        return True
    except Exception as e:
        print(f"   [FALHOU] %s" % e)
        return False
    finally:
        if old_sqlite is not None:
            os.environ["SQLITE_PATH"] = old_sqlite
        else:
            os.environ.pop("SQLITE_PATH", None)
        reload_settings()
        # Temp DB mantido para passo 4; removido no main() ao final


def test_faiss_or_fallback(temp_db_path: str):
    """4) Construir índice FAISS e match top-1; se indisponível, testar fallback linear. Usa temp DB."""
    print("4. Testando FAISS matching (ou fallback linear)...")
    from app.vision.matcher import (
        FAISSMatcher,
        FaceMatcher,
        load_embeddings_from_face_embeddings,
    )
    from app.config import reload_settings, get_settings
    from app.db.init_db import init_database, get_session
    from app.db.repo import FaceEmbeddingRepository

    old_sqlite = os.environ.get("SQLITE_PATH")
    os.environ["SQLITE_PATH"] = temp_db_path
    try:
        reload_settings()
        init_database()
        session = get_session()
        settings = get_settings()
        embedding_repo = FaceEmbeddingRepository(session)
        face_embeddings = embedding_repo.get_all_active_embeddings(school_id=settings.school_id)
        embeddings = load_embeddings_from_face_embeddings(face_embeddings)
    finally:
        if old_sqlite is not None:
            os.environ["SQLITE_PATH"] = old_sqlite
        else:
            os.environ.pop("SQLITE_PATH", None)
        reload_settings()

    try:
        import faiss
        faiss_available = True
    except ImportError as e:
        faiss_available = False
        print("   [AVISO] FAISS disabled: %s (usando fallback linear)" % e)

    if len(embeddings) == 0:
        print("   [FALHOU] nenhum embedding no temp DB (passo 3 deve ter inserido)")
        return False

    dim = len(embeddings[0][1])
    query = np.random.randn(dim).astype(np.float32)
    query = query / (np.linalg.norm(query) + 1e-12)

    if faiss_available:
        try:
            matcher = FAISSMatcher(embeddings, dim=dim)
            match = matcher.find_match(query, threshold=0.5)
            print("   [OK] FAISS matcher: %d embeddings, dim=%d" % (len(embeddings), dim))
        except Exception as e:
            print("   [AVISO] FAISS disabled: %s (usando fallback linear)" % e)
            matcher = FaceMatcher(embeddings)
            match = matcher.find_match(query, threshold=0.5)
    else:
        matcher = FaceMatcher(embeddings)
        match = matcher.find_match(query, threshold=0.5)
        print("   [OK] Fallback linear: %d embeddings" % len(embeddings))

    if match:
        print("   [OK] Match: student_id=%s, similarity=%.3f" % (match[0], match[1]))
    else:
        print("   [OK] Nenhum match (esperado com query aleatorio)")
    return True


def main():
    print("=" * 60)
    print("SANITY CHECK - Preseca")
    print("=" * 60)
    temp_db = Path("data/_sanity_temp.db")
    results = []
    results.append(("MediaPipe import (mp.solutions)", test_mediapipe_import()))
    results.append(("Embedding (160x160 dummy)", test_embedding_generation()))
    results.append(("Serialize/Deserialize", test_serialize_deserialize()))
    results.append(("DB temporario (insert/read)", test_database_insert_temp_db()))
    results.append(("FAISS ou fallback", test_faiss_or_fallback(str(temp_db.resolve()))))
    try:
        temp_db.unlink(missing_ok=True)
    except Exception:
        pass
    print()
    print("=" * 60)
    print("RESULTADOS:")
    for name, ok in results:
        print("  %s: %s" % (name, "PASSOU" if ok else "FALHOU"))
    all_ok = all(r[1] for r in results)
    print()
    if all_ok:
        print("Todos os testes passaram.")
        sys.exit(0)
    print("Alguns testes falharam.")
    sys.exit(1)


if __name__ == "__main__":
    main()
