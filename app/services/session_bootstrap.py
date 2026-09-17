"""Bootstrap da ClassSession ativa — retoma antes do orchestrator async.

Não toca TRI/visão. Garante que LiveSessionStore não exponha UUID efêmero
antes do bind com a sessão persistida no SQLite.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import structlog

from app.config import get_settings
from app.db.init_db import close_session, get_session
from app.db.models import ClassSession
from app.db.repo import ClassSessionRepository
from app.services.live_session import get_live_session
from app.services.session_persistence import enqueue_class_session_upsert
from app.utils.ids import generate_event_id

logger = structlog.get_logger()


def ensure_active_class_session(*, create_if_missing: bool = True) -> Optional[str]:
    """Retoma ClassSession active do SQLite e alinha LiveSessionStore.

    - 0 active → cria (se create_if_missing) ou retorna None
    - 1 active → retoma
    - N active → registra ambiguidade e retoma a mais recente (já existente)
    """
    settings = get_settings()
    session = get_session()
    try:
        repo = ClassSessionRepository(session)
        actives = (
            session.query(ClassSession)
            .filter(ClassSession.status == "active")
            .order_by(ClassSession.started_at.desc())
            .all()
        )
        if len(actives) > 1:
            logger.error(
                "class_session_ambiguous_active",
                count=len(actives),
                session_ids=[a.session_id for a in actives],
            )

        active = actives[0] if actives else None
        orphan_hours = float(getattr(settings, "session_orphan_hours", 12) or 12)
        if active:
            age_h = (datetime.utcnow() - active.started_at).total_seconds() / 3600.0
            if age_h > orphan_hours:
                repo.end_session(active.session_id)
                logger.info(
                    "class_session_orphan_ended",
                    session_id=active.session_id,
                    age_h=age_h,
                )
                active = None

        if active:
            sid = active.session_id
            started = None
            try:
                started = active.started_at.timestamp()
            except Exception:
                started = None
            get_live_session().bind_session_id(sid, started_at=started)
            logger.info("class_session_resumed", session_id=sid)
            return sid

        if not create_if_missing:
            return None

        sid = generate_event_id()
        room0 = settings.cameras[0].room_id if settings.cameras else "DEV"
        title = "Sessão automática"
        repo.create_session(
            session_id=sid,
            school_id=settings.school_id,
            room_id=room0,
            device_id=settings.device_id,
            title=title,
        )
        get_live_session().bind_session_id(sid, started_at=time.time())
        enqueue_class_session_upsert(
            session_id=sid,
            status="active",
            started_at=time.time(),
            title=title,
        )
        logger.info("class_session_auto_started", session_id=sid)
        return sid
    except Exception as e:
        logger.warning("class_session_bootstrap_failed", error=str(e))
        return None
    finally:
        close_session(session)
