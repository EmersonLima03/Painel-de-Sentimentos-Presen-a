"""FastAPI main application."""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Dict
from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, Any, Union
import html as html_module
import cv2
import io
import numpy as np
import sys
import json

_WIN32 = sys.platform == "win32"
try:
    _CAP_DSHOW_PROBE = cv2.CAP_DSHOW
except AttributeError:
    _CAP_DSHOW_PROBE = None

from app.config import get_settings, reload_settings
from app.logging import configure_logging, get_logger
from app.db.init_db import init_database
from app.db.init_db import get_session, close_session
from app.db.repo import (
    EventRepository,
    StudentRepository,
    FaceEmbeddingRepository,
    BehavioralEventRepository,
    ClassSessionRepository,
    ConsentRepository,
    PrivacyAuditRepository,
)
from app.pipeline.orchestrator import PipelineOrchestrator
from app.sync.worker import SyncWorker
from app.enroll.service import EnrollmentService
from app.backup import export_backup, import_backup, BackupResult
from app.auth import require_api_token
from app import __version__
from app.api.v1 import router as api_v1_router, live_hub
from app.runtime_mode import get_runtime_mode, is_demo, RuntimeMode, DEMO_BANNER

# Configurar logging
configure_logging()
logger = get_logger(__name__)

# Globals
orchestrator: PipelineOrchestrator = None
sync_worker: SyncWorker = None
demo_engine = None
start_time = time.time()
_debug_last_frame: Dict[str, Any] = {}  # camera_id -> frame (último frame para viewer fluido)
_DEBUG_SNAPSHOT_MAX_WIDTH = 960
_DEBUG_SNAPSHOT_JPEG_QUALITY = 80
_DEBUG_VIDEO_MAX_WIDTH = 1280  # preview — equilíbrio qualidade/latência (Ryzen 5)
_integrations_status_cache: Dict[str, Any] = {}
_integrations_status_cache_ts: float = 0.0
_INTEGRATIONS_STATUS_CACHE_TTL = 5.0


def _debug_placeholder_jpeg(text: str = "Aguardando frames...", width: int = 640, height: int = 360) -> bytes:
    """Gera um JPEG placeholder (cinza com texto) para o viewer nunca receber resposta não-imagem."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (40, 40, 40)
    cv2.putText(img, text, (width // 6, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 180, 180), 2)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, _DEBUG_SNAPSHOT_JPEG_QUALITY])
    return buf.tobytes()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle do FastAPI."""
    global orchestrator, sync_worker, demo_engine

    mode = get_runtime_mode()
    logger.info("app_starting", version=__version__, runtime_mode=mode.value)

    try:
        # Banco de produção (presença) — nunca recebe dados demo
        init_database()
        logger.info("database_initialized")
        try:
            from app.validation.db import init_validation_db

            init_validation_db()
        except Exception as e:
            logger.warning("validation_db_init_failed", error=str(e))

        # Retoma ClassSession ACTIVE antes de aceitar tráfego (evita UUID efêmero).
        if mode != RuntimeMode.DEMO:
            try:
                from app.services.session_bootstrap import ensure_active_class_session

                ensure_active_class_session(create_if_missing=True)
            except Exception as e:
                logger.warning("session_bootstrap_startup_failed", error=str(e))

        sync_worker = SyncWorker()
        asyncio.create_task(sync_worker.start())

        if mode == RuntimeMode.DEMO:
            from app.demo.engine import get_demo_engine
            from app.config import get_settings as _gs

            settings = _gs()
            demo_engine = get_demo_engine()
            # Garante path demo isolado
            demo_engine.demo_db_path = getattr(settings, "demo_db_path", "./data/demo/dulino_edge_demo.db")
            demo_engine.start()
            asyncio.create_task(live_hub.demo_ticker())
            logger.info("demo_engine_started", banner=DEMO_BANNER, demo_db=demo_engine.demo_db_path)
            # Orchestrator RTSP não sobe em demo (evita misturar fontes)
            orchestrator = None
        else:
            asyncio.create_task(live_hub.rtsp_ticker())
            _orchestrator = PipelineOrchestrator()
            orchestrator = _orchestrator

            async def init_and_start_orchestrator():
                try:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, _orchestrator.initialize)
                    logger.info("orchestrator_initialized")
                    await _orchestrator.start()
                except Exception as e:
                    # RTSP inválido não derruba a aplicação
                    logger.warning(
                        "orchestrator_init_failed",
                        error=str(e),
                        camera_status="connection_failed_or_init_error",
                        exc_info=True,
                    )

            asyncio.create_task(init_and_start_orchestrator())

        logger.info("app_started")

    except Exception as e:
        logger.error("startup_error", error=str(e))

    yield

    logger.info("app_stopping")
    try:
        if demo_engine:
            demo_engine.stop()
        if orchestrator:
            orchestrator.stop()
        if sync_worker:
            sync_worker.stop()
    except Exception as e:
        logger.warning("shutdown_error", error=str(e))

    logger.info("app_stopped")


# Criar app FastAPI
app = FastAPI(
    title="Dulino Edge Vision",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

app.include_router(api_v1_router)

# Servir arquivos estáticos (se existirem)
static_dir = Path(__file__).parent.parent / "app" / "static"
if static_dir.exists():
    try:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    except Exception as e:
        logger.warning("static_files_mount_failed", error=str(e))

# Assets do dashboard React (Vite → frontend/dist/assets)
_frontend_assets = Path(__file__).parent.parent / "frontend" / "dist" / "assets"
if _frontend_assets.exists():
    try:
        app.mount("/assets", StaticFiles(directory=str(_frontend_assets)), name="frontend_assets")
    except Exception as e:
        logger.warning("frontend_assets_mount_failed", error=str(e))


# --- Dashboard unificado (Módulo Emoções 40%) ---

class ReviewBody(BaseModel):
    result: str  # confirmed | rejected | inconclusive
    reviewed_by: str = "dashboard_user"


class ConsentBody(BaseModel):
    student_id: str
    consent_given: bool
    guardian_name: Optional[str] = None
    notes: Optional[str] = None


class SessionBody(BaseModel):
    room_id: Optional[str] = None
    title: Optional[str] = None


_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
_LEGACY_DASHBOARD = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/", response_class=HTMLResponse)
async def dashboard_page():
    """Dashboard educacional React (build em frontend/dist). Fallback: legado."""
    index = _FRONTEND_DIST / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        if is_demo():
            # Injeta banner se o HTML estático ainda não tiver (React também exibe)
            pass
        return HTMLResponse(html)
    if _LEGACY_DASHBOARD.exists():
        return HTMLResponse(_LEGACY_DASHBOARD.read_text(encoding="utf-8"))
    raise HTTPException(404, "dashboard build missing — run: cd frontend && npm run build")


@app.get("/dashboard-legacy", response_class=HTMLResponse)
async def dashboard_legacy_page():
    if not _LEGACY_DASHBOARD.exists():
        raise HTTPException(404, "dashboard.html missing")
    return HTMLResponse(_LEGACY_DASHBOARD.read_text(encoding="utf-8"))


@app.get("/debug/vision", response_class=HTMLResponse)
async def debug_vision_page(request: Request, _: None = Depends(require_api_token)):
    """Dashboard técnico — localhost por padrão; sem RTSP/creds/embeddings/frames."""
    settings = get_settings()
    client = request.client.host if request.client else ""
    allow_remote = bool(getattr(settings, "debug_vision_allow_remote", False))
    if not allow_remote and client not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "debug vision restricted to localhost")
    path = Path(__file__).parent / "static" / "debug_vision.html"
    if not path.exists():
        raise HTTPException(404, "debug_vision.html missing")
    html = path.read_text(encoding="utf-8")
    if is_demo():
        html = html.replace(
            "<h1>/debug/vision</h1>",
            f"<h1>/debug/vision</h1><span class=\"warn\">{DEMO_BANNER}</span>",
        )
    return HTMLResponse(html)


@app.get("/dashboard/api/overview")
async def dashboard_overview(_: None = Depends(require_api_token)):
    """Payload único: sistema + câmeras + fila + engajamento + clima."""
    from app.services.dashboard_reports import unified_overview

    settings = get_settings()
    session = get_session()
    try:
        return unified_overview(
            orchestrator,
            session,
            version=__version__,
            uptime_seconds=int(time.time() - start_time),
            simulation_mode=bool(settings.simulation),
            supabase_enabled=bool((getattr(settings, "supabase_ingest_url", None) or "").strip()),
            device_id=settings.device_id,
            school_id=str(settings.school_id),
        )
    finally:
        close_session(session)


@app.get("/dashboard/api/live")
async def dashboard_live(_: None = Depends(require_api_token)):
    from app.services.dashboard_reports import live_kpis

    session = get_session()
    try:
        return live_kpis(orchestrator, session)
    finally:
        close_session(session)


@app.get("/dashboard/api/timeline")
async def dashboard_timeline(
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    _: None = Depends(require_api_token),
):
    from app.services.dashboard_reports import session_timeline

    session = get_session()
    try:
        return session_timeline(session, session_id=session_id, room_id=room_id)
    finally:
        close_session(session)


@app.get("/dashboard/api/engagement")
async def dashboard_engagement(room_id: Optional[str] = None, _: None = Depends(require_api_token)):
    from app.services.dashboard_reports import engagement_report

    session = get_session()
    try:
        return engagement_report(session, room_id=room_id)
    finally:
        close_session(session)


@app.get("/dashboard/api/climate")
async def dashboard_climate(room_id: Optional[str] = None, _: None = Depends(require_api_token)):
    from app.services.dashboard_reports import climate_report

    session = get_session()
    try:
        return climate_report(session, room_id=room_id)
    finally:
        close_session(session)


