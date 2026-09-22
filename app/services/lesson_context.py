"""Fase 6 — contexto operacional da aula no Edge (ao redor do TRI).

Fonte de verdade da execução: SQLite ClassSession.metadata_json + cache diário.
Não toca app/vision.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.db.init_db import close_session, get_session
from app.db.models import ClassSession
from app.db.repo import ClassSessionRepository
from app.logging import get_logger
from app.services.live_session import get_live_session
from app.services.session_persistence import enqueue_class_session_upsert
from app.utils.ids import generate_event_id

logger = get_logger(__name__)

CONTEXT_SCHEMA_VERSION = 1


def _cache_path() -> Path:
    settings = get_settings()
    root = Path(getattr(settings, "data_dir", None) or "data")
    return root / "lesson_cache" / "today.json"


def load_day_cache() -> Dict[str, Any]:
    path = _cache_path()
    if not path.exists():
        return {"schema_version": CONTEXT_SCHEMA_VERSION, "cached_at": None, "occurrences": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("lesson_cache_read_failed", error=str(e))
        return {"schema_version": CONTEXT_SCHEMA_VERSION, "cached_at": None, "occurrences": []}


def save_day_cache(occurrences: List[Dict[str, Any]]) -> Dict[str, Any]:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "occurrences": occurrences,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def get_cached_occurrence(occurrence_id: str) -> Optional[Dict[str, Any]]:
    cache = load_day_cache()
    for row in cache.get("occurrences") or []:
        if str(row.get("id")) == str(occurrence_id):
            return row
    return None


def read_session_context(session_id: str | None) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    db = get_session()
    try:
        row = db.query(ClassSession).filter(ClassSession.session_id == session_id).first()
        if not row or not row.metadata_json:
            return None
        meta = json.loads(row.metadata_json)
        if not isinstance(meta, dict):
            return None
        ctx = meta.get("lesson_context") or meta
        return ctx if isinstance(ctx, dict) else None
    except Exception as e:
        logger.warning("read_session_context_failed", error=str(e))
        return None
    finally:
        close_session(db)


def build_context_from_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza o push do browser (ou cache) em snapshot estável."""
    roster = body.get("roster") or []
    student_map: Dict[str, str] = {}
    for item in roster:
        if not isinstance(item, dict):
            continue
        edge_key = str(item.get("edge_student_key") or "").strip()
        ext = str(item.get("external_ref") or item.get("external_student_id") or "").strip()
        if edge_key and ext:
            student_map[edge_key] = ext

    scheduled_start = body.get("scheduled_start_at")
    duration = body.get("scheduled_duration_minutes")
    try:
        duration_i = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_i = None

    return {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "lesson_occurrence_id": str(body.get("lesson_occurrence_id") or body.get("id") or ""),
        "organization_id": body.get("organization_id"),
        "school_id": body.get("school_id") or body.get("cloud_school_id"),
        "class_group_id": body.get("class_group_id"),
        "subject_id": body.get("subject_id"),
        "teacher_profile_id": body.get("teacher_profile_id"),
        "room_id": body.get("room_id"),
        "class_group_name": body.get("class_group_name") or body.get("turma"),
        "subject_name": body.get("subject_name") or body.get("disciplina"),
        "teacher_name": body.get("teacher_name") or body.get("professor"),
        "room_name": body.get("room_name") or body.get("sala"),
        "title": body.get("title"),
        "scheduled_start_at": scheduled_start,
        "scheduled_duration_minutes": duration_i,
        "external_lesson_id": (str(body.get("external_lesson_id") or "").strip() or None),
        "block_group_id": body.get("block_group_id"),
        "roster": roster,
        "student_map": student_map,
        "pushed_at": datetime.now(timezone.utc).isoformat(),
    }


