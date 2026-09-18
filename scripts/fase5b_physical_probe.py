#!/usr/bin/env python3
"""Probe LXP env + recent outbox for Fase 5B physical check (read-only)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.config import get_settings, reload_settings

reload_settings()
s = get_settings()
out = {
    "module_lxp_mode": getattr(s, "module_lxp_mode", None),
    "lxp_url_set": bool((getattr(s, "lxp_sim_attendance_url", "") or "").strip()),
    "lxp_token_set": bool((getattr(s, "lxp_sim_integration_token", "") or "").strip()),
    "lxp_lesson_set": bool((getattr(s, "lxp_external_lesson_id", "") or "").strip()),
    "lxp_url_is_simulator": "zasbmqwwkecmjbebejev" in (getattr(s, "lxp_sim_attendance_url", "") or ""),
}
con = sqlite3.connect("data/dulino_edge.db")
con.row_factory = sqlite3.Row
out["counts"] = [
    dict(r)
    for r in con.execute(
        "select event_type, status, count(*) as c from events "
        "where event_type in ('attendance_checkin','lxp_attendance_event') "
        "group by 1, 2"
    )
]
out["recent_checkins"] = []
for r in con.execute(
    "select event_id, event_type, status, payload_json from events "
    "where event_type='attendance_checkin' order by rowid desc limit 5"
):
    d = {"event_id": r["event_id"], "status": r["status"]}
    try:
        p = json.loads(r["payload_json"])
        d["student_id"] = p.get("student_id")
        d["session_id"] = p.get("session_id")
    except Exception:
        pass
    out["recent_checkins"].append(d)
out["recent_lxp"] = []
for r in con.execute(
    "select event_id, status, payload_json from events "
    "where event_type='lxp_attendance_event' order by rowid desc limit 8"
):
    d = {"event_id": r["event_id"], "status": r["status"]}
    try:
        p = json.loads(r["payload_json"])
        d["lesson_id"] = p.get("lesson_id")
        d["student_id"] = p.get("student_id")
        d["source"] = p.get("source")
    except Exception:
        pass
    out["recent_lxp"].append(d)

Path("experiments/smoke_e2e_sentimentos/fase5b/json/fase5b_physical_probe.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps(out, indent=2, ensure_ascii=False))
