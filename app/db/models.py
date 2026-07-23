"""Modelos SQLAlchemy para SQLite."""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Boolean, LargeBinary, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class DeviceState(Base):
    """Estado do dispositivo."""
    __tablename__ = "device_state"
    
    device_id = Column(String, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version = Column(String, default="0.1.0")


class Event(Base):
    """Eventos pendentes/enviados."""
    __tablename__ = "events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String, default="pending", index=True)  # pending, sent, failed
    retries = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)


class AttendanceCache(Base):
    """Cache de presença para dedup (dia ou sessão)."""
    __tablename__ = "attendance_cache"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String, nullable=False, index=True)
    date_key = Column(String, nullable=False, index=True)  # YYYY-MM-DD ou session:<id>
    session_id = Column(String, nullable=True, index=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    room_id = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    device_id = Column(String, nullable=False)
    sightings = Column(Integer, default=1)  # presença periódica na sessão
    
    # Índice composto para busca rápida
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class Student(Base):
    """Alunos cadastrados."""
    __tablename__ = "students"
    
    student_id = Column(String, primary_key=True)
    school_id = Column(String, nullable=False, index=True)
    room_id = Column(String, nullable=True, index=True)
    full_name = Column(String, nullable=True)
    external_ref = Column(String, nullable=True, index=True)  # Futuro mapeamento LXP
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FaceEmbedding(Base):
    """Embeddings faciais (pode ter múltiplos por aluno)."""
    __tablename__ = "face_embeddings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String, nullable=False, index=True)  # FK para students
    device_id = Column(String, nullable=False, index=True)
    school_id = Column(String, nullable=False, index=True)
    room_id = Column(String, nullable=True, index=True)
    embedding_dim = Column(Integer, default=512)
    embedding_blob = Column(LargeBinary, nullable=False)
    model_name = Column(String, default="facenet")
    model_version = Column(String, nullable=True)
    quality_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ClassSession(Base):
    """Sessão de aula (presença periódica e métricas)."""
    __tablename__ = "class_sessions"

    session_id = Column(String, primary_key=True)
    school_id = Column(String, nullable=False, index=True)
    room_id = Column(String, nullable=False, index=True)
    device_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, default="active", index=True)  # active | ended
    metadata_json = Column(Text, nullable=True)


class BehavioralEvent(Base):
    """Eventos comportamentais observáveis (revisáveis)."""
    __tablename__ = "behavioral_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    school_id = Column(String, nullable=False, index=True)
    room_id = Column(String, nullable=False, index=True)
    device_id = Column(String, nullable=False)
    camera_id = Column(String, nullable=True)
    session_id = Column(String, nullable=True, index=True)
    student_id = Column(String, nullable=True, index=True)
    anonymous_track_id = Column(String, nullable=True, index=True)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    duration_seconds = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    observation_quality = Column(String, nullable=True)
    source_model = Column(String, nullable=True)
    model_version = Column(String, nullable=True)
    status = Column(String, default="pending_review", index=True)  # pending_review|confirmed|rejected|inconclusive
    reviewed_by = Column(String, nullable=True)
    review_result = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class StudentConsent(Base):
    """Consentimento / exclusão de análise biométrica (LGPD mínima)."""
    __tablename__ = "student_consents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String, nullable=False, index=True)
    school_id = Column(String, nullable=False, index=True)
    consent_given = Column(Boolean, default=False)
    guardian_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    granted_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PrivacyAudit(Base):
    """Trilha simples de auditoria de privacidade."""
    __tablename__ = "privacy_audits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=True)
    detail_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
