"""Repositório para operações de banco de dados."""

from datetime import datetime
from typing import List, Optional, Union

import numpy as np

from app.utils.embedding_io import serialize_embedding
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.db.models import Event, AttendanceCache, DeviceState, Student, FaceEmbedding
from app.utils.time import get_date_key
from app.logging import get_logger

logger = get_logger(__name__)


class EventRepository:
    """Repositório para eventos."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create_event(self, event_id: str, event_type: str, payload_json: str) -> Event:
        """Cria novo evento."""
        event = Event(
            event_id=event_id,
            event_type=event_type,
            payload_json=payload_json,
            status="pending"
        )
        self.session.add(event)
        self.session.commit()
        return event
    
    def get_pending_events(self, limit: int = 100) -> List[Event]:
        """Retorna eventos pendentes."""
        return self.session.query(Event).filter(
            Event.status == "pending"
        ).order_by(Event.created_at).limit(limit).all()
    
    def mark_sent(self, event_id: str) -> None:
        """Marca evento como enviado."""
        event = self.session.query(Event).filter(Event.event_id == event_id).first()
        if event:
            event.status = "sent"
            event.sent_at = datetime.utcnow()
            event.retries = 0
            self.session.commit()
    
    def mark_failed(self, event_id: str, error: str) -> None:
        """Marca evento como falho."""
        event = self.session.query(Event).filter(Event.event_id == event_id).first()
        if event:
            event.status = "failed"
            event.last_error = error
            event.retries += 1
            self.session.commit()
    
    def get_stats(self) -> dict:
        """Retorna estatísticas de eventos."""
        total = self.session.query(Event).count()
        pending = self.session.query(Event).filter(Event.status == "pending").count()
        sent = self.session.query(Event).filter(Event.status == "sent").count()
        failed = self.session.query(Event).filter(Event.status == "failed").count()
        
        return {
            "total": total,
            "pending": pending,
            "sent": sent,
            "failed": failed
        }


class AttendanceRepository:
    """Repositório para cache de presença."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def has_attendance_today(self, student_id: str, room_id: str, date_key: Optional[str] = None) -> bool:
        """Verifica se já há presença hoje."""
        if date_key is None:
            date_key = get_date_key()
        
        count = self.session.query(AttendanceCache).filter(
            and_(
                AttendanceCache.student_id == student_id,
                AttendanceCache.date_key == date_key,
                AttendanceCache.room_id == room_id
            )
        ).count()
        
        return count > 0
    
    def create_attendance(self, student_id: str, room_id: str, confidence: float, device_id: str, 
                         date_key: Optional[str] = None) -> AttendanceCache:
        """Cria registro de presença."""
        if date_key is None:
            date_key = get_date_key()
        
        attendance = AttendanceCache(
            student_id=student_id,
            date_key=date_key,
            room_id=room_id,
            confidence=confidence,
            device_id=device_id
        )
        self.session.add(attendance)
        self.session.commit()
        return attendance
    
    def update_last_seen(self, student_id: str, room_id: str, date_key: Optional[str] = None) -> None:
        """Atualiza último visto."""
        if date_key is None:
            date_key = get_date_key()
        
        attendance = self.session.query(AttendanceCache).filter(
            and_(
                AttendanceCache.student_id == student_id,
                AttendanceCache.date_key == date_key,
                AttendanceCache.room_id == room_id
            )
        ).first()
        
        if attendance:
            attendance.last_seen_at = datetime.utcnow()
            self.session.commit()


