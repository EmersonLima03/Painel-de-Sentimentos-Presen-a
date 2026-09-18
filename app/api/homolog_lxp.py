"""API agregadora de homologação LXP — somente leitura.

Não altera SyncWorker, outbox, TRI nem LXP de produção.
Tokens LXP_SIM_* ficam só no Edge; o browser chama apenas este endpoint.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query

from app.auth import require_api_token
from app.config import get_settings
from app.integrations.attendance_lxp import LXP_ATTENDANCE_EVENT_TYPE, LxpAttendanceClient
from app.logging import get_logger
from app.pipeline.analytics_track import filter_displayable_tracks
from app.runtime_mode import DISCLAIMER
from app.services.live_session import dashboard_track_view, get_live_session

logger = get_logger(__name__)

router = APIRouter(tags=["homolog-lxp"])

PROD_HOST_MARKERS = ("sde.sistemadulino", "sistemadulino.com", "kjbygtbg")


def _host_from_url(url: str) -> Optional[str]:
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def _safe_payload(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"raw": data}
    except Exception:
        return {"raw": raw}


def _list_events(event_type: str, *, limit: int = 40) -> List[Dict[str, Any]]:
    from app.db.init_db import close_session, get_session
    from app.db.models import Event
    from sqlalchemy import desc

    session = get_session()
    try:
        rows = (
            session.query(Event)
            .filter(Event.event_type == event_type)
            .order_by(desc(Event.created_at))
            .limit(limit)
            .all()
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            payload = _safe_payload(row.payload_json)
            out.append(
                {
                    "event_id": row.event_id,
                    "event_type": row.event_type,
                    "status": row.status,
                    "retries": int(row.retries or 0),
                    "last_error": row.last_error,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "sent_at": row.sent_at.isoformat() if getattr(row, "sent_at", None) else None,
                    "payload": payload,
                }
            )
        return out
    finally:
        close_session(session)


def _outbox_counts(lxp_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_status = Counter(str(e.get("status") or "") for e in lxp_events)
    retries_total = sum(int(e.get("retries") or 0) for e in lxp_events)
    return {
        "pending": int(by_status.get("pending", 0)),
        "sent": int(by_status.get("sent", 0)),
        "failed": int(by_status.get("failed", 0)),
        "retries_total": retries_total,
        "total": len(lxp_events),
    }


async def _fetch_simulator_view(client: LxpAttendanceClient, view: str) -> Dict[str, Any]:
    """Mesmo contrato do admin.html (view=lessons|attendance|receipts)."""
    if not client.configured():
        return {"ok": False, "error": "not_configured", "items": []}
    url = f"{client.url}?token={client.token}&view={view}"
    headers = {"X-Integration-Token": client.token}
    if client.anon_key:
        headers["apikey"] = client.anon_key
        headers["Authorization"] = f"Bearer {client.anon_key}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(url, headers=headers)
        data = resp.json() if resp.content else {}
        if not resp.is_success:
            return {"ok": False, "error": f"http_{resp.status_code}", "items": []}
        key = "attendance" if view == "attendance" else view
        items = data.get(key) if isinstance(data, dict) else None
        if items is None and isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    items = v
                    break
        if not isinstance(items, list):
            items = []
        return {"ok": True, "items": items, "http_status": resp.status_code}
    except Exception as e:
        logger.warning("homolog_simulator_view_failed", view=view, error=str(e))
        return {"ok": False, "error": str(e), "items": []}


def _build_history(lxp_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ev in lxp_events:
        p = ev.get("payload") or {}
        rows.append(
            {
                "horario": ev.get("created_at"),
                "aluno": p.get("edge_student_key") or p.get("student_id"),
                "edge_id": p.get("edge_student_key"),
                "external_id": p.get("student_id"),
                "lesson_id": p.get("lesson_id"),
                "event_id": ev.get("event_id"),
                "status": ev.get("status"),
                "destino": "LXP Attendance Simulator",
                "retries": ev.get("retries"),
                "sent_at": ev.get("sent_at"),
                "source_checkin_event_id": p.get("source_checkin_event_id"),
                "session_id": p.get("class_session_id"),
                "attendance": p.get("attendance"),
                "occurred_at": p.get("occurred_at"),
                "source": p.get("source"),
                "contract_version": p.get("contract_version"),
            }
        )
    return rows


def _idempotency_for_event(
    event_id: Optional[str], receipts: List[Dict[str, Any]], attendance: List[Dict[str, Any]]
) -> Dict[str, Any]:
    if not event_id:
        return {"observed": False, "message": "Idempotência não observada nesta execução."}
    bare = event_id.replace("lxp-att:", "", 1) if event_id.startswith("lxp-att:") else event_id
    related = [r for r in receipts if str(r.get("event_id") or "") == event_id]
    att_rows = [
        a
        for a in attendance
        if str(a.get("source_event_id") or "") in (event_id, bare, f"lxp-att:{bare}")
    ]
    if not related and not att_rows:
        return {"observed": False, "message": "Idempotência não observada nesta execução."}

    results = []
    for r in related:
        st = str(r.get("result_status") or r.get("status") or "").lower()
        results.append(
            {
                "result_status": st or None,
                "http_status": r.get("http_status"),
                "received_at": r.get("received_at"),
            }
        )
    return {
        "observed": True,
        "event_id": event_id,
        "receipts": results,
        "attendance_record_count": len(att_rows),
        "message": None,
    }


def _pipeline_for_event(
    *,
    selected: Optional[Dict[str, Any]],
    checkins: List[Dict[str, Any]],
    tracks: List[Dict[str, Any]],
    receipts: List[Dict[str, Any]],
    attendance: List[Dict[str, Any]],
) -> Dict[str, Any]:
    ev = selected
    p = (ev or {}).get("payload") or {}
    edge_key = p.get("edge_student_key")
    checkin_id = p.get("source_checkin_event_id")
    lxp_id = (ev or {}).get("event_id")
    ext_id = p.get("student_id")

    track_match = next(
        (t for t in tracks if edge_key and t.get("student_id") == edge_key),
        tracks[0] if tracks else None,
    )
    checkin = next((c for c in checkins if c.get("event_id") == checkin_id), None)

    receipt = None
    if lxp_id:
        for r in receipts:
            if str(r.get("event_id") or "") == lxp_id:
                receipt = r
                break
    att = None
    bare = (checkin_id or "").strip()
    for a in attendance:
        src = str(a.get("source_event_id") or "")
        if src in (lxp_id or "", bare, f"lxp-att:{bare}"):
            att = a
            break

    status_outbox = (ev or {}).get("status")
    sent = status_outbox == "sent"
    pending = status_outbox == "pending"
    failed = status_outbox == "failed"

    steps = [
        {
            "id": "recognition",
            "label": "Reconhecimento",
            "status": "ok" if track_match and track_match.get("student_id") else "idle",
            "horario": None,
            "info": (track_match or {}).get("student_id") or "Não observado",
        },
        {
            "id": "checkin",
            "label": "Check-in",
            "status": "ok" if checkin else "idle",
            "horario": (checkin or {}).get("created_at"),
            "info": (checkin or {}).get("event_id") or "Não observado",
        },
        {
            "id": "outbox",
            "label": "Outbox",
            "status": "ok" if ev else "idle",
            "horario": (ev or {}).get("created_at"),
            "info": lxp_id or "Não observado",
        },
        {
            "id": "syncworker",
            "label": "SyncWorker",
            "status": "ok" if sent else ("pending" if pending else ("fail" if failed else "idle")),
            "horario": (ev or {}).get("sent_at") or (ev or {}).get("created_at"),
            "info": (
                f"{status_outbox}" + (f" · retries={ev.get('retries')}" if ev else "")
                if ev
                else "Não observado"
            ),
        },
        {
            "id": "simulator",
            "label": "LXP Simulator",
            "status": "ok" if (receipt or sent) else ("pending" if pending else "idle"),
            "horario": (receipt or {}).get("received_at") or (ev or {}).get("sent_at"),
            "info": (
                f"HTTP {receipt.get('http_status')} · {receipt.get('result_status')}"
                if receipt
                else ("enviado (sent)" if sent else "Não observado")
            ),
        },
        {
            "id": "presence",
            "label": "Presença",
            "status": "ok" if att else "idle",
            "horario": (att or {}).get("received_at"),
            "info": (
                f"{att.get('external_student_id') or ext_id} — {att.get('status') or att.get('attendance') or 'present'}"
                if att
                else "Não observado"
            ),
        },
    ]

    detail = None
    if ev:
        detail = {
            "event_id": lxp_id,
            "checkin_event_id": checkin_id,
            "student_id_edge": edge_key,
            "external_student_id": ext_id,
            "map_label": f"{edge_key} → {ext_id}" if edge_key and ext_id else None,
            "lesson_id": p.get("lesson_id"),
            "session_id": p.get("class_session_id"),
            "attendance": p.get("attendance"),
            "occurred_at": p.get("occurred_at"),
            "source": p.get("source"),
            "contract_version": p.get("contract_version"),
            "outbox_status": status_outbox,
            "retry_count": (ev or {}).get("retries"),
            "http_status": (receipt or {}).get("http_status"),
            "resultado": (receipt or {}).get("result_status"),
            "attendance_id": (att or {}).get("id") or (att or {}).get("attendance_id"),
            "last_error": (ev or {}).get("last_error"),
        }

    return {"steps": steps, "detail": detail, "selected_event_id": lxp_id}


@router.get("/homolog/lxp")
async def homolog_lxp_snapshot(
    event_id: Optional[str] = Query(default=None),
    _: None = Depends(require_api_token),
):
    """Snapshot de homologação LXP para o painel visual (somente leitura)."""
    from app.api.v1 import _current_lesson_context, _live_state

    settings = get_settings()
    mode = (getattr(settings, "module_lxp_mode", "disabled") or "disabled").lower()
    sim_url = (getattr(settings, "lxp_sim_attendance_url", "") or "").strip()
    host = _host_from_url(sim_url) or "zasbmqwwkecmjbebejev.supabase.co"

    if any(m in (sim_url or "").lower() for m in PROD_HOST_MARKERS):
        logger.error("homolog_blocked_production_url")
        return {
            "ok": False,
            "error": "production_url_blocked",
            "environment": {
                "badge": "BLOCKED",
                "disclaimer": "Ambiente de homologação — não conectado ao LXP de produção.",
            },
            "disclaimer": DISCLAIMER,
        }

    ls = get_live_session()
    lesson_ctx = _current_lesson_context() or {}
    tracks_raw = filter_displayable_tracks(_live_state.get("tracks") or [])
    tracks = [dashboard_track_view(t) for t in tracks_raw]

    checkins = _list_events("attendance_checkin", limit=30)
    lxp_events = _list_events(LXP_ATTENDANCE_EVENT_TYPE, limit=40)
    counts = _outbox_counts(lxp_events)

    simulator_block: Dict[str, Any] = {
        "status": "disabled",
        "mode": mode,
        "lessons": [],
        "attendance": [],
        "receipts": [],
        "reason": None,
    }

    if mode not in ("simulator", "http_sim"):
        simulator_block["status"] = "disabled"
        simulator_block["reason"] = f"module_lxp_mode={mode}"
    else:
        client = LxpAttendanceClient()
        if not client.configured():
            simulator_block["status"] = "offline"
            simulator_block["reason"] = "lxp_sim_not_configured"
        else:
            lessons_r, att_r, rec_r = await asyncio.gather(
                _fetch_simulator_view(client, "lessons"),
                _fetch_simulator_view(client, "attendance"),
                _fetch_simulator_view(client, "receipts"),
            )
            ok_any = lessons_r.get("ok") or att_r.get("ok") or rec_r.get("ok")
            simulator_block["status"] = "online" if ok_any else "offline"
            simulator_block["lessons"] = lessons_r.get("items") or []
            simulator_block["attendance"] = att_r.get("items") or []
            simulator_block["receipts"] = rec_r.get("items") or []
            if not ok_any:
                simulator_block["reason"] = (
                    lessons_r.get("error") or att_r.get("error") or rec_r.get("error")
                )

    selected = lxp_events[0] if lxp_events else None
    if event_id:
        selected = next((e for e in lxp_events if e.get("event_id") == event_id), selected)
    pipeline = _pipeline_for_event(
        selected=selected,
        checkins=checkins,
        tracks=tracks,
        receipts=simulator_block.get("receipts") or [],
        attendance=simulator_block.get("attendance") or [],
    )
    idem = _idempotency_for_event(
        (selected or {}).get("event_id"),
        simulator_block.get("receipts") or [],
        simulator_block.get("attendance") or [],
    )

    session_meta = ls.session_meta()
    context = {
        "escola": lesson_ctx.get("school_name") or lesson_ctx.get("school_id"),
        "turma": lesson_ctx.get("class_group_name"),
        "disciplina": lesson_ctx.get("subject_name"),
        "aula": lesson_ctx.get("title"),
        "lesson_id": lesson_ctx.get("external_lesson_id"),
        "duracao_minutos": lesson_ctx.get("scheduled_duration_minutes"),
        "sala": lesson_ctx.get("room_name"),
        "session_id": session_meta.get("session_id") or ls.session_id or None,
        "school_id": lesson_ctx.get("school_id"),
        "student_map": lesson_ctx.get("student_map"),
    }

    presence_rows = []
    for a in simulator_block.get("attendance") or []:
        students = a.get("students") if isinstance(a.get("students"), dict) else {}
        presence_rows.append(
            {
                "aluno": a.get("external_student_id") or students.get("external_student_id"),
                "lesson_id": a.get("external_lesson_id") or a.get("lesson_id"),
                "attendance": a.get("status") or a.get("attendance"),
                "horario": a.get("received_at"),
                "source_event_id": a.get("source_event_id"),
                "attendance_id": a.get("id") or a.get("attendance_id"),
            }
        )

    return {
        "ok": True,
        "environment": {
            "title": "LXP Attendance",
            "subtitle": "Painel de Homologação",
            "badge": "SIMULATOR",
            "disclaimer": "Ambiente de homologação — não conectado ao LXP de produção.",
            "simulator_label": "LXP ATTENDANCE SIMULATOR",
            "simulator_host": host,
            "project_ref": "zasbmqwwkecmjbebejev",
        },
        "simulator": {
            "status": simulator_block["status"],
            "host": host,
            "mode": mode,
            "reason": simulator_block.get("reason"),
        },
        "context": context,
        "recognition": {
            "tracks": [
                {
                    "student_id": t.get("student_id"),
                    "full_name": t.get("full_name"),
                    "identity_state": t.get("identity_state"),
                }
                for t in tracks
            ],
            "present": _live_state.get("recognized_people"),
        },
        "outbox_summary": counts,
        "history": _build_history(lxp_events),
        "checkins": [
            {
                "event_id": c.get("event_id"),
                "created_at": c.get("created_at"),
                "status": c.get("status"),
                "student_id": (c.get("payload") or {}).get("student_id"),
                "session_id": (c.get("payload") or {}).get("session_id"),
            }
            for c in checkins
        ],
        "pipeline": pipeline,
        "presence": presence_rows,
        "idempotency": idem,
        "admin_simulator_hint": "experiments/lxp_attendance_simulator/admin.html",
        "disclaimer": DISCLAIMER,
    }
