"""Cache em memória de nomes de alunos (evita SQLite a cada poll do viewer)."""

from __future__ import annotations

import threading
from typing import Dict, Optional

from app.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_names: Dict[str, str] = {}


def load_all(school_id: Optional[str] = None) -> int:
    """Carrega todos os alunos ativos no cache. Retorna quantidade."""
    from app.db.init_db import get_session
    from app.db.repo import StudentRepository

    session = get_session()
    try:
        repo = StudentRepository(session)
        students = repo.get_active_students(school_id=school_id)
        with _lock:
            for st in students:
                if st.student_id:
                    _names[st.student_id] = (st.full_name or st.student_id).strip() or st.student_id
        return len(students)
    finally:
        session.close()


def get_display_name(student_id: Optional[str]) -> Optional[str]:
    if not student_id:
        return None
    with _lock:
        if student_id in _names:
            return _names[student_id]
    from app.db.init_db import get_session
    from app.db.repo import StudentRepository

    session = get_session()
    try:
        st = StudentRepository(session).get_student(student_id)
        name = (st.full_name if st and st.full_name else student_id) or student_id
        with _lock:
            _names[student_id] = name
        return name
    finally:
        session.close()


def set_display_name(student_id: str, full_name: Optional[str]) -> None:
    with _lock:
        _names[student_id] = (full_name or student_id).strip() or student_id


def clear() -> None:
    with _lock:
        _names.clear()