class StudentRepository:
    """Repositório para alunos."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create_student(
        self,
        student_id: str,
        school_id: str,
        room_id: Optional[str] = None,
        full_name: Optional[str] = None,
        external_ref: Optional[str] = None,
        is_active: bool = True
    ) -> Student:
        """Cria ou atualiza aluno."""
        student = self.session.query(Student).filter(
            Student.student_id == student_id
        ).first()
        
        if student:
            student.school_id = school_id
            student.room_id = room_id
            student.full_name = full_name
            student.external_ref = external_ref
            student.is_active = is_active
            student.updated_at = datetime.utcnow()
        else:
            student = Student(
                student_id=student_id,
                school_id=school_id,
                room_id=room_id,
                full_name=full_name,
                external_ref=external_ref,
                is_active=is_active
            )
            self.session.add(student)
        
        self.session.commit()
        return student
    
    def get_student(self, student_id: str) -> Optional[Student]:
        """Retorna aluno por ID."""
        return self.session.query(Student).filter(
            Student.student_id == student_id
        ).first()
    
    def get_active_students(self, school_id: Optional[str] = None, room_id: Optional[str] = None) -> List[Student]:
        """Retorna alunos ativos, opcionalmente filtrados."""
        query = self.session.query(Student).filter(Student.is_active == True)
        
        if school_id:
            query = query.filter(Student.school_id == school_id)
        if room_id:
            query = query.filter(Student.room_id == room_id)
        
        return query.all()
    
    def deactivate_student(self, student_id: str) -> bool:
        """Desativa aluno."""
        student = self.get_student(student_id)
        if student:
            student.is_active = False
            student.updated_at = datetime.utcnow()
            self.session.commit()
            return True
        return False


class FaceEmbeddingRepository:
    """Repositório para embeddings faciais."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create_embedding(
        self,
        student_id: str,
        device_id: str,
        school_id: str,
        embedding_vector: Union[List[float], np.ndarray],
        room_id: Optional[str] = None,
        embedding_dim: int = 512,
        model_name: str = "facenet",
        model_version: Optional[str] = None,
        quality_score: Optional[float] = None
    ) -> FaceEmbedding:
        """Cria novo embedding. Armazena em embedding_blob como BLOB float32."""
        if isinstance(embedding_vector, list):
            arr = np.array(embedding_vector, dtype=np.float32)
        else:
            arr = np.asarray(embedding_vector, dtype=np.float32)
        embedding_blob = serialize_embedding(arr)

        embedding = FaceEmbedding(
            student_id=student_id,
            device_id=device_id,
            school_id=school_id,
            room_id=room_id,
            embedding_dim=embedding_dim,
            embedding_blob=embedding_blob,
            model_name=model_name,
            model_version=model_version,
            quality_score=quality_score
        )
        self.session.add(embedding)
        self.session.commit()
        return embedding
    
    def get_embeddings_for_student(self, student_id: str, active_only: bool = True) -> List[FaceEmbedding]:
        """Retorna embeddings de um aluno."""
        query = self.session.query(FaceEmbedding).filter(
            FaceEmbedding.student_id == student_id
        )
        
        if active_only:
            # Verificar se student está ativo
            student = self.session.query(Student).filter(
                Student.student_id == student_id,
                Student.is_active == True
            ).first()
            if not student:
                return []
        
        return query.order_by(FaceEmbedding.created_at.desc()).all()
    
    def get_all_active_embeddings(
        self,
        school_id: Optional[str] = None,
        device_id: Optional[str] = None
    ) -> List[FaceEmbedding]:
        """Retorna todos os embeddings ativos (de alunos ativos)."""
        # Join com students para filtrar apenas alunos ativos
        query = self.session.query(FaceEmbedding).join(
            Student, FaceEmbedding.student_id == Student.student_id
        ).filter(Student.is_active == True)
        
        if school_id:
            query = query.filter(FaceEmbedding.school_id == school_id)
        if device_id:
            query = query.filter(FaceEmbedding.device_id == device_id)
        
        return query.all()
    
    def get_latest_embedding(self, student_id: str) -> Optional[FaceEmbedding]:
        """Retorna o embedding mais recente de um aluno."""
        return self.session.query(FaceEmbedding).filter(
            FaceEmbedding.student_id == student_id
        ).order_by(FaceEmbedding.created_at.desc()).first()

    def count_templates_for_student(self, student_id: str, device_id: Optional[str] = None, school_id: Optional[str] = None) -> int:
        """Conta quantos templates (embeddings) o aluno possui."""
        q = self.session.query(FaceEmbedding).filter(FaceEmbedding.student_id == student_id)
        if device_id:
            q = q.filter(FaceEmbedding.device_id == device_id)
        if school_id:
            q = q.filter(FaceEmbedding.school_id == school_id)
        return q.count()

    def delete_embeddings_for_student(self, student_id: str, device_id: Optional[str] = None, school_id: Optional[str] = None) -> int:
        """Remove todos os embeddings de um aluno (para substituir template principal). Retorna quantidade removida."""
        q = self.session.query(FaceEmbedding).filter(FaceEmbedding.student_id == student_id)
        if device_id:
            q = q.filter(FaceEmbedding.device_id == device_id)
        if school_id:
            q = q.filter(FaceEmbedding.school_id == school_id)
        count = q.count()
        q.delete(synchronize_session=False)
        self.session.commit()
        return count

    def prune_oldest_templates(self, student_id: str, keep_count: int, device_id: Optional[str] = None, school_id: Optional[str] = None) -> int:
        """Mantém apenas os keep_count mais recentes; remove os mais antigos. Retorna quantidade removida."""
        q = (
            self.session.query(FaceEmbedding)
            .filter(FaceEmbedding.student_id == student_id)
            .order_by(FaceEmbedding.created_at.desc())
        )
        if device_id:
            q = q.filter(FaceEmbedding.device_id == device_id)
        if school_id:
            q = q.filter(FaceEmbedding.school_id == school_id)
        all_rows = q.all()
        if len(all_rows) <= keep_count:
            return 0
        to_delete = all_rows[keep_count:]
        for row in to_delete:
            self.session.delete(row)
        self.session.commit()
        return len(to_delete)

    def get_templates_per_student(self, school_id: Optional[str] = None, device_id: Optional[str] = None) -> dict:
        """Retorna {student_id: quantidade de templates} para telemetria (apenas alunos ativos)."""
        from sqlalchemy import func
        q = (
            self.session.query(FaceEmbedding.student_id, func.count(FaceEmbedding.id).label("n"))
            .join(Student, FaceEmbedding.student_id == Student.student_id)
            .filter(Student.is_active == True)
            .group_by(FaceEmbedding.student_id)
        )
        if school_id:
            q = q.filter(FaceEmbedding.school_id == school_id)
        if device_id:
            q = q.filter(FaceEmbedding.device_id == device_id)
        return {row.student_id: row.n for row in q.all()}
