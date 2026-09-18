"""API v1 — live, sessions, review, system, demo control, WebSocket."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.auth import require_api_token
from app.config import get_settings
from app.runtime_mode import DISCLAIMER, DEMO_BANNER, get_runtime_mode, is_demo
from app.labels_pt import (
    attention_label_pt,
    attention_level_from_index,
    climate_label_pt,
    labels_catalog,
)
from app.services.live_session import dashboard_track_view, get_live_session
from app.pipeline.analytics_track import filter_displayable_tracks

router = APIRouter(prefix="/api/v1", tags=["v1"])

_live_state: Dict[str, Any] = {
    "updated_at": 0.0,
    "tracks": [],
    "bindings": [],
    "signals": [],
    "latencies_ms": {},
    "phones": [],
    "observation_quality": {},
    "module_modes": {},
}


def update_live_debug_state(**kwargs) -> None:
    _live_state.update(kwargs)
    _live_state["updated_at"] = time.time()
    cc = kwargs.get("classroom_counts") or _live_state.get("classroom_counts") or {}
    if cc.get("climate_distribution"):
        _live_state["climate_distribution"] = cc["climate_distribution"]
    for k in ("embeddings", "rtsp_url", "frame", "credentials"):
        _live_state.pop(k, None)
    if not is_demo():
        get_live_session().ingest_live_state(_live_state)


def _demo_snap() -> Dict[str, Any]:
    from app.demo.engine import get_demo_engine

    return get_demo_engine().snapshot()


def _enrich(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = get_runtime_mode().value
    payload = dict(payload)
    payload["runtime_mode"] = mode
    payload["is_simulated"] = mode == "demo"
    payload["disclaimer"] = DISCLAIMER
    if mode == "demo":
        payload["banner"] = DEMO_BANNER
    return payload


class ReviewPatch(BaseModel):
    status: str
    notes: Optional[str] = None


class DemoControlBody(BaseModel):
    playing: Optional[bool] = None
    speed: Optional[float] = None
    reset: bool = False


def _current_lesson_context() -> Optional[Dict[str, Any]]:
    try:
        from app.services.lesson_context import read_session_context

        return read_session_context(get_live_session().session_id)
    except Exception:
        return None


class LessonCacheBody(BaseModel):
    occurrences: List[Dict[str, Any]] = Field(default_factory=list)


class StartWithContextBody(BaseModel):
    lesson_occurrence_id: str
    organization_id: Optional[str] = None
    school_id: Optional[str] = None
    class_group_id: Optional[str] = None
    subject_id: Optional[str] = None
    teacher_profile_id: Optional[str] = None
    room_id: Optional[str] = None
    class_group_name: Optional[str] = None
    subject_name: Optional[str] = None
    teacher_name: Optional[str] = None
    room_name: Optional[str] = None
    title: Optional[str] = None
    scheduled_start_at: Optional[str] = None
    scheduled_duration_minutes: Optional[int] = None
    external_lesson_id: Optional[str] = None
    block_group_id: Optional[str] = None
    roster: List[Dict[str, Any]] = Field(default_factory=list)
    require_full_context: bool = False


def _client_is_localhost(request: Request) -> bool:
    client = request.client.host if request.client else ""
    return client in ("127.0.0.1", "::1", "localhost", "testclient")


@router.get("/live/status")
async def live_status(_: None = Depends(require_api_token)):
    settings = get_settings()
    if is_demo():
        snap = _demo_snap()
        return _enrich(
            {
                "ok": True,
                "device_id": settings.device_id,
                "updated_at": snap["updated_at"],
                "modules": snap["module_modes"],
                "session": snap["session"],
                "kpis": snap["kpis"],
                "camera_status": "demo_source",
            }
        )
    return _enrich(
        {
            "ok": True,
            "device_id": settings.device_id,
            "updated_at": _live_state.get("updated_at"),
            "modules": {
                "expression": getattr(settings, "module_expression_mode", "disabled"),
                "face_landmarks": getattr(settings, "module_face_landmarks_mode", "disabled"),
                "person_tracking": getattr(settings, "module_person_tracking_mode", "disabled"),
                "phone": getattr(settings, "module_phone_mode", "disabled"),
                "pose": getattr(settings, "module_pose_mode", "disabled"),
                "temporal_fusion": getattr(settings, "module_temporal_fusion_mode", "disabled"),
                "lxp": getattr(settings, "module_lxp_mode", "disabled"),
            },
            "camera_status": "rtsp_or_offline",
            "session": get_live_session().session_meta(),
            "lesson_context": _current_lesson_context(),
            "kpis": {
                "visible": _live_state.get("visible_people"),
                "present": _live_state.get("recognized_people"),
                "observable": _live_state.get("observable_people"),
                "inconclusive": _live_state.get("inconclusive_people"),
                "attention_index": _live_state.get("attention_index"),
                "climate": _live_state.get("apparent_climate"),
                "active_events": len(_live_state.get("live_event_buffer") or []),
            },
        }
    )


@router.get("/live/classroom-summary")
async def classroom_summary(_: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich(
            {
                "visible_people": snap["kpis"]["visible"],
                "recognized_people": snap["kpis"]["present"],
                "observable_people": snap["kpis"]["observable"],
                "inconclusive_people": snap["kpis"]["inconclusive"],
                "attention_index": snap["kpis"]["attention_index"],
                "apparent_climate": snap["kpis"]["climate"],
                "phones": snap["phones"],
                "active_behavioral_signals": snap["kpis"]["active_events"],
                "updated_at": snap["updated_at"],
            }
        )
    # Runtime real: usa snapshot publicado pelo orchestrator
    counts = {
        "visible_people": _live_state.get("visible_people"),
        "recognized_people": _live_state.get("recognized_people"),
        "observable_people": _live_state.get("observable_people"),
        "inconclusive_people": _live_state.get("inconclusive_people"),
        "attention_index": _live_state.get("attention_index"),
        "apparent_climate": _live_state.get("apparent_climate"),
        "climate_distribution": _live_state.get("climate_distribution"),
        "phones": _live_state.get("phones", []),
        "active_behavioral_signals": sum(
            1
            for e in (_live_state.get("live_event_buffer") or [])
            if e.get("lifecycle") in ("opened", "updated")
        ),
        "updated_at": _live_state.get("updated_at"),
        "tracks": [dashboard_track_view(t) for t in filter_displayable_tracks(_live_state.get("tracks") or [])],
    }
    # null quando sem dado (não forçar 0)
    for k in ("observable_people", "inconclusive_people", "attention_index", "apparent_climate"):
        if k not in _live_state:
            counts[k] = None
    attn_index = counts.get("attention_index")
    attn_level = attention_level_from_index(attn_index)
    climate = counts.get("apparent_climate")
    ls = get_live_session()
    agg = ls.aggregate(_live_state)
    counts["attention_level"] = attn_level
    counts["attention_label_pt"] = attention_label_pt(attn_level)
    counts["climate_label_pt"] = climate_label_pt(climate)
    counts["class_summary"] = agg.get("class_summary")
    return _enrich(counts)


@router.get("/labels")
async def api_labels(_: None = Depends(require_api_token)):
    return _enrich(labels_catalog())


@router.get("/live/tracks")
async def live_tracks(_: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich(
            {
                "tracks": snap["tracks"],
                "bindings": snap["bindings"],
                "updated_at": snap["updated_at"],
            }
        )
    return _enrich(
        {
            "tracks": [dashboard_track_view(t) for t in filter_displayable_tracks(_live_state.get("tracks") or [])],
            "bindings": _live_state.get("bindings", []),
            "updated_at": _live_state.get("updated_at"),
            "latencies_ms": _live_state.get("latencies_ms", {}),
            "observation_quality": _live_state.get("observation_quality", {}),
            "classroom_counts": _live_state.get("classroom_counts", {}),
        }
    )


@router.get("/live/debug-snapshot")
async def debug_snapshot(request: Request, _: None = Depends(require_api_token)):
    settings = get_settings()
    allow_remote = getattr(settings, "debug_vision_allow_remote", False)
    if not allow_remote and not _client_is_localhost(request):
        return JSONResponse({"detail": "debug vision restricted to localhost"}, status_code=403)
    if is_demo():
        snap = _demo_snap()
        return _enrich(
            {
                **{k: snap[k] for k in snap if k not in ("embeddings",)},
                "frame_source": "DemoFrameSource",
                "security": {
                    "localhost_only": not allow_remote,
                    "stores_frames": False,
                    "exposes_embeddings": False,
                    "exposes_rtsp": False,
                },
            }
        )
    safe = {k: v for k, v in _live_state.items() if k not in ("embeddings", "rtsp_url", "frame", "credentials")}
    safe["security"] = {
        "localhost_only": not allow_remote,
        "stores_frames": False,
        "exposes_embeddings": False,
        "exposes_rtsp": False,
    }
    return _enrich(safe)


@router.get("/sessions")
async def list_sessions(_: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich({"sessions": [snap["session"]]})
    return _enrich({"sessions": [get_live_session().session_meta()]})


@router.get("/sessions/current-context")
async def sessions_current_context(_: None = Depends(require_api_token)):
    from app.services.lesson_context import current_context_payload

    return _enrich(current_context_payload())


@router.post("/lessons/cache")
async def lessons_cache_push(body: LessonCacheBody, _: None = Depends(require_api_token)):
    """Browser push: cache das aulas do dia no Edge (offline-first)."""
    from app.services.lesson_context import save_day_cache

    saved = save_day_cache(list(body.occurrences or []))
    return _enrich({"ok": True, "cached_at": saved.get("cached_at"), "count": len(saved.get("occurrences") or [])})


@router.get("/lessons/cache")
async def lessons_cache_get(_: None = Depends(require_api_token)):
    from app.services.lesson_context import load_day_cache

    return _enrich(load_day_cache())


@router.post("/sessions/start-with-context")
async def sessions_start_with_context(body: StartWithContextBody, _: None = Depends(require_api_token)):
    from app.services.lesson_context import start_session_with_context

    result = start_session_with_context(body.model_dump())
    status = 200 if result.get("ok") else (409 if result.get("code") == "conflict_active_session" else 400)
    return JSONResponse(_enrich(result), status_code=status)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, _: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        if snap["session"]["session_id"] != session_id:
            return JSONResponse({"detail": "session not found"}, status_code=404)
        return _enrich(snap["session"])
    ls = get_live_session()
    if ls.session_id != session_id:
        return JSONResponse({"detail": "session not found"}, status_code=404)
    return _enrich(ls.session_meta())


@router.get("/sessions/{session_id}/summary")
async def session_summary(session_id: str, _: None = Depends(require_api_token)):
    if is_demo():
        from app.demo.engine import get_demo_engine

        return _enrich(get_demo_engine().report())
    ls = get_live_session()
    if ls.session_id != session_id:
        return _enrich({"session_id": session_id, "summary": None})
    return _enrich(ls.build_report(_live_state))


@router.get("/sessions/{session_id}/timeline")
async def session_timeline(session_id: str, _: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich({"session_id": session_id, "timeline": snap["timeline"]})
    ls = get_live_session()
    return _enrich({"session_id": session_id, "timeline": ls.timeline[-80:]})


@router.get("/sessions/{session_id}/students")
async def session_students(session_id: str, _: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich({"session_id": session_id, "students": snap["attendance"]})
    return _enrich({"session_id": session_id, "students": get_live_session().students_list()})


@router.get("/sessions/{session_id}/engagement")
async def session_engagement(session_id: str, _: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich(
            {
                "session_id": session_id,
                "attention_index": snap["kpis"]["attention_index"],
                "tracks": [
                    {
                        "student_id": t["student_id"],
                        "visual_attention_score": t["visual_attention_score"],
                        "state": t["attention_state"],
                    }
                    for t in snap["tracks"]
                ],
            }
        )
    return _enrich({"session_id": session_id, "engagement": []})


@router.get("/sessions/{session_id}/climate")
async def session_climate(session_id: str, _: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich({"session_id": session_id, "dominant_state": snap["kpis"]["climate"]})
    return _enrich(
        {
            "session_id": session_id,
            "dominant_state": _live_state.get("apparent_climate"),
            "climate_distribution": _live_state.get("climate_distribution"),
            "timeline": get_live_session().climate_samples,
        }
    )


@router.get("/sessions/{session_id}/behavioral-events")
async def session_behavioral(session_id: str, _: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich({"session_id": session_id, "events": snap["events"]})
    evs = list(get_live_session().events_seen.values())
    return _enrich({"session_id": session_id, "events": evs[-100:]})


@router.get("/review/events")
async def review_events(
    status: Optional[str] = Query(default=None),
    _: None = Depends(require_api_token),
):
    if is_demo():
        snap = _demo_snap()
        events = snap["events"]
        if status:
            events = [e for e in events if e.get("review_status") == status]
        return _enrich({"events": events})
    from app.db.init_db import get_session, close_session
    from app.db.repo import BehavioralEventRepository

    session = get_session()
    try:
        rows = BehavioralEventRepository(session).list_events(status=status, limit=100)
        return _enrich(
            {
                "events": [
                    {
                        "event_id": r.event_id,
                        "event_type": r.event_type,
                        "status": r.status,
                        "confidence": r.confidence,
                    }
                    for r in rows
                ]
            }
        )
    finally:
        close_session(session)


@router.get("/review/events/{event_id}")
async def review_event_get(event_id: str, _: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        for e in snap["events"]:
            if e["event_id"] == event_id:
                return _enrich(e)
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse({"detail": "not found"}, status_code=404)


@router.patch("/review/events/{event_id}")
async def review_patch(event_id: str, body: ReviewPatch, _: None = Depends(require_api_token)):
    if body.status not in ("confirmed", "rejected", "inconclusive", "pending"):
        return JSONResponse({"detail": "invalid status"}, status_code=400)
    if is_demo():
        from app.demo.engine import get_demo_engine

        ev = get_demo_engine().review_event(event_id, body.status, body.notes or "")
        if not ev:
            return JSONResponse({"detail": "not found"}, status_code=404)
        await live_hub.broadcast({"type": "review_queue_update", "payload": {"event_id": event_id, "status": body.status}})
        return _enrich({"ok": True, "event": ev})
    from app.db.init_db import get_session, close_session
    from app.db.repo import BehavioralEventRepository

    session = get_session()
    try:
        ok = BehavioralEventRepository(session).review(event_id, body.status, reviewed_by="api_v1")
        return _enrich({"ok": bool(ok), "event_id": event_id, "status": body.status})
    finally:
        close_session(session)


@router.get("/system/health")
async def system_health(_: None = Depends(require_api_token)):
    return _enrich({"status": "ok", "ts": time.time()})


@router.get("/system/models")
async def system_models(_: None = Depends(require_api_token)):
    settings = get_settings()
    return _enrich(
        {
            "detector": getattr(settings, "vision_detector_backend", "yunet"),
            "embedder": getattr(settings, "vision_embedder_backend", "facenet"),
            "expression_provider": "demo_mock" if is_demo() else getattr(settings, "expression_provider", "none"),
            "note": "No secrets or RTSP URLs",
        }
    )


@router.get("/system/performance")
async def system_performance(_: None = Depends(require_api_token)):
    if is_demo():
        snap = _demo_snap()
        return _enrich({"performance": snap["performance"], "latencies_ms": snap["latencies_ms"]})
    return _enrich({"performance": {}, "latencies_ms": _live_state.get("latencies_ms", {})})


@router.get("/system/configuration")
async def system_configuration(_: None = Depends(require_api_token)):
    settings = get_settings()
    return _enrich(
        {
            "device_id": settings.device_id,
            "school_id": settings.school_id,
            "runtime_mode": get_runtime_mode().value,
            "rule_engine_version": getattr(settings, "rule_engine_version", "rules-v0-baseline"),
            "threshold_profile": getattr(settings, "threshold_profile", "presence-yaml-2026-07-23"),
            "camera_calibration_version": getattr(
                settings, "camera_calibration_version", "cam-vip-5440-01-uncalibrated"
            ),
        }
    )


@router.post("/demo/control")
async def demo_control(body: DemoControlBody, _: None = Depends(require_api_token)):
    if not is_demo():
        return JSONResponse({"detail": "not in demo mode"}, status_code=400)
    from app.demo.engine import get_demo_engine

    ctrl = get_demo_engine().control_update(playing=body.playing, speed=body.speed, reset=body.reset)
    return _enrich(
        {
            "playing": ctrl.playing,
            "speed": ctrl.speed,
            "t_seconds": ctrl.t_seconds,
            "session_id": ctrl.session_id,
        }
    )


@router.get("/demo/report")
async def demo_report(_: None = Depends(require_api_token)):
    if not is_demo():
        return JSONResponse({"detail": "not in demo mode"}, status_code=400)
    from app.demo.engine import get_demo_engine

    return _enrich(get_demo_engine().report())


@router.get("/demo/report.csv")
async def demo_report_csv(_: None = Depends(require_api_token)):
    if not is_demo():
        return JSONResponse({"detail": "not in demo mode"}, status_code=400)
    from app.demo.engine import get_demo_engine

    snap = get_demo_engine().snapshot()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["student_id", "full_name", "present", "attention_state", "expression", "is_simulated"])
    by_id = {t["student_id"]: t for t in snap["tracks"]}
    for a in snap["attendance"]:
        tr = by_id.get(a["student_id"], {})
        w.writerow(
            [
                a["student_id"],
                a["full_name"],
                a["present"],
                tr.get("attention_state", ""),
                tr.get("expression_window", ""),
                True,
            ]
        )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=demo_report.csv"},
    )


@router.post("/demo/lxp/flush")
async def demo_lxp_flush(_: None = Depends(require_api_token)):
    if not is_demo():
        return JSONResponse({"detail": "not in demo mode"}, status_code=400)
    from app.demo.engine import get_demo_engine

    return _enrich(get_demo_engine().process_lxp_outbox())


class LiveHub:
    def __init__(self):
        self.clients: Set[WebSocket] = set()
        self._task: Optional[asyncio.Task] = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, message: Dict[str, Any]):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def demo_ticker(self):
        while True:
            await asyncio.sleep(1.0)
            if not is_demo() or not self.clients:
                continue
            try:
                snap = _demo_snap()
                await self.broadcast(
                    _enrich(
                        {
                            "type": "classroom_summary",
                            "payload": snap["kpis"],
                            "is_simulated": True,
                        }
                    )
                )
                await self.broadcast(
                    _enrich(
                        {
                            "type": "live_tracks",
                            "payload": {"tracks": snap["tracks"]},
                            "is_simulated": True,
                        }
                    )
                )
                await self.broadcast(
                    _enrich({"type": "heartbeat", "ts": time.time(), "is_simulated": True})
                )
            except Exception:
                continue

    async def rtsp_ticker(self):
        """Broadcast live analytics no runtime real (sem frames/embeddings/credenciais)."""
        while True:
            await asyncio.sleep(1.0)
            if is_demo() or not self.clients:
                continue
            try:
                from app.main import orchestrator

                orch = orchestrator
                if orch is None:
                    await self.broadcast(
                        _enrich(
                            {
                                "type": "heartbeat",
                                "ts": time.time(),
                                "is_simulated": False,
                            }
                        )
                    )
                    continue

                status = orch.get_status() if hasattr(orch, "get_status") else {}
                cams = (status or {}).get("cameras") or {}
                cam_id = next(iter(cams.keys()), "cam-web")
                tracks = list(getattr(orch, "_analytics_tracks", {}).get(cam_id) or [])
                # sanitize
                safe_tracks = []
                for t in tracks:
                    safe_tracks.append(
                        {
                            k: v
                            for k, v in t.items()
                            if k
                            not in (
                                "embedding",
                                "embeddings",
                                "frame",
                                "rtsp_url",
                                "credentials",
                            )
                        }
                    )
                counts = getattr(orch, "_analytics_counts", {}).get(cam_id) or {}
                cam_st = cams.get(cam_id) or {}
                await self.broadcast(
                    _enrich(
                        {
                            "type": "camera_status",
                            "payload": {
                                "camera_id": cam_id,
                                "connected": bool(cam_st.get("connected") or cam_st.get("is_connected")),
                                "faces_detected_last": cam_st.get("faces_detected_last"),
                            },
                            "is_simulated": False,
                        }
                    )
                )
                await self.broadcast(
                    _enrich(
                        {
                            "type": "live_tracks",
                            "payload": {"camera_id": cam_id, "tracks": safe_tracks},
                            "is_simulated": False,
                        }
                    )
                )
                await self.broadcast(
                    _enrich(
                        {
                            "type": "classroom_summary",
                            "payload": {
                                "visible_people": counts.get("visible"),
                                "recognized_people": counts.get("present"),
                                "observable_people": counts.get("observable"),
                                "inconclusive_people": counts.get("inconclusive"),
                                "attention_index": counts.get("attention_index"),
                                "apparent_climate": counts.get("climate"),
                            },
                            "is_simulated": False,
                        }
                    )
                )
                if counts.get("attention_index") is not None:
                    await self.broadcast(
                        _enrich(
                            {
                                "type": "engagement_update",
                                "payload": {"attention_index": counts.get("attention_index")},
                                "is_simulated": False,
                            }
                        )
                    )
                if counts.get("climate") is not None:
                    await self.broadcast(
                        _enrich(
                            {
                                "type": "climate_update",
                                "payload": {"apparent_climate": counts.get("climate")},
                                "is_simulated": False,
                            }
                        )
                    )
                # drain engine events
                eng = getattr(orch, "_analytics_engine", None)
                if eng and hasattr(eng, "drain_ws_events"):
                    for ev in eng.drain_ws_events():
                        await self.broadcast(_enrich(ev))
                # latencies aggregate
                lat = {}
                for t in safe_tracks:
                    for k, v in (t.get("latencies_ms") or {}).items():
                        if isinstance(v, (int, float)):
                            lat.setdefault(k, []).append(float(v))
                lat_avg = {k: round(sum(vs) / len(vs), 2) for k, vs in lat.items() if vs}
                await self.broadcast(
                    _enrich(
                        {
                            "type": "performance_metrics",
                            "payload": {"latencies_ms": lat_avg},
                            "is_simulated": False,
                        }
                    )
                )
                await self.broadcast(
                    _enrich({"type": "heartbeat", "ts": time.time(), "is_simulated": False})
                )
            except Exception:
                continue


live_hub = LiveHub()


# --- Validação controlada (DB isolado; não altera presença) ---


class ValidationSessionBody(BaseModel):
    operator: str = "operator"
    camera_id: str = "cam-web"
    student_id: Optional[str] = None


class ValidationStartBody(BaseModel):
    scenario_key: Optional[str] = None
    step_id: Optional[str] = None


class ValidationFinishBody(BaseModel):
    observation: Optional[str] = None
    result: Optional[str] = None  # override PASS|FAIL|INCONCLUSIVO


class ValidationPatchBody(BaseModel):
    observation: Optional[str] = None
    result: Optional[str] = None


@router.get("/validation/scenarios")
async def validation_scenarios(_: None = Depends(require_api_token)):
    from app.validation.scenarios import list_scenarios

    return _enrich({"scenarios": list_scenarios()})


@router.post("/validation/sessions")
async def validation_create_session(body: ValidationSessionBody, _: None = Depends(require_api_token)):
    from app.validation.service import get_validation_service

    svc = get_validation_service()
    sess = svc.create_session(
        operator=body.operator, camera_id=body.camera_id, student_id=body.student_id
    )
    return _enrich(sess)


@router.get("/validation/sessions")
async def validation_list_sessions(_: None = Depends(require_api_token)):
    from app.validation.service import get_validation_service

    return _enrich({"sessions": get_validation_service().list_sessions()})


@router.get("/validation/sessions/{session_id}")
async def validation_get_session(session_id: str, _: None = Depends(require_api_token)):
    from app.validation.service import get_validation_service

    try:
        return _enrich(get_validation_service().get_session(session_id))
    except KeyError:
        return JSONResponse({"detail": "session_not_found"}, status_code=404)


@router.post("/validation/sessions/{session_id}/steps/start")
async def validation_start_step(
    session_id: str, body: ValidationStartBody, _: None = Depends(require_api_token)
):
    from app.validation.service import get_validation_service

    try:
        step = get_validation_service().start_step(
            session_id, scenario_key=body.scenario_key, step_id=body.step_id
        )
        return _enrich(step)
    except KeyError:
        return JSONResponse({"detail": "step_not_found"}, status_code=404)


@router.post("/validation/sessions/{session_id}/steps/{step_id}/sample")
async def validation_sample_step(
    session_id: str, step_id: str, _: None = Depends(require_api_token)
):
    from app.validation.service import get_validation_service

    try:
        return _enrich(get_validation_service().record_sample(session_id, step_id))
    except RuntimeError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)


@router.post("/validation/sessions/{session_id}/steps/{step_id}/finish")
async def validation_finish_step(
    session_id: str,
    step_id: str,
    body: ValidationFinishBody,
    _: None = Depends(require_api_token),
):
    from app.validation.service import get_validation_service

    try:
        step = get_validation_service().finish_step(
            session_id,
            step_id,
            observation=body.observation,
            result_override=body.result,
        )
        return _enrich(step)
    except (KeyError, RuntimeError) as e:
        return JSONResponse({"detail": str(e)}, status_code=400)


@router.patch("/validation/sessions/{session_id}/steps/{step_id}")
async def validation_patch_step(
    session_id: str,
    step_id: str,
    body: ValidationPatchBody,
    _: None = Depends(require_api_token),
):
    from app.validation.service import get_validation_service

    try:
        return _enrich(
            get_validation_service().patch_step(
                session_id, step_id, observation=body.observation, result=body.result
            )
        )
    except (KeyError, ValueError) as e:
        return JSONResponse({"detail": str(e)}, status_code=400)


@router.get("/validation/sessions/{session_id}/report")
async def validation_report(session_id: str, _: None = Depends(require_api_token)):
    from app.validation.service import get_validation_service

    try:
        return _enrich(get_validation_service().build_report(session_id))
    except KeyError:
        return JSONResponse({"detail": "session_not_found"}, status_code=404)


@router.get("/validation/sessions/{session_id}/report.csv")
async def validation_report_csv(session_id: str, _: None = Depends(require_api_token)):
    from app.validation.service import get_validation_service

    try:
        csv_text = get_validation_service().report_csv(session_id)
    except KeyError:
        return JSONResponse({"detail": "session_not_found"}, status_code=404)
    return StreamingResponse(
        io.StringIO(csv_text),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="validation_{session_id}.csv"'},
    )


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    settings = get_settings()
    expected = (settings.api_auth_token or "").strip()
    if expected:
        token = websocket.query_params.get("api_token")
        if token != expected:
            await websocket.close(code=4401)
            return
    await live_hub.connect(websocket)
    try:
        await websocket.send_json(
            _enrich(
                {
                    "type": "system_status",
                    "payload": {"ok": True, "runtime_mode": get_runtime_mode().value},
                }
            )
        )
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_json(
                        {"type": "heartbeat", "ts": time.time(), "is_simulated": is_demo()}
                    )
            except asyncio.TimeoutError:
                await websocket.send_json(
                    {"type": "heartbeat", "ts": time.time(), "is_simulated": is_demo()}
                )
            except WebSocketDisconnect:
                break
    finally:
        live_hub.disconnect(websocket)
