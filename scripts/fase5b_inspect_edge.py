#!/usr/bin/env python3
"""Inspect local Edge outbox/session for Fase 5B evidence."""
import json
import sqlite3
from pathlib import Path

db = Path("data/dulino_edge.db")
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table'").fetchall()]
out = {"tables_sample": tables, "lxp_events": [], "sessions": []}

if "events" in tables:
    rows = cur.execute(
        "select event_id, event_type, status, retries, payload_json from events "
        "where event_type='lxp_attendance_event' order by rowid desc limit 20"
    ).fetchall()
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json"))
        except Exception:
            d["payload_raw"] = d.pop("payload_json")[:300]
        out["lxp_events"].append(d)

for t in ("class_sessions", "sessions", "session"):
    if t in tables:
        cols = [c[1] for c in cur.execute(f"pragma table_info({t})").fetchall()]
        out["session_table"] = t
        out["session_cols"] = cols
        rows = cur.execute(f"select * from {t} order by rowid desc limit 5").fetchall()
        for r in rows:
            out["sessions"].append({k: r[k] for k in r.keys()})
        break

Path("experiments/smoke_e2e_sentimentos/fase5b/json/fase5b_edge_outbox.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
)
print(json.dumps({"lxp_count": len(out["lxp_events"]), "session_table": out.get("session_table"), "statuses": [e.get("status") for e in out["lxp_events"][:10]]}, ensure_ascii=False))