@app.get("/dashboard/api/observability")
async def dashboard_observability(room_id: Optional[str] = None, _: None = Depends(require_api_token)):
    from app.services.dashboard_reports import observability_summary

    session = get_session()
    try:
        return observability_summary(session, room_id=room_id)
    finally:
        close_session(session)


@app.get("/dashboard/api/events")
async def dashboard_events(
    status: Optional[str] = "pending_review",
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    _: None = Depends(require_api_token),
):
    session = get_session()
    try:
        repo = BehavioralEventRepository(session)
        rows = repo.list_events(session_id=session_id, room_id=room_id, status=status, limit=100)
        return {
            "events": [
                {
                    "event_id": r.event_id,
                    "event_type": r.event_type,
                    "duration_seconds": r.duration_seconds,
                    "confidence": r.confidence,
                    "status": r.status,
                    "anonymous_track_id": r.anonymous_track_id,
                    "observation_quality": r.observation_quality,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }
    finally:
        close_session(session)


@app.post("/dashboard/api/events/{event_id}/review")
async def dashboard_review_event(event_id: str, body: ReviewBody, _: None = Depends(require_api_token)):
    if body.result not in ("confirmed", "rejected", "inconclusive"):
        raise HTTPException(400, "result must be confirmed|rejected|inconclusive")
    session = get_session()
    try:
        repo = BehavioralEventRepository(session)
        row = repo.review(event_id, body.result, body.reviewed_by)
        if not row:
            raise HTTPException(404, "event not found")
        PrivacyAuditRepository(session).log(
            "event_review",
            actor=body.reviewed_by,
            detail={"event_id": event_id, "result": body.result},
        )
        return {"ok": True, "event_id": event_id, "status": row.status}
    finally:
        close_session(session)


@app.post("/sessions/start")
async def sessions_start(body: SessionBody, _: None = Depends(require_api_token)):
    from app.utils.ids import generate_event_id
    from app.services.live_session import get_live_session
    from app.services.session_persistence import enqueue_class_session_upsert
    import time as _time
    import json as _json

    settings = get_settings()
    session = get_session()
    try:
        repo = ClassSessionRepository(session)
        active = repo.get_active(room_id=body.room_id)
        if active:
            return {"session_id": active.session_id, "status": "already_active"}
        sid = generate_event_id()
        room = body.room_id or (settings.cameras[0].room_id if settings.cameras else "DEV")
        title = body.title or "Sessão manual"
        external_lesson = (getattr(settings, "lxp_external_lesson_id", "") or "").strip() or None
        row = repo.create_session(
            session_id=sid,
            school_id=settings.school_id,
            room_id=room,
            device_id=settings.device_id,
            title=title,
        )
        if external_lesson and row:
            row.metadata_json = _json.dumps({"external_lesson_id": external_lesson})
            session.commit()
        if orchestrator:
            orchestrator.active_session_id = sid
            for p in orchestrator.presence_pipelines.values():
                p.set_session_id(sid)
            for b in orchestrator.behavioral_pipelines.values():
                b.set_session_id(sid)
            for c in orchestrator.climate_analytics.values():
                c.session_id = sid
        get_live_session().bind_session_id(sid)
        enqueue_class_session_upsert(
            session_id=sid,
            status="active",
            started_at=_time.time(),
            title=title,
            external_lesson_id=external_lesson,
        )
        return {"session_id": sid, "status": "active"}
    finally:
        close_session(session)


@app.post("/sessions/{session_id}/end")
async def sessions_end(session_id: str, _: None = Depends(require_api_token)):
    from app.db.models import ClassSession
    from app.services.session_persistence import enqueue_class_session_upsert, enqueue_report_snapshot
    from app.services.live_session import get_live_session
    import time as _time
    import json as _json

    session = get_session()
    try:
        repo = ClassSessionRepository(session)
        row = session.query(ClassSession).filter(ClassSession.session_id == session_id).first()
        ok = repo.end_session(session_id)
        if not ok:
            raise HTTPException(404, "session not found")
        started = _time.time()
        title = None
        ctx = {}
        if row is not None:
            title = getattr(row, "title", None)
            if getattr(row, "started_at", None) is not None:
                try:
                    started = row.started_at.timestamp()
                except Exception:
                    pass
            try:
                if row.metadata_json:
                    meta = _json.loads(row.metadata_json)
                    if isinstance(meta, dict):
                        ctx = meta.get("lesson_context") if isinstance(meta.get("lesson_context"), dict) else meta
            except Exception:
                ctx = {}
        enqueue_class_session_upsert(
            session_id=session_id,
            status="ended",
            started_at=started,
            ended_at=_time.time(),
            title=title,
            external_lesson_id=(ctx or {}).get("external_lesson_id"),
            lesson_occurrence_id=(ctx or {}).get("lesson_occurrence_id"),
            class_group_id=(ctx or {}).get("class_group_id"),
            subject_id=(ctx or {}).get("subject_id"),
            teacher_profile_id=(ctx or {}).get("teacher_profile_id"),
            room_id=(ctx or {}).get("room_id") if len(str((ctx or {}).get("room_id") or "")) == 36 else None,
            scheduled_start_at=(ctx or {}).get("scheduled_start_at"),
            scheduled_duration_minutes=(ctx or {}).get("scheduled_duration_minutes"),
            organization_id=(ctx or {}).get("organization_id"),
            cloud_school_id=(ctx or {}).get("school_id"),
        )
        try:
            live = get_live_session()
            report = live.build_report({})
        except Exception:
            live = None
            report = {"status": "ended", "session_id": session_id}
        enqueue_report_snapshot(
            session_id=session_id,
            report=report if isinstance(report, dict) else {"status": "ended"},
            is_final=True,
        )
        # Libera acumuladores pedagógicos após snapshot final (não altera TRI).
        try:
            if live is not None and getattr(live, "session_id", None) == session_id:
                live.reset()
        except Exception:
            pass
        return {"ok": True, "session_id": session_id, "status": "ended"}
    finally:
        close_session(session)


@app.post("/privacy/consent")
async def privacy_consent(body: ConsentBody, _: None = Depends(require_api_token)):
    settings = get_settings()
    session = get_session()
    try:
        row = ConsentRepository(session).upsert(
            student_id=body.student_id,
            school_id=settings.school_id,
            consent_given=body.consent_given,
            guardian_name=body.guardian_name,
            notes=body.notes,
        )
        PrivacyAuditRepository(session).log(
            "consent_upsert",
            detail={"student_id": body.student_id, "consent_given": body.consent_given},
        )
        if orchestrator and getattr(settings, "require_consent", False):
            denied = ConsentRepository(session).students_without_consent(settings.school_id)
            for p in orchestrator.presence_pipelines.values():
                p.set_excluded_students(denied)
        return {
            "student_id": row.student_id,
            "consent_given": row.consent_given,
            "granted_at": row.granted_at.isoformat() if row.granted_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        }
    finally:
        close_session(session)


@app.delete("/privacy/students/{student_id}")
async def privacy_delete_student(student_id: str, _: None = Depends(require_api_token)):
    """Exclusão / desativação (LGPD mínima) — remove embeddings e desativa aluno."""
    settings = get_settings()
    session = get_session()
    try:
        FaceEmbeddingRepository(session).delete_embeddings_for_student(
            student_id, school_id=settings.school_id
        )
        StudentRepository(session).deactivate_student(student_id)
        ConsentRepository(session).upsert(
            student_id=student_id,
            school_id=settings.school_id,
            consent_given=False,
            notes="revoked_via_api",
        )
        PrivacyAuditRepository(session).log(
            "student_erasure",
            detail={"student_id": student_id},
        )
        return {"ok": True, "student_id": student_id, "action": "deactivated_and_embeddings_removed"}
    finally:
        close_session(session)


@app.get("/module/dod")
async def module_dod_status(_: None = Depends(require_api_token)):
    """Checklist DoD do Módulo 40% (status técnico)."""
    session = get_session()
    try:
        from app.services.dashboard_reports import climate_report, engagement_report

        from app.db.models import BehavioralEvent

        eng = engagement_report(session, limit=5)
        clim = climate_report(session, limit=5)
        beh_n = session.query(BehavioralEvent).count()
        return {
            "module": "Emocoes_e_Dashboard_40",
            "checklist": {
                "behavioral_signals": True,
                "climate_channel": True,
                "dashboard_ui": (Path(__file__).parent / "static" / "dashboard.html").exists(),
                "human_review_api": True,
                "session_presence": True,
                "auth_optional_token": True,
                "privacy_consent_api": True,
                "phone_yolo_optional": bool(get_settings().phone_yolo_enabled),
                "has_engagement_windows": len(eng.get("points") or []) > 0,
                "has_climate_windows": len(clim.get("points") or []) > 0,
                "behavioral_events_stored": beh_n,
            },
            "disclaimer": "Estimativa visual observável. Não é diagnóstico emocional.",
        }
    finally:
        close_session(session)


@app.get("/health")
async def health() -> Dict:
    """Health check endpoint."""
    try:
        settings = get_settings()
        uptime = time.time() - start_time
        
        camera_status = {}
        online_cameras = 0
        
        vision_backends = {"detector_backend": "none", "embedder_backend": "none", "faiss_enabled": False}
        if orchestrator:
            try:
                status = orchestrator.get_status()
                camera_status = status.get("cameras", {})
                online_cameras = sum(1 for cam in camera_status.values() if cam.get("is_connected", False))
                vision_backends = orchestrator.get_vision_backends()
            except Exception as e:
                logger.warning("health_orchestrator_error", error=str(e))
        
        # Info de presença para debug
        presence_debug = {}
        if orchestrator and orchestrator.presence_pipelines:
            from app.utils.time import is_in_active_window, parse_active_windows
            presence_debug = {
                "presence_always_on": getattr(settings, "presence_always_on", False),
                "in_active_window": is_in_active_window(parse_active_windows(settings.presence_active_windows)),
                "matcher_embeddings": 0,
            }
            try:
                pipe = next(iter(orchestrator.presence_pipelines.values()))
                if hasattr(pipe.matcher, "index") and pipe.matcher.index.ntotal:
                    presence_debug["matcher_embeddings"] = pipe.matcher.index.ntotal
                elif hasattr(pipe.matcher, "embeddings"):
                    presence_debug["matcher_embeddings"] = len(pipe.matcher.embeddings)
                from app.db.init_db import close_session, get_session
                from app.db.repo import FaceEmbeddingRepository

                sess = get_session()
                try:
                    emb_repo = FaceEmbeddingRepository(sess)
                    presence_debug["templates_per_student"] = emb_repo.get_templates_per_student(
                        school_id=settings.school_id, device_id=settings.device_id
                    )
                finally:
                    close_session(sess)
            except Exception:
                pass

        supabase_enabled = bool((getattr(settings, "supabase_ingest_url", None) or "").strip())
        return {
            "status": "ok",
            "version": __version__,
            "uptime_seconds": int(uptime),
            "cameras_online": online_cameras,
            "cameras_total": len(camera_status),
            "simulation_mode": settings.simulation,
            "detector_backend": vision_backends.get("detector_backend", "none"),
            "embedder_backend": vision_backends.get("embedder_backend", "none"),
            "faiss_enabled": vision_backends.get("faiss_enabled", False),
            "sqlite_path": getattr(settings, "sqlite_path", ""),
            "supabase_enabled": supabase_enabled,
            "presence_debug": presence_debug,
        }
    except Exception as e:
        logger.error("health_endpoint_error", error=str(e))
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/stats")
async def stats() -> Dict:
    """Estatísticas do sistema."""
    from app.db.init_db import close_session

    session = get_session()
    try:
        event_repo = EventRepository(session)
        stats_data = event_repo.get_stats()
        
        orchestrator_status = {}
        if orchestrator:
            try:
                orchestrator_status = orchestrator.get_status()
            except Exception as e:
                logger.warning("orchestrator_status_error", error=str(e))
                orchestrator_status = {"running": False, "error": str(e)}
        else:
            orchestrator_status = {"running": False}
        
        # Contar eventos por tipo
        from sqlalchemy import func
        from app.db.models import Event
        type_counts = session.query(
            Event.event_type,
            func.count(Event.event_id).label('count')
        ).group_by(Event.event_type).all()
        
        events_by_type = {event_type: count for event_type, count in type_counts}
        
        # Contar por status
        status_counts = session.query(
            Event.status,
            func.count(Event.event_id).label('count')
        ).group_by(Event.status).all()
        
        events_by_status = {status: count for status, count in status_counts}
        
        return {
            "status": "ok",
            "events": stats_data,
            "events_by_type": events_by_type,
            "events_by_status": events_by_status,
            "outbox_lanes": event_repo.get_outbox_lane_stats(),
            "orchestrator": orchestrator_status
        }
    except Exception as e:
        logger.error("stats_endpoint_error", error=str(e))
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        close_session(session)


@app.get("/events")
async def list_events(
    status: Optional[str] = Query(None, description="Filtrar por status: pending, sent, failed"),
    event_type: Optional[str] = Query(None, description="Filtrar por tipo: attendance_checkin, engagement_window"),
    limit: int = Query(20, ge=1, le=100, description="Limite de resultados")
) -> Dict:
    """Lista eventos com filtros opcionais."""
    from app.db.init_db import close_session

    session = get_session()
    try:
        from app.db.models import Event
        from sqlalchemy import desc
        import json
        
        query = session.query(Event)
        
        if status:
            query = query.filter(Event.status == status)
        
        if event_type:
            query = query.filter(Event.event_type == event_type)
        
        # Ordenar por mais recente
        events = query.order_by(desc(Event.created_at)).limit(limit).all()
        
        events_list = []
        for event in events:
            try:
                payload = json.loads(event.payload_json) if event.payload_json else {}
            except:
                payload = {"raw": event.payload_json}
            
            events_list.append({
                "event_id": event.event_id,
                "event_type": event.event_type,
                "status": event.status,
                "retries": event.retries,
                "last_error": event.last_error,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "payload": payload
            })
        
        return {
            "status": "ok",
            "count": len(events_list),
            "filters": {
                "status": status,
                "event_type": event_type,
                "limit": limit
            },
            "events": events_list
        }
    except Exception as e:
        logger.error("events_endpoint_error", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        close_session(session)


@app.get("/reports/attendance/today")
async def report_attendance_today() -> Dict:
    """Resumo de presença do dia (inspirado em AI-Based-Student-Monitoring)."""
    from app.db.init_db import close_session
    from app.services.reports import attendance_summary_today

    settings = get_settings()
    session = get_session()
    try:
        return {
            "status": "ok",
            **attendance_summary_today(session, school_id=settings.school_id),
        }
    except Exception as e:
        logger.error("report_attendance_error", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        close_session(session)


@app.get("/reports/engagement/summary")
async def report_engagement_summary(
    room_id: Optional[str] = Query(None, description="Filtrar por sala"),
    limit: int = Query(30, ge=1, le=100),
) -> Dict:
    """Médias de engajamento por janela (emoção + movimento)."""
    from app.db.init_db import close_session
    from app.services.reports import engagement_summary

    session = get_session()
    try:
        return {
            "status": "ok",
            **engagement_summary(session, room_id=room_id, limit=limit),
        }
    except Exception as e:
        logger.error("report_engagement_error", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        close_session(session)


@app.get("/cameras")
async def cameras() -> Dict:
    """Status das câmeras."""
    settings = get_settings()
    cameras_list = []
    
    try:
        # Se orchestrator existe e tem readers, usar status real
        if orchestrator and orchestrator.readers:
            status = orchestrator.get_status()
            cameras_status = status.get("cameras", {})
            
            for camera_id, cam_status in cameras_status.items():
                room_id = "unknown"
                for cam_config in settings.cameras:
                    if cam_config.camera_id == camera_id:
                        room_id = cam_config.room_id
                        break
                raw_match = cam_status.get("last_presence_match")
                cameras_list.append({
                    "camera_id": camera_id,
                    "room_id": room_id,
                    "is_connected": cam_status.get("is_connected", False),
                    "last_frame_time": cam_status.get("last_frame_time", 0.0),
                    "frame_count": cam_status.get("frame_count", 0),
                    "last_error": cam_status.get("last_error"),
                    "faces_detected_last": cam_status.get("faces_detected_last", 0),
                    "last_presence_match": raw_match,
                    "last_presence_event_id": cam_status.get("last_presence_event_id"),
                })
        else:
            # Se não há orchestrator ou readers, mostrar cameras configuradas (mas não conectadas)
            for cam_config in settings.cameras:
                cameras_list.append({
                    "camera_id": cam_config.camera_id,
                    "room_id": cam_config.room_id,
                    "is_connected": False,
                    "last_frame_time": 0.0,
                    "frame_count": 0,
                    "last_error": "Not initialized" if not orchestrator else "RTSP disabled or not connected",
                    "faces_detected_last": 0,
                    "last_presence_match": None,
                    "last_presence_event_id": None,
                })
        
        return {"cameras": cameras_list}
    except Exception as e:
        logger.error("cameras_endpoint_error", error=str(e))
        return {"cameras": [], "error": str(e)}


class EnrollRequest(BaseModel):
    student_id: str
    image_path: str = None


class EnrollWebcamRequest(BaseModel):
    student_id: str
    full_name: Optional[str] = None
    camera_id: str = "cam-web"
    num_frames: Optional[int] = None
    frames_used: Optional[int] = None
    capture_duration: Optional[float] = None
    append_template: bool = False  # True = adiciona template (ex.: óculos/sem); False = substitui
    dry_run: bool = False  # True = só valida qualidade, não grava no banco
    min_quality_score: float = 0.45
    min_good_frames: int = 3


def _enrollment_service() -> EnrollmentService:
    """Reutiliza FacePipeline do orchestrator (mesmo embedder ONNX + YuNet do reconhecimento)."""
    if orchestrator and getattr(orchestrator, "face_pipeline", None) is not None:
        return EnrollmentService(face_pipeline=orchestrator.face_pipeline)
    return EnrollmentService()


@app.post("/enroll")
async def enroll(request: EnrollRequest) -> Dict:
    """Cadastra face de aluno."""
    service = _enrollment_service()
    
    if request.image_path:
        success = service.enroll_from_image(request.image_path, request.student_id)
    else:
        raise HTTPException(status_code=400, detail="image_path required")
    
    if success:
        # Recarregar matcher no orchestrator
        if orchestrator:
            for pipeline in orchestrator.presence_pipelines.values():
                pipeline.reload_matcher()
        
        return {"status": "success", "student_id": request.student_id}
    else:
        raise HTTPException(status_code=500, detail="Enrollment failed")


@app.post("/enroll/webcam")
async def enroll_webcam(request: EnrollWebcamRequest) -> Dict:
    """Cadastra face de aluno capturando da webcam."""
    service = _enrollment_service()
    
    # Tentar reutilizar reader do orchestrator se disponível
    reader = None
    if orchestrator and orchestrator.readers:
        reader = orchestrator.readers.get(request.camera_id)
    
    result = service.enroll_from_webcam(
        camera_id=request.camera_id,
        student_id=request.student_id,
        full_name=request.full_name,
        num_frames=request.num_frames,
        frames_used=request.frames_used,
        capture_duration=request.capture_duration,
        append_template=request.append_template,
        dry_run=request.dry_run,
        min_quality_score=request.min_quality_score,
        min_good_frames=request.min_good_frames,
        reader=reader
    )

    # Dry-run nunca recarrega matcher (não houve gravação)
    if request.dry_run:
        return result

    if result.get("status") == "success":
        # Recarregar matcher no orchestrator
        if orchestrator:
            for pipeline in orchestrator.presence_pipelines.values():
                pipeline.reload_matcher()
        
        return result
    else:
        raise HTTPException(
            status_code=500, 
            detail=result.get("error", "Enrollment failed")
        )


@app.post("/enroll/webcam/preview")
async def enroll_webcam_preview(request: EnrollWebcamRequest) -> Dict:
    """
    Preview guiado de cadastro: captura frames, avalia qualidade e recomenda se está bom.
    Não grava no banco.
    """
    request.dry_run = True
    return await enroll_webcam(request)


@app.post("/config/reload")
async def reload_config() -> Dict:
    """Recarrega configuração."""
    try:
        reload_settings()
        
        # Reinicializar orchestrator se necessário
        if orchestrator:
            orchestrator.stop()
            orchestrator.initialize()
            asyncio.create_task(orchestrator.start())
        
        return {"status": "success", "message": "Configuration reloaded"}
    except Exception as e:
        logger.error("config_reload_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# --- Backup (DAT: embeddings + fila, opcional AES-256) ---

class BackupExportRequest(BaseModel):
    path: Optional[str] = None  # se null, usa backup_dir + timestamp
    include_events: bool = True


class BackupRestoreRequest(BaseModel):
    path: str
    passphrase: Optional[str] = None  # se null, usa BACKUP_PASSPHRASE
    merge_events: bool = False


@app.post("/backup/export")
async def backup_export(body: BackupExportRequest = None) -> Dict:
    """Exporta embeddings e (opcional) fila de eventos. Criptografia se BACKUP_PASSPHRASE definida."""
    body = body or BackupExportRequest()
    settings = get_settings()
    out_path = body.path
    if not out_path:
        from datetime import datetime
        backup_dir = getattr(settings, "backup_dir", None) or "./data/backups"
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        out_path = str(Path(backup_dir) / f"preseca_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.datbackup")
    session = get_session()
    try:
        emb_repo = FaceEmbeddingRepository(session)
        ev_repo = EventRepository(session)
        embeddings = emb_repo.get_all_active_embeddings()
        events = ev_repo.get_pending_events(limit=10000) if body.include_events else []
        passphrase = getattr(settings, "backup_passphrase", None) or None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: export_backup(embeddings, events, out_path, passphrase),
        )
    finally:
        session.close()
    if result.error:
        raise HTTPException(status_code=500, detail=result.error)
    return {
        "status": "success",
        "path": result.path,
        "encrypted": result.encrypted,
        "embeddings_count": result.embeddings_count,
        "events_count": result.events_count,
    }


@app.post("/backup/restore")
async def backup_restore(body: BackupRestoreRequest) -> Dict:
    """Restaura backup (embeddings e opcionalmente fila). Passphrase obrigatória se ficheiro estiver criptografado."""
    settings = get_settings()
    passphrase = body.passphrase or getattr(settings, "backup_passphrase", None)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: import_backup(
            body.path,
            passphrase,
            get_session,
            merge_embeddings=True,
            merge_events=body.merge_events,
        ),
    )
    if result.error:
        raise HTTPException(status_code=400, detail=result.error)
    return {
        "status": "success",
        "path": result.path,
        "embeddings_restored": result.embeddings_count,
        "events_restored": result.events_count,
    }


def _get_debug_frame(camera_id: str) -> Optional[np.ndarray]:
    """Último frame da câmera (buffer assíncrono) — sem ML. Rejeita frame preto/inválido."""
    from app.rtsp.video_capture import _frame_usable

    frame = None
    if orchestrator:
        frame = orchestrator.get_latest_frame(camera_id)
    if frame is None and orchestrator:
        reader = orchestrator.readers.get(camera_id)
        if reader:
            ret, frame = reader.read_frame()
            if not ret:
                frame = None
    if frame is not None and not _frame_usable(frame):
        frame = None
    if frame is None:
        _debug_last_frame.pop(camera_id, None)
        return None
    _debug_last_frame[camera_id] = frame
    return frame


def _debug_snapshot_jpeg_bytes(camera_id: str, overlay: int, full_res: bool) -> bytes:
    """Snapshot único (cadastro legado). Preferir /debug/mjpeg para fluidez."""
    frame = _get_debug_frame(camera_id)
    if frame is None:
        # Mensagem explícita: API 200 ≠ imagem válida.
        err = None
        if orchestrator and camera_id in (orchestrator.readers or {}):
            try:
                err = (orchestrator.readers[camera_id].get_status() or {}).get("last_error")
            except Exception:
                err = None
        if err == "black frame":
            msg = "Sinal da camera perdido (frame preto) — reconectando..."
        elif err:
            msg = f"Sinal da camera: {str(err)[:40]}"
        else:
            msg = "Aguardando frames da camera " + camera_id + "..."
        return _debug_placeholder_jpeg(msg)
    return _encode_preview_jpeg(frame, overlay, camera_id, full_res)


def _overlay_scale_for_frame(camera_id: str, frame_w: int, frame_h: int) -> tuple[float, float]:
    """Escala bboxes do cache (tamanho do frame na detecção) para o frame de preview."""
    if not orchestrator:
        return 1.0, 1.0
    src = orchestrator.get_overlay_source_size(camera_id)
    if not src:
        return 1.0, 1.0
    src_w, src_h = src
    if src_w <= 0 or src_h <= 0:
        return 1.0, 1.0
    return frame_w / float(src_w), frame_h / float(src_h)


def _draw_overlay_from_cache(frame: np.ndarray, camera_id: str) -> int:
    """Desenha person (ciano), face (verde), celular e rótulos person-first."""
    if not orchestrator:
        return 0
    fh, fw = frame.shape[:2]
    sx, sy = _overlay_scale_for_frame(camera_id, fw, fh)
    eng_faces = orchestrator.get_overlay_engagement(camera_id)
    from app.pipeline.analytics_track import filter_displayable_tracks

    analytics_raw = list(getattr(orchestrator, "_analytics_tracks", {}).get(camera_id) or [])
    analytics = filter_displayable_tracks(analytics_raw)

    # person tracks (ciano) — corpo; se YOLO só devolveu o rosto, expande torso a partir da face.
    for t in analytics:
        pb = t.get("person_bbox") or t.get("bbox")
        fb = t.get("face_bbox")
        if (not pb or len(pb) < 4) and fb and len(fb) >= 4:
            tconf = float(t.get("track_confidence") or t.get("confidence") or 0.0)
            body_ok = bool((t.get("observability") or {}).get("body_detected"))
            if not body_ok and tconf < 0.45:
                continue
            pb = [
                fb[0] - fb[2] * 0.35,
                fb[1] - fb[3] * 0.15,
                fb[2] * 1.7,
                fb[3] * 3.1,
            ]
        elif pb and len(pb) >= 4 and fb and len(fb) >= 4:
            pa = max(float(pb[2]) * float(pb[3]), 1.0)
            fa = max(float(fb[2]) * float(fb[3]), 1.0)
            # Close-up: person_bbox ≈ face → membrana de tronco só com corpo/conf úteis
            # (evita ciano inventado em torno de YuNet FP na parede).
            tconf = float(t.get("track_confidence") or t.get("confidence") or 0.0)
            body_ok = bool((t.get("observability") or {}).get("body_detected"))
            if pa < fa * 2.2 and (body_ok or tconf >= 0.45):
                pb = [
                    min(pb[0], fb[0] - fb[2] * 0.25),
                    min(pb[1], fb[1] - fb[3] * 0.10),
                    max(pb[2], fb[2] * 1.65),
                    max(pb[3], fb[3] * 2.8),
                ]
        if not pb or len(pb) < 4:
            continue
        x, y, w, h = int(pb[0] * sx), int(pb[1] * sy), int(pb[2] * sx), int(pb[3] * sy)
        x, y = max(0, x), max(0, y)
        w, h = max(8, w), max(8, h)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 0), 2)  # cyan-ish BGR
        ident = t.get("identity") or {}
        sid = ident.get("student_id") or t.get("student_id")
        src = ident.get("source") or "?"
        conf = float(ident.get("confidence") or t.get("confidence") or 0.0)
        gap = ident.get("seconds_since_face_seen")
        pid = t.get("person_track_id") or t.get("track_id") or ""
        face_vis = ident.get("face_visible")
        tstate = t.get("tracking_state") or "active"
        det_gap = t.get("seconds_since_person_detection")
        line1 = f"{pid}"
        if sid:
            line1 = f"{pid} {sid} ({conf:.2f}) [{src}]"
        else:
            line1 = f"{pid} unknown"
        line1 = f"{line1} [{tstate}]"
        from app.pipeline.analytics_track import ascii_overlay_label

        cv2.putText(
            frame,
            ascii_overlay_label(line1)[:56],
            (x, max(y - 8, 16)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 0),
            1,
        )
        status_bits = []
        if tstate == "temporarily_lost":
            status_bits.append("Track temporariamente perdido")
            if det_gap is not None:
                status_bits.append(f"corpo {float(det_gap):.1f}s")
        elif tstate == "reassociated":
            status_bits.append("Track reassociado")
        if face_vis:
            status_bits.append("Rosto visivel")
        elif sid:
            status_bits.append("Rosto temporariamente oculto")
            if gap is not None:
                status_bits.append(f"face {float(gap):.1f}s")
        else:
            status_bits.append("Identidade desconhecida")
        hs = (t.get("head_state") or {}).get("state")
        if hs and "head_down" in str(hs):
            status_bits.append("Cabeca baixa")
        occ = (t.get("face_occlusion") or {}).get("state")
        if occ and occ != "none":
            status_bits.append("Possivel oclusao por mao")
        ph = (t.get("phone") or {}).get("state")
        if ph in ("possible_phone_interaction", "probable_phone_interaction"):
            status_bits.append("Possivel interacao com celular")
        elif ph and ph not in ("not_detected", "none"):
            status_bits.append("Celular visivel")
        va = (t.get("visual_attention") or {}).get("state")
        if va == "inconclusive":
            status_bits.append("Estado inconclusivo")
        label2 = ascii_overlay_label(" | ".join(status_bits[:3]) or "Pessoa rastreada")
        cv2.putText(
            frame, label2[:56], (x, min(y + h + 16, fh - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1
        )
        # face bbox verde
        fb = t.get("face_bbox")
        if fb and len(fb) >= 4:
            fx, fy, fw_, fh_ = int(fb[0] * sx), int(fb[1] * sy), int(fb[2] * sx), int(fb[3] * sy)
            cv2.rectangle(frame, (fx, fy), (fx + fw_, fy + fh_), (0, 255, 0), 2)

    # fallback legado se sem analytics
    if not analytics:
        matches = orchestrator.get_overlay_matches(camera_id)
        boxes = orchestrator.get_overlay_boxes(camera_id)
        n = max(len(matches), len(boxes))
        for i in range(n):
            m = dict(matches[i]) if i < len(matches) else {}
            sid = m.get("student_id")
            conf = float(m.get("confidence") or 0.0)
            if not sid and conf < 0.10:
                continue
            if i < len(boxes):
                x, y, w, h = boxes[i]
            else:
                bbox = m.get("bbox") or [0, 0, 0, 0]
                x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
            x, y, w, h = int(x * sx), int(y * sy), int(w * sx), int(h * sy)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            display = (m.get("full_name") or sid or "?").strip()
            cv2.putText(
                frame, f"{display} ({conf:.2f})", (x, max(y - 5, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2
            )

    # celulares (magenta)
    phones = getattr(orchestrator, "_overlay_phones", {}).get(camera_id) or []
    for p in phones:
        bb = p[:4] if not isinstance(p, dict) else (p.get("bbox") or [0, 0, 0, 0])
        if len(bb) < 4:
            continue
        x, y, w, h = int(bb[0] * sx), int(bb[1] * sy), int(bb[2] * sx), int(bb[3] * sy)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 255), 2)

    n_people = len(analytics) if analytics else len(orchestrator.get_overlay_boxes(camera_id) or [])
    cv2.putText(
        frame,
        f"pessoas: {n_people}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 0),
        2,
    )
    return n_people


def _encode_preview_jpeg(frame: np.ndarray, overlay: int, camera_id: str, full_res: bool) -> bytes:
    """Encode rápido para MJPEG/snapshot — reduz resolução antes do overlay/JPEG."""
    h, w = frame.shape[:2]
    max_w = w if full_res else _DEBUG_VIDEO_MAX_WIDTH
    if w > max_w:
        scale = max_w / w
        frame = cv2.resize(
            frame,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_AREA,
        )
    else:
        frame = frame.copy()
    if overlay == 1:
        _draw_overlay_from_cache(frame, camera_id)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _DEBUG_SNAPSHOT_JPEG_QUALITY])
    if not ok:
        return _debug_placeholder_jpeg("encode error")
    return buf.tobytes()


@app.get("/debug/snapshot")
async def debug_snapshot(
    camera_id: Optional[str] = Query(None, description="ID da câmera (ex: cam-web)"),
    overlay: int = Query(0, description="1=desenhar bboxes e labels de match no frame"),
    full_res: bool = Query(
        False,
        description="Se true, não reduz largura (padrão: máx. 960px para o viewer). Use para confirmar 1920×1080.",
    ),
):
    """Snapshot de debug. Requer ENABLE_DEBUG_SNAPSHOT=1. overlay=1 desenha bboxes e label. Apenas webcam do notebook (cam-web)."""
    settings = get_settings()
    if not settings.enable_debug_snapshot:
        raise HTTPException(status_code=404, detail="Debug snapshot disabled (ENABLE_DEBUG_SNAPSHOT=1)")

    available = list(orchestrator.readers.keys()) if orchestrator and orchestrator.readers else [
        c.camera_id for c in settings.cameras
    ]
    if not camera_id:
        return JSONResponse(
            status_code=400,
            content={"error": "camera_id required", "available_cameras": available or []}
        )

    if orchestrator:
        reader = orchestrator.readers.get(camera_id)
        if not reader and available:
            return JSONResponse(
                status_code=404,
                content={"error": f"Camera {camera_id} not found", "available_cameras": available},
            )
    else:
        reader = None

    body = _debug_snapshot_jpeg_bytes(camera_id, overlay, full_res)
    return StreamingResponse(
        io.BytesIO(body),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/debug/mjpeg")
async def debug_mjpeg(
    camera_id: str = Query("cam-web", description="ID da câmera"),
    overlay: int = Query(1, description="1=overlay de faces/nomes"),
    fps: float = Query(20.0, ge=2, le=30, description="Quadros por segundo (20 recomendado para RTSP)"),
):
    """
    Stream MJPEG (multipart) — um fluxo contínuo, mais suave que vários GET /debug/snapshot.
    Requer ENABLE_DEBUG_SNAPSHOT=1. No viewer embutido use <img src="/debug/mjpeg?...">.
    """
    settings = get_settings()
    if not settings.enable_debug_snapshot:
        raise HTTPException(status_code=404, detail="Debug snapshot disabled (ENABLE_DEBUG_SNAPSHOT=1)")

    delay = 1.0 / fps

    def mjpeg_frames():
        boundary = b"--frame\r\n"
        ct = b"Content-Type: image/jpeg\r\n\r\n"
        demo_src = None
        if is_demo():
            from app.vision.frame_source import DemoFrameSource

            demo_src = DemoFrameSource(camera_id="demo-cam", fps=max(fps, 5.0))
            demo_src.open()
        while True:
            if is_demo() and demo_src is not None:
                pkt = demo_src.read()
                if pkt is None:
                    time.sleep(0.05)
                    continue
                frame = pkt.frame.copy()
                cv2.putText(
                    frame,
                    "DEMO — NAO E SUA WEBCAM",
                    (24, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 200, 255),
                    2,
                )
                cv2.putText(
                    frame,
                    "RUNTIME_MODE=demo (dados simulados)",
                    (24, 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (180, 180, 180),
                    2,
                )
                # Desenha “alunos” fictícios do snapshot se disponível
                try:
                    from app.demo.engine import get_demo_engine

                    for tr in get_demo_engine().snapshot().get("tracks", []):
                        x, y, w, h = tr.get("bbox") or [0, 0, 80, 100]
                        cv2.rectangle(frame, (int(x), int(y)), (int(x + w), int(y + h)), (42, 157, 143), 2)
                        name = (tr.get("full_name") or "")[:18]
                        cv2.putText(
                            frame,
                            name,
                            (int(x), max(20, int(y) - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.45,
                            (231, 236, 243),
                            1,
                        )
                except Exception:
                    pass
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _DEBUG_SNAPSHOT_JPEG_QUALITY])
                chunk = buf.tobytes() if ok else _debug_placeholder_jpeg("demo encode error")
            elif not orchestrator or camera_id not in (orchestrator.readers or {}):
                chunk = _debug_placeholder_jpeg("Aguardando camera ou modelos...")
            else:
                try:
                    chunk = _debug_snapshot_jpeg_bytes(camera_id, overlay, full_res=False)
                except Exception as e:
                    logger.warning("mjpeg_frame_error", error=str(e))
                    chunk = _debug_placeholder_jpeg("frame error")
            yield boundary + ct + chunk + b"\r\n"
            time.sleep(delay)

    return StreamingResponse(
        mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
        },
    )


def _open_capture_probe(index: int):
    """Mesma ideia do RTSPReader: no Windows DirectShow costuma bater com Iriun/USB."""
    if _WIN32 and _CAP_DSHOW_PROBE is not None:
        return cv2.VideoCapture(index, _CAP_DSHOW_PROBE)
    return cv2.VideoCapture(index)


def _enumerate_local_cameras(try_1080: bool) -> Dict[str, Any]:
    """Lista índices 0..9 com um frame de teste (pode falhar se o mesmo índice estiver em uso pelo servidor)."""
    devices = []
    for idx in range(10):
        cap = _open_capture_probe(idx)
        if not cap.isOpened():
            devices.append(
                {
                    "index": idx,
                    "opened": False,
                    "frame_ok": False,
                    "width": None,
                    "height": None,
                    "label": f"Câmera {idx} (não abriu)",
                }
            )
            cap.release()
            continue
        try:
            if try_1080:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920.0)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080.0)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            ret, frame = cap.read()
            # Aquecimento curto: USB/Iriun às vezes devolvem 1º frame preto.
            if ret and frame is not None:
                for _ in range(8):
                    r2, f2 = cap.read()
                    if r2 and f2 is not None:
                        frame = f2
            w = h = None
            mean_b = std_b = None
            if ret and frame is not None:
                h, w = frame.shape[:2]
                mean_b = round(float(frame.mean()), 1)
                std_b = round(float(frame.std()), 1)
            else:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            label = f"Câmera {idx}"
            if w and h:
                label = f"Câmera {idx} — {w}×{h}px"
                if w >= 1920 and h >= 1080:
                    label += " (provável 1080p)"
                if mean_b is not None and (mean_b < 8.0 or (std_b is not None and std_b < 5.0)):
                    label += " ⚠ frame preto/plano (Iriun/IR?)"
                elif mean_b is not None:
                    label += f" · brilho {mean_b}"
            devices.append(
                {
                    "index": idx,
                    "opened": True,
                    "frame_ok": bool(ret and frame is not None),
                    "width": w,
                    "height": h,
                    "mean_brightness": mean_b,
                    "std": std_b,
                    "label": label,
                }
            )
        finally:
            cap.release()
    return {
        "devices": devices,
        "hint": (
            'No config.yaml use rtsp_url: "N" com o índice da USB (ex.: XWF-1080P). '
            "Compare width×height e brilho: Iriun Webcam virtual costuma ser 1080p PRETA sem o celular. "
            "Chame com try_1080=false para resolução padrão do driver. "
            "Melhor com uvicorn parado (senão o índice em uso pode falhar ou parecer preto). "
            "Navegador: as_html=1."
        ),
    }


@app.get("/cameras/devices", response_model=None)
async def list_camera_devices(
    try_1080: bool = Query(
        True,
        description="Se true, pede 1920x1080 ao driver antes do frame (ajuda a identificar USB 1080p vs webcam HD). "
        "Use apenas true ou false (valores truncados geram 422).",
    ),
    as_html: bool = Query(
        False,
        description="Se true, devolve página HTML com tabela (melhor no navegador embutido do Cursor/VS Code).",
    ),
) -> Union[JSONResponse, HTMLResponse]:
    """Lista câmeras locais (índices 0..9) com resolução do primeiro frame — use para escolher rtsp_url."""
    settings = get_settings()
    if not getattr(settings, "enable_debug_ui", False) and not getattr(settings, "enable_debug_snapshot", False):
        raise HTTPException(status_code=404, detail="Enable ENABLE_DEBUG_UI or ENABLE_DEBUG_SNAPSHOT")
    payload = _enumerate_local_cameras(try_1080)
    if as_html:
        rows = []
        for d in payload["devices"]:
            rows.append(
                "<tr>"
                f"<td>{d['index']}</td>"
                f"<td>{html_module.escape(str(d['opened']))}</td>"
                f"<td>{html_module.escape(str(d['frame_ok']))}</td>"
                f"<td>{html_module.escape(str(d['width']))}</td>"
                f"<td>{html_module.escape(str(d['height']))}</td>"
                f"<td>{html_module.escape(str(d.get('mean_brightness')))}</td>"
                f"<td>{html_module.escape(str(d['label']))}</td>"
                "</tr>"
            )
        body = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"/><title>Câmeras locais</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1rem; background: #1a1a1a; color: #eee; }}
table {{ border-collapse: collapse; width: 100%; max-width: 960px; }}
th, td {{ border: 1px solid #444; padding: 8px; text-align: left; }}
th {{ background: #333; }}
p.hint {{ max-width: 960px; line-height: 1.5; color: #bbb; }}
code {{ background: #333; padding: 2px 6px; }}
</style></head><body>
<h1>Índices de câmera (0–9)</h1>
<p class="hint">{html_module.escape(payload['hint'])}</p>
<table>
<thead><tr><th>Índice</th><th>Abriu</th><th>Frame OK</th><th>Largura</th><th>Altura</th><th>Brilho</th><th>Descrição</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<p class="hint">JSON: <code>/cameras/devices</code> · HTML: <code>/cameras/devices?as_html=1</code> · sem forçar 1080: <code>?try_1080=false&amp;as_html=1</code></p>
</body></html>"""
        return HTMLResponse(content=body, media_type="text/html; charset=utf-8")
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")


@app.get("/debug/overlay_matches")
async def debug_overlay_matches(
    camera_id: Optional[str] = Query(None, description="ID da câmera (ex: cam-web)")
):
    """Lista current_matches (um por face): track_id, student_id, confidence, unknown. Histerese + top-k por face."""
    settings = get_settings()
    if not getattr(settings, "enable_debug_snapshot", False) and not getattr(settings, "enable_debug_ui", False):
        raise HTTPException(status_code=404, detail="Debug disabled")
    if not orchestrator:
        # 200 em vez de 503: o viewer faz fetch+JSON a cada 1s; lista vazia até o pipeline subir
        return {
            "camera_id": camera_id or "cam-web",
            "current_matches": [],
            "initializing": True,
            "hint": "Orquestrador ainda a carregar modelos/câmera — aguarde alguns segundos.",
        }
    available = list(orchestrator.readers.keys()) if orchestrator.readers else []
    if not camera_id:
        return JSONResponse(status_code=400, content={"error": "camera_id required", "available_cameras": available})
    reader = orchestrator.readers.get(camera_id)
    if not reader:
        return JSONResponse(status_code=404, content={"error": f"Camera {camera_id} not found", "available_cameras": available})
    cached = orchestrator.get_overlay_matches(camera_id)
    if cached:
        matches = cached
    else:
        boxes = orchestrator.get_overlay_boxes(camera_id)
        matches = [
            {
                "track_id": i,
                "bbox": [x, y, w, h],
                "student_id": None,
                "confidence": 0.0,
                "provável": False,
            }
            for i, (x, y, w, h) in enumerate(boxes)
        ]
    if not matches:
        return {
            "camera_id": camera_id,
            "current_matches": [],
            "frame_pending": not orchestrator.has_latest_frame(camera_id),
            "hint": "Aguardando detecção (8 Hz) ou presença (2 s) — sem ML neste endpoint.",
        }
    out = []
    for m in matches:
        sid = m.get("student_id")
        unknown = sid is None
        conf = float(m.get("confidence") or 0.0)
        if unknown and conf < 0.10:
            continue
        name = m.get("full_name")
        if sid and not name:
            from app.db import student_cache

            name = student_cache.get_display_name(sid)
        out.append({
            "track_id": m.get("track_id", 0),
            "label": name if name else ("UNKNOWN" if unknown else sid),
            "student_id": sid,
            "full_name": name,
            "confidence": round(conf, 4),
            "unknown": unknown,
            "top2_score": m.get("top2_score"),
            "margin": m.get("margin"),
            "engagement_state": m.get("engagement_state"),
            "engagement_label": m.get("engagement_label"),
        })
    return {"camera_id": camera_id, "current_matches": out}


@app.get("/debug/integrations_status")
async def debug_integrations_status(
    camera_id: Optional[str] = Query(None, description="ID da câmera"),
) -> Dict:
    """Painel das integrações dos 5 projetos (emoção, relatórios, backends)."""
    global _integrations_status_cache, _integrations_status_cache_ts

    settings = get_settings()
    cam_id = _default_debug_camera_id(camera_id) if orchestrator else (camera_id or "cam-web")
    now = time.time()
    if (
        _integrations_status_cache
        and (now - _integrations_status_cache_ts) < _INTEGRATIONS_STATUS_CACHE_TTL
        and _integrations_status_cache.get("camera_id") == cam_id
    ):
        return _integrations_status_cache

    from app.db.init_db import close_session
    from app.services.reports import attendance_summary_today, engagement_summary
    import json
    from app.db.models import Event
    from sqlalchemy import desc

    session = get_session()
    try:
        integ = orchestrator.get_integrations_status(cam_id) if orchestrator else {}
        att = attendance_summary_today(session, school_id=settings.school_id)
        eng = engagement_summary(session, room_id=integ.get("room_id"), limit=5)

        last_window = None
        ev = (
            session.query(Event)
            .filter(Event.event_type == "engagement_window")
            .order_by(desc(Event.created_at))
            .limit(1)
            .first()
        )
        if ev and ev.payload_json:
            try:
                last_window = json.loads(ev.payload_json)
            except json.JSONDecodeError:
                pass

        result = {
            "status": "ok",
            "camera_id": cam_id,
            "integrations": {
                "real_time_classroom": "Mini-XCEPTION emoção → engajamento por face",
                "engagement_recognition": "rótulos engaged/disengaged",
                "ai_based_student": "GET /reports/attendance/today",
                "presenca_edge": "YuNet + FAISS + FastAPI",
            },
            "backends": integ,
            "attendance_today": {
                "unique_students": att.get("unique_students"),
                "total_checkins": att.get("total_checkins"),
                "students": att.get("students", [])[:10],
            },
            "engagement_summary": {
                "window_count": eng.get("window_count"),
                "engagement_index_mean": eng.get("engagement_index_mean"),
                "faces_detected_mean": eng.get("faces_detected_mean"),
                "last_windows": eng.get("windows", [])[:3],
            },
            "last_engagement_window_event": last_window,
            "api_links": {
                "attendance_report": "/reports/attendance/today",
                "engagement_report": f"/reports/engagement/summary?room_id={integ.get('room_id') or 'DEV'}",
                "events_engagement": "/events?event_type=engagement_window&limit=5",
            },
        }
        _integrations_status_cache = result
        _integrations_status_cache_ts = now
        return result
    except Exception as e:
        logger.error("integrations_status_error", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        close_session(session)


def _default_debug_camera_id(preferred: Optional[str] = None) -> str:
    """Primeira câmera enabled no config; fallback para query ou cam-web."""
    settings = get_settings()
    if preferred:
        return preferred
    for cam in settings.cameras:
        if cam.enabled:
            return cam.camera_id
    if settings.cameras:
        return settings.cameras[0].camera_id
    return "cam-web"


@app.get("/debug/viewer", response_class=HTMLResponse)
async def debug_viewer(camera_id: Optional[str] = Query(None, description="ID da câmera (ex: cam-sala-tech)")):
    """Viewer simples de debug (DEV ONLY). Usa ?camera_id= ou a primeira câmera enabled no config."""
    settings = get_settings()
    if not getattr(settings, "enable_debug_ui", False):
        raise HTTPException(status_code=404, detail="Debug viewer disabled (ENABLE_DEBUG_UI=1)")
    cam_id = _default_debug_camera_id(camera_id)
    th_on = float(getattr(settings, "presence_th_on", 0.75))
    margin_min = float(getattr(settings, "presence_match_margin", 0.08))
    # Viewer bem simples: apenas imagem + texto de status/matches. Sem estilos complexos.
    html = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Debug Viewer (simples)</title>
    <style>
      body { font-family: system-ui, sans-serif; background: #111827; color: #e5e7eb; margin: 0; padding: 12px; }
      h1 { font-size: 18px; margin: 0 0 8px; }
      .video-wrap { width: 100%; max-width: 1280px; margin: 0 0 12px; }
      #frame { width: 100%; height: auto; display: block; border: 1px solid #374151; background: #000; border-radius: 6px; }
      pre { background: #020617; padding: 8px; border-radius: 4px; overflow-x: auto; }
      .row { display: flex; gap: 12px; margin-top: 8px; flex-wrap: wrap; }
      .col { flex: 1 1 260px; }
    </style>
  </head>
  <body>
    <h1>Debug Viewer (__CAM_ID__)</h1>
    <p>Câmera <code>__CAM_ID__</code> — MJPEG ~20 FPS; reconhecimento atualiza a cada 2 s. Outra câmera: <code>?camera_id=...</code></p>
    <div class="video-wrap">
      <img id="frame" alt="preview __CAM_ID__" src="" />
    </div>
    <div class="row">
      <div class="col">
        <h3>Status / cameras</h3>
        <pre id="status">Carregando…</pre>
      </div>
      <div class="col">
        <h3>Current matches (per face)</h3>
        <pre id="matches">Carregando…</pre>
      </div>
      <div class="col">
        <h3>Integrações (5 projetos)</h3>
        <pre id="integrations">Carregando…</pre>
      </div>
    </div>
    <script>
      const base = window.location.origin;
      const CAM_ID = '__CAM_ID__';
      (function () {
        const img = document.getElementById('frame');
        img.src = base + '/debug/mjpeg?camera_id=' + encodeURIComponent(CAM_ID) + '&overlay=1&fps=20';
      })();

      function resumoCamera(cam) {
        if (!cam) return 'Câmera \"' + CAM_ID + '\" não encontrada. Verifique config.yaml (enabled: true) e reinicie o servidor.';
        const conectado = cam.is_connected ? 'SIM' : 'NÃO';
        const faces = cam.faces_detected_last ?? '-';
        let linhas = [];
        linhas.push(`Câmera: ${cam.camera_id}  |  Sala: ${cam.room_id}`);
        linhas.push(`Conectada ao PC: ${conectado}`);
        linhas.push(`Rostos detectados neste instante: ${faces}`);
        const raw = cam.last_presence_match;
        let lista = [];
        if (raw) {
          if (Array.isArray(raw)) lista = raw;
          else lista = [raw];
        }
        if (!lista.length) {
          linhas.push('');
          linhas.push('Último reconhecimento: nenhum aluno reconhecido ainda.');
        } else {
          linhas.push('');
          linhas.push('Último(s) aluno(s) reconhecido(s):');
          lista.forEach(m => {
            const sid = m.student_id || 'UNKNOWN';
            const nome = m.full_name || sid;
            const conf = m.confidence != null ? (Number(m.confidence) * 100).toFixed(1) + '%' : '-';
            const estado = sid === 'UNKNOWN' ? 'DESCONHECIDO' : 'RECONHECIDO';
            linhas.push(`  - ${nome} (${sid})  →  ${estado} com confiança ${conf}`);
          });
        }
        return linhas.join('\\n');
      }

      function resumoMatches(matches) {
        if (!matches.length) {
          return 'Nenhuma face visível para a câmera neste exato momento.\\nSe há pessoas na sala, aproxime-as um pouco ou verifique o enquadramento.';
        }
        const TH_ON = __INJECT_TH_ON__;
        const MARGIN_MIN = __INJECT_MARGIN_MIN__;
        return matches.map(m => {
          const sid = m.student_id || 'UNKNOWN';
          const label = m.label || sid;
          const score = m.confidence != null ? (Number(m.confidence) * 100).toFixed(1) + '%' : '-';
          const top2 = m.top2_score != null ? (Number(m.top2_score) * 100).toFixed(1) + '%' : '-';
          const marginVal = m.margin != null ? m.margin.toFixed(3) : '-';
          const confN = m.confidence != null ? Number(m.confidence) : 0;
          const marginOk = (m.margin == null) || (m.margin >= MARGIN_MIN);
          let nivel = 'desconhecido';
          if (!m.unknown && m.confidence != null) {
            if (confN >= TH_ON && marginOk) {
              nivel = 'seguro';
            } else if (confN >= TH_ON && !marginOk) {
              nivel = 'margem';
            } else {
              nivel = 'provável';
            }
          }
          let interpretacao;
          if (nivel === 'seguro') {
            interpretacao = 'Aluno reconhecido com segurança (confiança e margem ok).';
          } else if (nivel === 'margem') {
            interpretacao = 'Confiança alta, mas o 2º candidato está próximo (margin baixo). Multi-template ou cadastro mais nítido reduz troca entre pessoas.';
          } else if (sid === 'UNKNOWN') {
            interpretacao = 'Rosto DESCONHECIDO (não cadastrado).';
          } else {
            interpretacao = 'Confiança abaixo do limiar de exibição segura (histerese) — pode estabilizar no próximo ciclo de presença.';
          }
          const eng = m.engagement_label
            ? `  - Engajamento (RTCMS+ER): ${m.engagement_label} [${m.engagement_state || '-'}]`
            : '  - Engajamento: aguardando ciclo (~5s) — roda a cada 5s no vídeo';
          return [
            `Face ${m.track_id}: ${label} (${sid})`,
            `  - Confiança do modelo: ${score}`,
            `  - Diferença p/ segundo melhor: ${top2} (margin=${marginVal}; mín. ${MARGIN_MIN})`,
            eng,
            `  - Interpretação: ${interpretacao}`,
          ].join('\\n');
        }).join('\\n\\n');
      }

      function resumoIntegrations(data) {
        if (!data || data.status !== 'ok') return 'Integrações: dados indisponíveis.';
        const b = data.backends || {};
        const att = data.attendance_today || {};
        const eng = data.engagement_summary || {};
        const lw = data.last_engagement_window_event || {};
        const lines = [];
        lines.push('=== Backends ativos ===');
        lines.push(`Detector: ${b.detector || '-'}  |  Embedder: ${b.embedder || '-'}`);
        lines.push(`Engajamento: ${b.engagement_backend || '-'}  (${b.engagement_model_version || '-'})`);
        lines.push(`Modelo emoção TF: ${b.emotion_model_available ? 'SIM' : 'NÃO (usa heurística)'}`);
        lines.push('');
        lines.push('=== Presença hoje (AI-Based-Student) ===');
        lines.push(`Check-ins: ${att.total_checkins ?? 0}  |  Alunos únicos: ${att.unique_students ?? 0}`);
        lines.push('');
        lines.push('=== Janela engajamento (agregado) ===');
        lines.push(`Média índice: ${eng.engagement_index_mean ?? '-'}  |  Rostos médios: ${eng.faces_detected_mean ?? '-'}`);
        if (lw.engagement_index_avg != null) {
          lines.push(`Última janela: índice ${lw.engagement_index_avg}, atividade ${lw.activity_level || '-'}, modelo ${lw.model_version || '-'}`);
        } else {
          lines.push('Última janela: ainda não gerada (aguarde ~10s com rosto visível)');
        }
        lines.push('');
        lines.push('=== APIs ===');
        lines.push((data.api_links && data.api_links.attendance_report) || '/reports/attendance/today');
        lines.push((data.api_links && data.api_links.engagement_report) || '/reports/engagement/summary');
        return lines.join('\\n');
      }

      function refreshOverlay() {
        Promise.all([
          fetch(base + '/cameras').then(r => r.json()).catch(() => ({ cameras: [] })),
          fetch(base + '/debug/overlay_matches?camera_id=' + encodeURIComponent(CAM_ID)).then(r => r.json()).catch(() => ({ current_matches: [] }))
        ]).then(([cams, overlay]) => {
          const cam = (cams.cameras || []).find(c => c.camera_id === CAM_ID);
          document.getElementById('status').textContent = resumoCamera(cam);
          document.getElementById('matches').textContent = resumoMatches(overlay.current_matches || []);
        });
      }

      function refreshIntegrations() {
        fetch(base + '/debug/integrations_status?camera_id=' + encodeURIComponent(CAM_ID))
          .then(r => r.json())
          .catch(() => ({}))
          .then(integ => {
            const integEl = document.getElementById('integrations');
            if (integEl) integEl.textContent = resumoIntegrations(integ);
          });
      }

      setInterval(refreshOverlay, 1000);
      setInterval(refreshIntegrations, 5000);
      refreshOverlay();
      refreshIntegrations();
    </script>
  </body>
</html>"""
    html = (
        html.replace("__INJECT_TH_ON__", str(th_on))
        .replace("__INJECT_MARGIN_MIN__", str(margin_min))
        .replace("__CAM_ID__", cam_id)
    )
    return HTMLResponse(html)


@app.get("/debug/enroll", response_class=HTMLResponse)
async def debug_enroll_viewer(
    camera_id: Optional[str] = Query(None, description="ID da câmera (ex: cam-vip-5440-01)"),
):
    """
    Tela de cadastro assistido:
    - mostra câmera ao vivo
    - valida qualidade do cadastro (preview)
    - cadastra aluno somente quando qualidade estiver ok
    """
    settings = get_settings()
    if not getattr(settings, "enable_debug_ui", False):
        raise HTTPException(status_code=404, detail="Debug UI disabled (ENABLE_DEBUG_UI=1)")

    cam_id = _default_debug_camera_id(camera_id)
    enroll_frames = int(getattr(settings, "enroll_num_frames", 20))
    enroll_used = int(getattr(settings, "enroll_frames_used", 12))
    enroll_duration = float(getattr(settings, "enroll_capture_duration", 5.0))

    html = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Cadastro Assistido (Enroll)</title>
    <style>
      body { font-family: system-ui, sans-serif; background: #111827; color: #e5e7eb; margin: 0; padding: 12px; }
      h1 { font-size: 18px; margin: 0 0 8px; }
      .video-wrap { width: 100%; max-width: 1280px; margin: 0 0 12px; }
      #frame { width: 100%; height: auto; display: block; border: 1px solid #374151; background: #000; border-radius: 6px; }
      .row { display: flex; gap: 12px; margin-top: 10px; flex-wrap: wrap; }
      .card { background: #0b1220; border: 1px solid #1f2937; border-radius: 8px; padding: 10px; flex: 1 1 320px; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
      label { font-size: 12px; color: #cbd5e1; }
      input { width: 100%; box-sizing: border-box; background: #020617; color: #e5e7eb; border: 1px solid #334155; border-radius: 6px; padding: 8px; }
      button { background: #0ea5e9; color: #fff; border: 0; padding: 8px 10px; border-radius: 6px; cursor: pointer; font-weight: 600; }
      button.secondary { background: #334155; }
      button.ok { background: #16a34a; }
      .actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
      pre { background: #020617; padding: 8px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
      .small { font-size: 12px; color: #93c5fd; }
    </style>
  </head>
  <body>
    <h1>Cadastro Assistido de Aluno</h1>
    <p class="small">Fluxo: 1) Siga os passos abaixo na câmera 2) Validar qualidade 3) Cadastrar. Para <strong>mais de um template</strong> (lado, óculos, máscara), use o <strong>mesmo student_id</strong> e marque o checkbox antes de cadastrar de novo.</p>
    <div class="video-wrap">
      <img id="frame" alt="preview câmera" />
    </div>

    <div class="row">
      <div class="card" style="flex:1 1 100%;max-width:100%;">
        <h3>Passos visuais (recomendado — multi-template)</h3>
        <ol style="margin:0;padding-left:1.25rem;line-height:1.55;font-size:13px;color:#cbd5e1;">
          <li><strong>Frente</strong> — olhos na câmera, rosto centralizado (cadastro principal).</li>
          <li><strong>Leve à esquerda</strong> (~20–30°) — mesmo aluno; marque <em>Adicionar template</em> → Validar → Cadastrar.</li>
          <li><strong>Leve à direita</strong> — idem com checkbox marcado.</li>
          <li><strong>Com óculos</strong> (se usa na escola) — idem, checkbox marcado.</li>
          <li><strong>Com máscara</strong> (se aplicável) — idem, checkbox marcado.</li>
        </ol>
        <p class="small" style="margin-top:8px;">Checkbox <strong>desmarcado</strong> = apaga templates antigos desse aluno e grava só este. <strong>Marcado</strong> = mantém os anteriores e <strong>soma mais um vetor</strong> (até o limite em config.yaml → max_templates_per_student).</p>
      </div>
    </div>

    <div class="row">
      <div class="card">
        <h3>Dados do aluno</h3>
        <div class="grid">
          <div>
            <label>student_id</label>
            <input id="student_id" placeholder="p01" />
          </div>
          <div>
            <label>Nome completo</label>
            <input id="full_name" placeholder="Emerson Lima" />
          </div>
          <div>
            <label>camera_id</label>
            <input id="camera_id" value="__CAM_ID__" />
          </div>
          <div>
            <label>Duração (seg)</label>
            <input id="capture_duration" value="__ENROLL_DURATION__" />
          </div>
          <div>
            <label>Frames a capturar</label>
            <input id="num_frames" value="__ENROLL_FRAMES__" />
          </div>
          <div>
            <label>Frames usados</label>
            <input id="frames_used" value="__ENROLL_USED__" />
          </div>
          <div>
            <label>Min quality score</label>
            <input id="min_quality_score" value="0.45" />
          </div>
          <div>
            <label>Min good frames</label>
            <input id="min_good_frames" value="3" />
          </div>
        </div>
        <div style="margin-top:8px;">
          <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;">
            <input id="append_template" type="checkbox" style="width:auto;margin-top:2px;" />
            <span><strong>Adicionar template</strong> (multi-template): mesmo <code>student_id</code> e nome; <strong>não apaga</strong> o cadastro anterior — acrescenta vista (lado/óculos/máscara). Primeiro cadastro do aluno: deixe <strong>desmarcado</strong>.</span>
          </label>
        </div>
        <div class="actions">
          <button class="secondary" onclick="validar()">Validar qualidade</button>
          <button class="ok" onclick="cadastrar()">Cadastrar aluno</button>
        </div>
      </div>

      <div class="card">
        <h3>Resultado</h3>
        <pre id="resultado">Aguardando ação...</pre>
      </div>
    </div>

    <script>
      const base = window.location.origin;
      let ultimoPreviewOk = false;

      function refreshFrame() {
        const cam = document.getElementById('camera_id').value || '__CAM_ID__';
        document.getElementById('frame').src = base + '/debug/mjpeg?camera_id=' + encodeURIComponent(cam) + '&overlay=0&fps=20&v=3';
      }

      function payloadBase() {
        return {
          student_id: document.getElementById('student_id').value.trim(),
          full_name: document.getElementById('full_name').value.trim() || null,
          camera_id: document.getElementById('camera_id').value.trim() || 'cam-web',
          capture_duration: Number(document.getElementById('capture_duration').value || '5'),
          num_frames: Number(document.getElementById('num_frames').value || '15'),
          frames_used: Number(document.getElementById('frames_used').value || '10'),
          min_quality_score: Number(document.getElementById('min_quality_score').value || '0.45'),
          min_good_frames: Number(document.getElementById('min_good_frames').value || '3'),
          append_template: !!document.getElementById('append_template').checked
        };
      }

      function validarCampos(body) {
        if (!body.student_id) return 'Informe student_id.';
        if (!body.camera_id) return 'Informe camera_id.';
        return null;
      }

      async function validar() {
        const body = payloadBase();
        const erro = validarCampos(body);
        if (erro) {
          document.getElementById('resultado').textContent = erro;
          return;
        }
        document.getElementById('resultado').textContent = 'Validando qualidade...';
        ultimoPreviewOk = false;
        try {
          const r = await fetch(base + '/enroll/webcam/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
          });
          const data = await r.json();
          ultimoPreviewOk = !!data.quality_ok;
          const linhas = [
            'Preview de qualidade',
            '-------------------',
            `status: ${data.status}`,
            `quality_ok: ${data.quality_ok}`,
            `quality_score: ${data.quality_score}`,
            `quality_avg: ${data.quality_avg}`,
            `quality_label: ${data.quality_label}`,
            `frames_captured: ${data.frames_captured}`,
            `good/fair/poor: ${data.good_frames}/${data.fair_frames}/${data.poor_frames}`,
            '',
            `recomendação: ${data.quality_recommendation || '-'}`,
            '',
            JSON.stringify(data, null, 2)
          ];
          document.getElementById('resultado').textContent = linhas.join('\\n');
        } catch (e) {
          document.getElementById('resultado').textContent = 'Erro na validação: ' + e;
        }
      }

      async function cadastrar() {
        const body = payloadBase();
        const erro = validarCampos(body);
        if (erro) {
          document.getElementById('resultado').textContent = erro;
          return;
        }
        document.getElementById('resultado').textContent = 'Cadastrando...';
        try {
          const r = await fetch(base + '/enroll/webcam', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
          });
          const data = await r.json();
          if (!r.ok) {
            document.getElementById('resultado').textContent = 'Cadastro falhou:\\n' + JSON.stringify(data, null, 2);
            return;
          }
          const aviso = ultimoPreviewOk ? 'Cadastro concluído (preview ok).' : 'Cadastro concluído. Dica: rode preview antes para validar qualidade.';
          document.getElementById('resultado').textContent =
            aviso + '\\n\\n' + JSON.stringify(data, null, 2);
        } catch (e) {
          document.getElementById('resultado').textContent = 'Erro no cadastro: ' + e;
        }
      }

      const urlCam = new URLSearchParams(window.location.search).get('camera_id');
      if (urlCam) document.getElementById('camera_id').value = urlCam;
      refreshFrame();
      document.getElementById('camera_id').addEventListener('change', refreshFrame);
    </script>
  </body>
</html>"""
    html = (
        html.replace("__CAM_ID__", cam_id)
        .replace("__ENROLL_FRAMES__", str(enroll_frames))
        .replace("__ENROLL_USED__", str(enroll_used))
        .replace("__ENROLL_DURATION__", str(enroll_duration))
    )
    return HTMLResponse(html)


@app.post("/mock/ingest")
async def mock_ingest(payload: dict):
    """Endpoint mock para testar sync sem Supabase."""
    # Validar estrutura mínima
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")
    
    # Se for lista, processar cada item
    if isinstance(payload, list):
        events = payload
    else:
        events = [payload]
    
    processed = []
    for event in events:
        if not isinstance(event, dict):
            continue
        
        event_id = event.get("event_id")
        event_type = event.get("event_type")
        
        if not event_id or not event_type:
            logger.warning("mock_ingest_invalid", event=event)
            continue
        
        logger.info("mock_ingest_received", event_id=event_id, event_type=event_type)
        processed.append(event_id)
    
    return {
        "status": "ok",
        "message": f"Processed {len(processed)} events",
        "event_ids": processed
    }


@app.get("/")
async def root():
    """Root — redireciona ao painel unificado quando disponível."""
    dash = Path(__file__).parent / "static" / "dashboard.html"
    if dash.exists():
        return RedirectResponse(url="/dashboard", status_code=302)
    static_file = Path(__file__).parent.parent / "app" / "static" / "index.html"
    if static_file.exists():
        return FileResponse(str(static_file))
    return {
        "name": "Dulino Edge Vision",
        "version": __version__,
        "status": "running",
        "endpoints": {
            "dashboard": "/dashboard",
            "health": "/health",
            "stats": "/stats",
            "cameras": "/cameras",
            "enroll": "/enroll (POST)",
            "module_dod": "/module/dod",
        }
    }
