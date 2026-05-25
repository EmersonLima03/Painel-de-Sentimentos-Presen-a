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
    """Cache de presença para dedup."""
    __tablename__ = "attendance_cache"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String, nullable=False, index=True)
    date_key = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    room_id = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    device_id = Column(String, nullable=False)
    
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
