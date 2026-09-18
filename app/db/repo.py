"""Repositório para operações de banco de dados."""

from datetime import datetime
from typing import List, Optional, Union

import numpy as np

from app.utils.embedding_io import serialize_embedding
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.db.models import (
    Event,
    AttendanceCache,
    DeviceState,
    Student,
    FaceEmbedding,
    ClassSession,
    BehavioralEvent,
    StudentConsent,
    PrivacyAudit,
)
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
    
    def get_pending_events(
        self,
        limit: int = 100,
        *,
        event_types: Optional[Union[List[str], tuple]] = None,
        prioritize_types: Optional[Union[List[str], tuple]] = None,
    ) -> List[Event]:
        """Retorna eventos pendentes.

        IMPORTANTE: quando ``event_types`` é informado, o filtro é aplicado
        *antes* do LIMIT (evita FIFO + whitelist vazia).
        """
        from sqlalchemy import case

        q = self.session.query(Event).filter(Event.status == "pending")
        if event_types:
            types = [t for t in event_types if t]
            if types:
                q = q.filter(Event.event_type.in_(types))
        if prioritize_types:
            pri = [t for t in prioritize_types if t]
            if pri:
                whens = [(Event.event_type == t, i) for i, t in enumerate(pri)]
                q = q.order_by(case(*whens, else_=len(pri)), Event.created_at.asc())
            else:
                q = q.order_by(Event.created_at.asc())
        else:
            q = q.order_by(Event.created_at.asc())
        return q.limit(limit).all()

    def get_outbox_lane_stats(self) -> dict:
        """Contagens pending por lane (product / lxp / telemetry / ignored)."""
        from sqlalchemy import func
        from app.sync.outbox_contract import (
            CLOUD_MVP_SYNCABLE_SET,
            LXP_SYNCABLE_SET,
            TELEMETRY_LOCAL_TYPES,
            classify_outbox_lane,
        )

        rows = (
            self.session.query(Event.event_type, func.count(Event.id))
            .filter(Event.status == "pending")
            .group_by(Event.event_type)
            .all()
        )
        by_type = {t: int(n) for t, n in rows}
        product_pending = sum(n for t, n in by_type.items() if t in CLOUD_MVP_SYNCABLE_SET)
        lxp_pending = sum(n for t, n in by_type.items() if t in LXP_SYNCABLE_SET)
        telemetry_pending = sum(n for t, n in by_type.items() if t in TELEMETRY_LOCAL_TYPES)
        ignored_pending = sum(
            n
            for t, n in by_type.items()
            if classify_outbox_lane(t) == "ignored"
        )
        return {
            "product_pending": product_pending,
            "lxp_pending": lxp_pending,
            "telemetry_pending": telemetry_pending,
            "ignored_pending": ignored_pending,
            "pending_by_type": by_type,
        }
    
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
                         date_key: Optional[str] = None, session_id: Optional[str] = None) -> AttendanceCache:
        """Cria registro de presença."""
        if date_key is None:
            date_key = get_date_key()
        
        attendance = AttendanceCache(
            student_id=student_id,
            date_key=date_key,
            session_id=session_id,
            room_id=room_id,
            confidence=confidence,
            device_id=device_id,
            sightings=1,
        )
        self.session.add(attendance)
        self.session.commit()
        return attendance
    
    def update_last_seen(self, student_id: str, room_id: str, date_key: Optional[str] = None) -> None:
        """Atualiza último visto e incrementa sightings (presença periódica)."""
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
            try:
                attendance.sightings = int(getattr(attendance, "sightings", 1) or 1) + 1
            except Exception:
                pass
            self.session.commit()

    def list_for_session(self, session_id: str) -> List[AttendanceCache]:
        return (
            self.session.query(AttendanceCache)
            .filter(AttendanceCache.session_id == session_id)
            .all()
        )


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


class ClassSessionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_session(
        self,
        session_id: str,
        school_id: str,
        room_id: str,
        device_id: str,
        title: Optional[str] = None,
    ) -> ClassSession:
        from app.db.models import ClassSession

        row = ClassSession(
            session_id=session_id,
            school_id=school_id,
            room_id=room_id,
            device_id=device_id,
            title=title,
            status="active",
        )
        self.session.add(row)
        self.session.commit()
        return row

    def get_active(self, room_id: Optional[str] = None) -> Optional[ClassSession]:
        from app.db.models import ClassSession

        q = self.session.query(ClassSession).filter(ClassSession.status == "active")
        if room_id:
            q = q.filter(ClassSession.room_id == room_id)
        return q.order_by(ClassSession.started_at.desc()).first()

    def end_session(self, session_id: str) -> bool:
        from app.db.models import ClassSession

        row = self.session.query(ClassSession).filter(ClassSession.session_id == session_id).first()
        if not row:
            return False
        row.status = "ended"
        row.ended_at = datetime.utcnow()
        self.session.commit()
        return True

    def list_recent(self, limit: int = 20) -> List[ClassSession]:
        from app.db.models import ClassSession

        return (
            self.session.query(ClassSession)
            .order_by(ClassSession.started_at.desc())
            .limit(limit)
            .all()
        )


class BehavioralEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> BehavioralEvent:
        from app.db.models import BehavioralEvent

        row = BehavioralEvent(**kwargs)
        self.session.add(row)
        self.session.commit()
        return row

    def list_events(
        self,
        *,
        session_id: Optional[str] = None,
        room_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[BehavioralEvent]:
        from app.db.models import BehavioralEvent

        q = self.session.query(BehavioralEvent)
        if session_id:
            q = q.filter(BehavioralEvent.session_id == session_id)
        if room_id:
            q = q.filter(BehavioralEvent.room_id == room_id)
        if status:
            q = q.filter(BehavioralEvent.status == status)
        return q.order_by(BehavioralEvent.created_at.desc()).limit(limit).all()

    def review(self, event_id: str, result: str, reviewed_by: str) -> Optional[BehavioralEvent]:
        from app.db.models import BehavioralEvent

        row = self.session.query(BehavioralEvent).filter(BehavioralEvent.event_id == event_id).first()
        if not row:
            return None
        row.status = result
        row.review_result = result
        row.reviewed_by = reviewed_by
        row.reviewed_at = datetime.utcnow()
        self.session.commit()
        return row


class ConsentRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(
        self,
        student_id: str,
        school_id: str,
        consent_given: bool,
        guardian_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> StudentConsent:
        from app.db.models import StudentConsent

        row = (
            self.session.query(StudentConsent)
            .filter(StudentConsent.student_id == student_id, StudentConsent.school_id == school_id)
            .order_by(StudentConsent.id.desc())
            .first()
        )
        now = datetime.utcnow()
        if row is None:
            row = StudentConsent(
                student_id=student_id,
                school_id=school_id,
                consent_given=consent_given,
                guardian_name=guardian_name,
                notes=notes,
                granted_at=now if consent_given else None,
                revoked_at=None if consent_given else now,
            )
            self.session.add(row)
        else:
            row.consent_given = consent_given
            row.guardian_name = guardian_name
            row.notes = notes
            if consent_given:
                row.granted_at = now
                row.revoked_at = None
            else:
                row.revoked_at = now
        self.session.commit()
        return row

    def has_consent(self, student_id: str, school_id: str) -> bool:
        from app.db.models import StudentConsent

        row = (
            self.session.query(StudentConsent)
            .filter(StudentConsent.student_id == student_id, StudentConsent.school_id == school_id)
            .order_by(StudentConsent.id.desc())
            .first()
        )
        return bool(row and row.consent_given)

    def students_without_consent(self, school_id: str) -> List[str]:
        """IDs ativos sem consentimento (para exclusão da análise biométrica)."""
        from app.db.models import StudentConsent

        active = self.session.query(Student).filter(
            Student.school_id == school_id, Student.is_active == True
        ).all()
        denied = []
        for s in active:
            if not self.has_consent(s.student_id, school_id):
                # Em modo piloto: se NÃO houver nenhum registro de consent, trata como permitido
                # apenas quando require_consent=False (config). Aqui retorna só revogados explícitos.
                row = (
                    self.session.query(StudentConsent)
                    .filter(
                        StudentConsent.student_id == s.student_id,
                        StudentConsent.school_id == school_id,
                    )
                    .first()
                )
                if row is not None and not row.consent_given:
                    denied.append(s.student_id)
        return denied


class PrivacyAuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def log(self, action: str, actor: Optional[str] = None, detail: Optional[dict] = None) -> PrivacyAudit:
        from app.db.models import PrivacyAudit
        import json

        row = PrivacyAudit(
            action=action,
            actor=actor,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
        self.session.add(row)
        self.session.commit()
        return row
