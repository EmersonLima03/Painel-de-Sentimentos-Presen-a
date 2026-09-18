"""Integração de chamada → LXP Attendance Simulator (homologação).

Não toca TRI. Consome apenas presença já validada (attendance_checkin com student_id).
Segredo LXP_SIM_INTEGRATION_TOKEN fica só no Edge (.env) — nunca no frontend.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.services.session_persistence import enqueue_outbox

logger = get_logger(__name__)

CONTRACT_VERSION = "attendance.events.v1"
LXP_ATTENDANCE_EVENT_TYPE = "lxp_attendance_event"


def _iso(ts: float | int | None) -> str:
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _session_meta(session_id: str | None) -> Dict[str, Any]:
    if not session_id:
        return {}
    try:
        from app.db.init_db import close_session, get_session
        from app.db.models import ClassSession
        import json

        db = get_session()
        try:
            row = db.query(ClassSession).filter(ClassSession.session_id == session_id).first()
            if not row or not row.metadata_json:
                return {}
            meta = json.loads(row.metadata_json)
            return meta if isinstance(meta, dict) else {}
        finally:
            close_session(db)
    except Exception as e:
        logger.warning("session_meta_read_failed", error=str(e))
        return {}


def resolve_external_student_id(
    edge_student_key: str, *, session_id: str | None = None
) -> Optional[str]:
    """Mapa Edge → ID externo LXP/Simulator.

    Ordem: roster da sessão (Fase 6) → env JSON → seed lab.
    """
    meta = _session_meta(session_id)
    ctx = meta.get("lesson_context") if isinstance(meta.get("lesson_context"), dict) else {}
    smap = ctx.get("student_map") if isinstance(ctx, dict) else None
    if isinstance(smap, dict) and edge_student_key in smap:
        val = str(smap.get(edge_student_key) or "").strip()
        if val:
            return val

    settings = get_settings()
    raw = (getattr(settings, "lxp_student_map_json", "") or "").strip()
    if raw:
        try:
            import json

            m = json.loads(raw)
            if isinstance(m, dict) and edge_student_key in m:
                return str(m[edge_student_key])
        except Exception:
            logger.warning("lxp_student_map_json_invalid")
    # Seed do simulador (lab): p01→ext-stu-001 …
    defaults = {
        "p01": "ext-stu-001",
        "p02": "ext-stu-002",
        "p03": "ext-stu-003",
    }
    return defaults.get(edge_student_key)


def resolve_external_lesson_id(session_id: str | None) -> Optional[str]:
    """Aula externa: sessão/ocorrência primeiro; env só fallback de laboratório."""
    meta = _session_meta(session_id)
    lid = meta.get("external_lesson_id")
    if not lid and isinstance(meta.get("lesson_context"), dict):
        lid = meta["lesson_context"].get("external_lesson_id")
    if lid:
        return str(lid).strip() or None

    settings = get_settings()
    fixed = (getattr(settings, "lxp_external_lesson_id", "") or "").strip()
    return fixed or None


def maybe_enqueue_lxp_attendance_from_checkin(event: Dict[str, Any]) -> bool:
    """Empilha evento de chamada no outbox product se houver identidade + aula externa.

    Regras:
    - module_lxp_mode em {simulator, http}
    - student_id obrigatório (não anônimo)
    - external_lesson_id configurado
    - mapeamento student → external_student_id
    """
    settings = get_settings()
    mode = (getattr(settings, "module_lxp_mode", "disabled") or "disabled").lower()
    if mode not in ("simulator", "http", "http_sim"):
        return False

    edge_key = str(event.get("student_id") or "").strip()
    if not edge_key or edge_key.startswith("anon") or edge_key == "unknown":
        logger.info("lxp_attendance_skipped_no_identity", student_id=edge_key or None)
        return False

    session_id = event.get("session_id")
    lesson_id = resolve_external_lesson_id(str(session_id) if session_id else None)
    if not lesson_id:
        logger.info("lxp_attendance_skipped_no_lesson", session_id=session_id)
        return False

    ext_student = resolve_external_student_id(
        edge_key, session_id=str(session_id) if session_id else None
    )
    if not ext_student:
        logger.info("lxp_attendance_skipped_unmapped_student", edge_student_key=edge_key)
        return False

    source_event_id = str(event.get("event_id") or "")
    if not source_event_id:
        return False

    # Idempotência estável: um check-in Edge → um event_id de integração
    event_id = f"lxp-att:{source_event_id}"
    payload = {
        "event_type": LXP_ATTENDANCE_EVENT_TYPE,
        "event_id": event_id,
        "contract_version": CONTRACT_VERSION,
        "lesson_id": lesson_id,
        "student_id": ext_student,
        "attendance": "present",
        "occurred_at": _iso(event.get("timestamp")),
        "source": "sentimentos",
        "edge_student_key": edge_key,
        "class_session_id": session_id,
        "source_checkin_event_id": source_event_id,
        "device_id": event.get("device_id") or settings.device_id,
    }
    ok = enqueue_outbox(LXP_ATTENDANCE_EVENT_TYPE, event_id, payload)
    if ok:
        logger.info(
            "lxp_attendance_enqueued",
            event_id=event_id,
            lesson_id=lesson_id,
            student_id=ext_student,
        )
    return ok


class LxpAttendanceClient:
    """Cliente HTTP → Edge Function attendance-events do simulador."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        anon_key: str | None = None,
        timeout: float = 10.0,
    ):
        settings = get_settings()
        self.url = (
            base_url
            or getattr(settings, "lxp_sim_attendance_url", "")
            or ""
        ).rstrip("/")
        self.token = token or getattr(settings, "lxp_sim_integration_token", "") or ""
        self.anon_key = anon_key or getattr(settings, "lxp_sim_anon_key", "") or ""
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(self.url and self.token)

    async def send_attendance_event(self, payload: Dict[str, Any]) -> bool:
        if not self.configured():
            logger.warning("lxp_sim_not_configured")
            return False

        headers = {
            "Content-Type": "application/json",
            "X-Integration-Token": self.token,
        }
        if self.anon_key:
            headers["apikey"] = self.anon_key
            headers["Authorization"] = f"Bearer {self.anon_key}"

        body = {
            "event_id": payload.get("event_id"),
            "lesson_id": payload.get("lesson_id"),
            "student_id": payload.get("student_id"),
            "attendance": payload.get("attendance", "present"),
            "occurred_at": payload.get("occurred_at"),
            "source": payload.get("source", "sentimentos"),
            "contract_version": payload.get("contract_version", CONTRACT_VERSION),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.url, json=body, headers=headers)
            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                    st = str(data.get("status") or "")
                    if st in ("unauthorized", "invalid", "retryable_error"):
                        logger.error("lxp_attendance_rejected", body=data)
                        return False
                except Exception:
                    pass
                logger.info(
                    "lxp_attendance_sent",
                    event_id=body.get("event_id"),
                    http=resp.status_code,
                )
                return True
            if resp.status_code in (401, 403, 400, 404):
                # Não retry cego para erros de contrato
                logger.error(
                    "lxp_attendance_client_error",
                    status=resp.status_code,
                    body=resp.text[:400],
                )
                return False
            logger.error(
                "lxp_attendance_server_error",
                status=resp.status_code,
                body=resp.text[:400],
            )
            return False
        except httpx.TimeoutException:
            logger.warning("lxp_attendance_timeout", url=self.url)
            return False
        except Exception as e:
            logger.error("lxp_attendance_error", error=str(e))
            return False


def token_sha256(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