def _bind_orchestrator(session_id: str) -> None:
    try:
        from app.main import orchestrator

        if orchestrator:
            orchestrator.active_session_id = session_id
            for p in orchestrator.presence_pipelines.values():
                p.set_session_id(session_id)
            for b in orchestrator.behavioral_pipelines.values():
                b.set_session_id(session_id)
            for c in orchestrator.climate_analytics.values():
                c.session_id = session_id
    except Exception as e:
        logger.warning("bind_orchestrator_failed", error=str(e))


def start_session_with_context(body: Dict[str, Any]) -> Dict[str, Any]:
    """Inicia ou retoma sessão com contexto de aula planejada.

    Regras aprovadas:
    - outra sessão active de outra ocorrência → BLOCK
    - mesma ocorrência active → retoma
    - ocorrência com sessão ended → NOVA session_id (+ aviso)
    """
    settings = get_settings()
    occurrence_id = str(body.get("lesson_occurrence_id") or body.get("id") or "").strip()
    if not occurrence_id:
        return {"ok": False, "error": "missing_lesson_occurrence_id", "code": "missing_occurrence"}

    # Prefer payload; se incompleto, tenta cache local (offline)
    ctx_src = dict(body)
    if not ctx_src.get("class_group_name") and not ctx_src.get("external_lesson_id"):
        cached = get_cached_occurrence(occurrence_id)
        if cached:
            merged = dict(cached)
            merged.update({k: v for k, v in body.items() if v is not None})
            ctx_src = merged
        elif body.get("require_full_context"):
            return {
                "ok": False,
                "error": "occurrence_not_in_cache_and_incomplete_payload",
                "code": "offline_no_context",
            }

    ctx = build_context_from_payload({**ctx_src, "lesson_occurrence_id": occurrence_id})
    if not ctx.get("lesson_occurrence_id"):
        return {"ok": False, "error": "invalid_context", "code": "invalid_context"}

    db = get_session()
    try:
        repo = ClassSessionRepository(db)
        active = repo.get_active()
        if active:
            active_ctx = None
            try:
                if active.metadata_json:
                    meta = json.loads(active.metadata_json)
                    active_ctx = meta.get("lesson_context") if isinstance(meta, dict) else None
            except Exception:
                active_ctx = None
            active_occ = str((active_ctx or {}).get("lesson_occurrence_id") or "")
            if active_occ and active_occ == occurrence_id:
                get_live_session().bind_session_id(active.session_id)
                _bind_orchestrator(active.session_id)
                return {
                    "ok": True,
                    "status": "resumed",
                    "session_id": active.session_id,
                    "lesson_occurrence_id": occurrence_id,
                    "context": active_ctx or ctx,
                    "reopen": False,
                    "message": "Sessão ativa retomada para esta aula.",
                }
            if active_occ:
                # Conflito: outra aula formal ativa
                title = getattr(active, "title", None) or "outra aula"
                label = None
                if isinstance(active_ctx, dict):
                    parts = [
                        active_ctx.get("class_group_name"),
                        active_ctx.get("subject_name"),
                    ]
                    label = " · ".join([p for p in parts if p]) or title
                return {
                    "ok": False,
                    "error": "another_session_active",
                    "code": "conflict_active_session",
                    "active_session_id": active.session_id,
                    "active_lesson_occurrence_id": active_occ or None,
                    "active_label": label or title,
                    "message": (
                        f"Já existe uma aula em andamento ({label or title}). "
                        "Encerre essa aula antes de iniciar outra."
                    ),
                }
            # Sessão automática / sem lesson_context: encerra e segue com aula formal
            logger.info(
                "superseding_contextless_session",
                session_id=active.session_id,
                title=getattr(active, "title", None),
                new_occurrence_id=occurrence_id,
            )
            ended_sid = active.session_id
            try:
                started_ts = (
                    active.started_at.timestamp()
                    if getattr(active, "started_at", None) is not None
                    else time.time()
                )
            except Exception:
                started_ts = time.time()
            repo.end_session(ended_sid)
            try:
                enqueue_class_session_upsert(
                    session_id=ended_sid,
                    status="ended",
                    started_at=started_ts,
                    ended_at=time.time(),
                    title=getattr(active, "title", None) or "Sessão automática",
                )
            except Exception as e:
                logger.warning("supersede_enqueue_end_failed", error=str(e))

        # Reabertura: houve sessão ended para esta ocorrência?
        reopen = False
        prior = (
            db.query(ClassSession)
            .filter(ClassSession.status == "ended")
            .order_by(ClassSession.ended_at.desc())
            .limit(40)
            .all()
        )
        for row in prior:
            try:
                if not row.metadata_json:
                    continue
                meta = json.loads(row.metadata_json)
                lc = meta.get("lesson_context") if isinstance(meta, dict) else None
                if isinstance(lc, dict) and str(lc.get("lesson_occurrence_id")) == occurrence_id:
                    reopen = True
                    break
            except Exception:
                continue

        sid = generate_event_id()
        room = (
            str(ctx.get("room_id") or "")
            or (settings.cameras[0].room_id if settings.cameras else "DEV")
        )
        title = (
            ctx.get("title")
            or " · ".join(
                [
                    p
                    for p in [
                        ctx.get("class_group_name"),
                        ctx.get("subject_name"),
                    ]
                    if p
                ]
            )
            or "Aula"
        )
        row = repo.create_session(
            session_id=sid,
            school_id=settings.school_id,
            room_id=room,
            device_id=settings.device_id,
            title=title,
        )
        meta = {
            "external_lesson_id": ctx.get("external_lesson_id"),
            "lesson_occurrence_id": occurrence_id,
            "lesson_context": ctx,
        }
        row.metadata_json = json.dumps(meta, ensure_ascii=False)
        db.commit()

        get_live_session().bind_session_id(sid)
        _bind_orchestrator(sid)

        started = time.time()
        enqueue_class_session_upsert(
            session_id=sid,
            status="active",
            started_at=started,
            title=title,
            external_lesson_id=ctx.get("external_lesson_id"),
            lesson_occurrence_id=occurrence_id,
            class_group_id=ctx.get("class_group_id"),
            subject_id=ctx.get("subject_id"),
            teacher_profile_id=ctx.get("teacher_profile_id"),
            room_id=ctx.get("room_id") if _looks_uuid(ctx.get("room_id")) else None,
            scheduled_start_at=ctx.get("scheduled_start_at"),
            scheduled_duration_minutes=ctx.get("scheduled_duration_minutes"),
            organization_id=ctx.get("organization_id"),
            cloud_school_id=ctx.get("school_id"),
        )

        warn = None
        if reopen:
            warn = (
                "Esta aula já teve uma sessão encerrada hoje. "
                "Uma nova sessão será criada (dados separados)."
            )

        return {
            "ok": True,
            "status": "started",
            "session_id": sid,
            "lesson_occurrence_id": occurrence_id,
            "context": ctx,
            "reopen": reopen,
            "warning": warn,
            "message": "Aula iniciada." if not reopen else warn,
        }
    finally:
        close_session(db)


def _looks_uuid(value: Any) -> bool:
    s = str(value or "")
    return len(s) == 36 and s.count("-") == 4


def current_context_payload() -> Dict[str, Any]:
    live = get_live_session()
    sid = getattr(live, "session_id", None) or None
    ctx = read_session_context(sid)
    started = None
    status = None
    title = None
    db = get_session()
    try:
        if sid:
            row = db.query(ClassSession).filter(ClassSession.session_id == sid).first()
            if row:
                status = row.status
                title = row.title
                if row.started_at:
                    try:
                        started = row.started_at.replace(tzinfo=timezone.utc).timestamp()
                    except Exception:
                        started = None
        active = ClassSessionRepository(db).get_active()
        active_id = active.session_id if active else None
    finally:
        close_session(db)

    return {
        "session_id": sid,
        "status": status,
        "title": title,
        "started_at": started,
        "active_session_id": active_id,
        "context": ctx,
        "cache": {
            "cached_at": load_day_cache().get("cached_at"),
            "count": len(load_day_cache().get("occurrences") or []),
        },
    }
