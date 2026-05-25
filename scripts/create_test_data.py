"""Script para criar dados de teste no banco."""

import sys
import json
from pathlib import Path

# Adicionar app ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.init_db import init_database, get_session
from app.db.repo import FaceProfileRepository, EventRepository
from app.utils.ids import generate_event_id

def create_test_profiles():
    """Cria perfis faciais de teste."""
    session = get_session()
    repo = FaceProfileRepository(session)
    
    # Criar 3 perfis de teste com embeddings simulados
    test_students = [
        "student-001",
        "student-002", 
        "student-003"
    ]
    
    # Usar random do Python ao invés de numpy (evita problema de DLL)
    import random
    
    for student_id in test_students:
        # Embedding simulado (512 dimensões) usando random do Python
        embedding = [random.gauss(0, 1) for _ in range(512)]
        # Normalizar
        norm = sum(x*x for x in embedding) ** 0.5
        embedding = [x/norm for x in embedding]
        
        repo.create_profile(
            student_id=student_id,
            embedding_vector=embedding,  # Já é lista Python
            model_version="emb-v1",
            template_version="tpl-v1"
        )
        print(f"✓ Perfil criado: {student_id}")
    
    print(f"\n✓ {len(test_students)} perfis de teste criados!")

def create_test_events():
    """Cria alguns eventos de teste."""
    session = get_session()
    repo = EventRepository(session)
    
    import time
    
    # Evento de presença
    attendance_event = {
        "event_id": generate_event_id(),
        "event_type": "attendance_checkin",
        "student_id": "student-001",
        "school_id": "1",
        "room_id": "A01",
        "device_id": "edge-001",
        "timestamp": int(time.time()),
        "confidence": 0.85,
        "model_version": "emb-v1",
        "template_version": "tpl-v1",
        "face_quality": "good"
    }
    
    repo.create_event(
        event_id=attendance_event["event_id"],
        event_type="attendance_checkin",
        payload_json=json.dumps(attendance_event)
    )
    print("✓ Evento de presença criado")
    
    # Evento de engajamento
    engagement_event = {
        "event_id": generate_event_id(),
        "event_type": "engagement_window",
        "school_id": "1",
        "room_id": "A01",
        "device_id": "edge-001",
        "ts_start": int(time.time()) - 10,
        "ts_end": int(time.time()),
        "faces_detected_avg": 15.0,
        "engagement_index_avg": 0.72,
        "states_distribution": {
            "attentive": 0.60,
            "neutral": 0.30,
            "distracted": 0.10
        },
        "model_version": "eng-v0"
    }
    
    repo.create_event(
        event_id=engagement_event["event_id"],
        event_type="engagement_window",
        payload_json=json.dumps(engagement_event)
    )
    print("✓ Evento de engajamento criado")
    
    print("\n✓ Eventos de teste criados!")

if __name__ == "__main__":
    print("=== Criando dados de teste ===\n")
    
    # Inicializar banco
    init_database()
    
    # Criar perfis
    print("1. Criando perfis faciais de teste...")
    create_test_profiles()
    
    # Criar eventos
    print("\n2. Criando eventos de teste...")
    create_test_events()
    
    print("\n=== Concluído! ===")
    print("\nAgora você pode:")
    print("  - Ver perfis: http://localhost:8000/stats")
    print("  - Ver eventos no banco SQLite")
    print("  - Testar detecção de presença (modo simulação)")
