"""API v1 + estado live para debug vision / WS."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.auth import require_api_token
from app.config import get_settings
from app.module_modes import ModuleMode, parse_module_mode

router = APIRouter(prefix="/api/v1", tags=["v1"])

# Estado em memória (sem embeddings / sem frames)
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
    # Sanitizar
    _live_state.pop("embeddings", None)
    _live_state.pop("rtsp_url", None)
    _live_state.pop("frame", None)


class ReviewPatch(BaseModel):
    status: str
    notes: Optional[str] = None


def _client_is_localhost(request: Request) -> bool:
    client = request.client.host if request.client else ""
    return client in ("127.0.0.1", "::1", "localhost")


@router.get("/live/status")
async def live_status(_: None = Depends(require_api_token)):
    settings = get_settings()
    return {
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
        "disclaimer": "Indicadores estimados a partir de sinais visuais. Não constituem diagnóstico.",
    }


@router.get("/live/tracks")
async def live_tracks(_: None = Depends(require_api_token)):
    return {
        "tracks": _live_state.get("tracks", []),
        "bindings": _live_state.get("bindings", []),
        "updated_at": _live_state.get("updated_at"),
    }


@router.get("/live/classroom-summary")
async def classroom_summary(_: None = Depends(require_api_token)):
    return {
        "visible_people": _live_state.get("visible_people", 0),
        "recognized_people": _live_state.get("recognized_people", 0),
        "observable_people": _live_state.get("observable_people", 0),
        "phones": _live_state.get("phones", []),
        "updated_at": _live_state.get("updated_at"),
        "disclaimer": "Estimativa visual observável — não diagnóstico.",
    }


@router.get("/live/debug-snapshot")
async def debug_snapshot(request: Request, _: None = Depends(require_api_token)):
    """Somente localhost por padrão (além de auth quando configurada)."""
    settings = get_settings()
    allow_remote = getattr(settings, "debug_vision_allow_remote", False)
    if not allow_remote and not _client_is_localhost(request):
        return JSONResponse({"detail": "debug vision restricted to localhost"}, status_code=403)
    # Payload sanitizado
    safe = {
        k: v
        for k, v in _live_state.items()
        if k not in ("embeddings", "rtsp_url", "frame", "credentials")
    }
    safe["security"] = {
        "localhost_only": not allow_remote,
        "stores_frames": False,
        "exposes_embeddings": False,
        "exposes_rtsp": False,
    }
    return safe


@router.get("/system/health")
async def system_health(_: None = Depends(require_api_token)):
    return {"status": "ok", "ts": time.time()}


@router.get("/system/models")
async def system_models(_: None = Depends(require_api_token)):
    settings = get_settings()
    return {
        "detector": getattr(settings, "vision_detector_backend", "yunet"),
        "embedder": getattr(settings, "vision_embedder_backend", "facenet"),
        "expression_provider": getattr(settings, "expression_provider", "none"),
        "expression_mode": getattr(settings, "module_expression_mode", "disabled"),
        "note": "No secrets or RTSP URLs",
    }


@router.get("/system/configuration")
async def system_configuration(_: None = Depends(require_api_token)):
    settings = get_settings()
    return {
        "device_id": settings.device_id,
        "school_id": settings.school_id,
        "rule_engine_version": getattr(settings, "rule_engine_version", "rules-v0-baseline"),
        "threshold_profile": getattr(settings, "threshold_profile", "presence-yaml-2026-07-23"),
        "camera_calibration_version": getattr(
            settings, "camera_calibration_version", "cam-vip-5440-01-uncalibrated"
        ),
        "modules": {
            "expression": getattr(settings, "module_expression_mode", "disabled"),
            "phone": getattr(settings, "module_phone_mode", "disabled"),
        },
    }


@router.get("/review/events")
async def review_events(_: None = Depends(require_api_token)):
    from app.db.init_db import get_session
    from app.db.repo import BehavioralEventRepository

    session = get_session()
    try:
        repo = BehavioralEventRepository(session)
        rows = repo.list_events(limit=100)
        return {
            "events": [
                {
                    "event_id": r.event_id,
                    "event_type": r.event_type,
                    "status": r.status,
                    "confidence": r.confidence,
                    "started_at": str(r.started_at),
                    "ended_at": str(r.ended_at) if r.ended_at else None,
                }
                for r in rows
            ]
        }
    finally:
        session.close()


@router.patch("/review/events/{event_id}")
async def review_patch(event_id: str, body: ReviewPatch, _: None = Depends(require_api_token)):
    from app.db.init_db import get_session
    from app.db.repo import BehavioralEventRepository

    if body.status not in ("confirmed", "rejected", "inconclusive", "pending"):
        return JSONResponse({"detail": "invalid status"}, status_code=400)
    session = get_session()
    try:
        repo = BehavioralEventRepository(session)
        ok = repo.review(event_id, body.status, reviewed_by="api_v1")
        return {"ok": bool(ok), "event_id": event_id, "status": body.status}
    finally:
        session.close()


class LiveHub:
    def __init__(self):
        self.clients: Set[WebSocket] = set()

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


live_hub = LiveHub()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    settings = get_settings()
    # Auth via query api_token se configurado
    expected = (settings.api_auth_token or "").strip()
    if expected:
        token = websocket.query_params.get("api_token")
        if token != expected:
            await websocket.close(code=4401)
            return
    await live_hub.connect(websocket)
    try:
        await websocket.send_json({"type": "system_status", "payload": {"ok": True}})
        while True:
            # heartbeat / client ping
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_json({"type": "heartbeat", "ts": time.time()})
            except WebSocketDisconnect:
                break
    finally:
        live_hub.disconnect(websocket)
