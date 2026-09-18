#!/usr/bin/env python3
"""Read-only probe of Edge env-relevant settings + recent outbox (Fase 5B physical)."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings, reload_settings

reload_settings()
s = get_settings()
out = {
    "probed_at": datetime.now(timezone.utc).isoformat(),
    "process_env": {
        "RUNTIME_MODE": os.environ.get("RUNTIME_MODE"),
        "PRESENCA_CONFIG_OVERLAY": os.environ.get("PRESENCA_CONFIG_OVERLAY"),
        "MODULE_LXP_MODE": os.environ.get("MODULE_LXP_MODE"),
        "LXP_SIM_ATTENDANCE_URL_set": bool(os.environ.get("LXP_SIM_ATTENDANCE_URL")),
        "LXP_SIM_INTEGRATION_TOKEN_set": bool(os.environ.get("LXP_SIM_INTEGRATION_TOKEN")),
        "LXP_SIM_ANON_KEY_set": bool(os.environ.get("LXP_SIM_ANON_KEY")),
        "LXP_EXTERNAL_LESSON_ID": os.environ.get("LXP_EXTERNAL_LESSON_ID") or None,
        "LXP_URL_is_simulator": "zasbmqwwkecmjbebejev"
        in (os.environ.get("LXP_SIM_ATTENDANCE_URL") or ""),
        "LXP_URL_is_prod_forbidden": any(
            x in (os.environ.get("LXP_SIM_ATTENDANCE_URL") or "")
            for x in ("lxp-prod", "production-lxp")
        ),
    },
    "settings": {
        "runtime_mode": getattr(s, "runtime_mode", None),
        "module_lxp_mode": getattr(s, "module_lxp_mode", None),
        "lxp_url_set": bool((getattr(s, "lxp_sim_attendance_url", "") or "").strip()),
        "lxp_token_set": bool((getattr(s, "lxp_sim_integration_token", "") or "").strip()),
        "lxp_anon_set": bool((getattr(s, "lxp_sim_anon_key", "") or "").strip()),
        "lxp_lesson": (getattr(s, "lxp_external_lesson_id", "") or "") or None,
        "lxp_url_is_simulator": "zasbmqwwkecmjbebejev"
        in (getattr(s, "lxp_sim_attendance_url", "") or ""),
        "config_overlay_hint": os.environ.get("PRESENCA_CONFIG_OVERLAY"),
    },
}

con = sqlite3.connect("data/dulino_edge.db")
con.row_factory = sqlite3.Row
sess = con.execute(
    "select session_id, status, title, started_at, metadata_json from class_sessions "
    "where status='active' order by rowid desc limit 3"
).fetchall()
out["active_sessions"] = [dict(r) for r in sess]

out["recent_checkins"] = []
for r in con.execute(
    "select event_id, status, payload_json from events "
    "where event_type='attendance_checkin' order by rowid desc limit 8"
):
    d = {"event_id": r["event_id"], "status": r["status"]}
    try:
        p = json.loads(r["payload_json"])
        d.update(
            {
                "student_id": p.get("student_id"),
                "session_id": p.get("session_id"),
                "timestamp": p.get("timestamp"),
            }
        )
    except Exception:
        pass
    out["recent_checkins"].append(d)

out["recent_lxp"] = []
for r in con.execute(
    "select event_id, status, retries, last_error, payload_json from events "
    "where event_type='lxp_attendance_event' order by rowid desc limit 10"
):
    d = {
        "event_id": r["event_id"],
        "status": r["status"],
        "retries": r["retries"],
        "last_error": r["last_error"],
    }
    try:
        p = json.loads(r["payload_json"])
        d.update(
            {
                "lesson_id": p.get("lesson_id"),
                "student_id": p.get("student_id"),
                "edge_student_key": p.get("edge_student_key"),
                "class_session_id": p.get("class_session_id"),
                "source_checkin_event_id": p.get("source_checkin_event_id"),
            }
        )
    except Exception:
        pass
    out["recent_lxp"].append(d)

path = Path("experiments/smoke_e2e_sentimentos/fase5b/json/fase5b_physical_env_audit.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
