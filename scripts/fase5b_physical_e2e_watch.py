#!/usr/bin/env python3
"""Wait for p01 checkin on current active session, then LXP→Simulator (no session rotate)."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments/smoke_e2e_sentimentos/fase5b/json"
SIM_URL = os.environ.get(
    "LXP_SIM_ATTENDANCE_URL",
    "https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events",
)
SIM_REST = "https://zasbmqwwkecmjbebejev.supabase.co/rest/v1"
TOKEN = os.environ.get("LXP_SIM_INTEGRATION_TOKEN", "homolog-lxp-sim-token-v1")
ANON = os.environ.get("LXP_SIM_ANON_KEY", "")


def db():
    con = sqlite3.connect(ROOT / "data/dulino_edge.db")
    con.row_factory = sqlite3.Row
    return con


def sim_headers():
    h = {"Content-Type": "application/json", "X-Integration-Token": TOKEN}
    if ANON:
        h["apikey"] = ANON
        h["Authorization"] = f"Bearer {ANON}"
    return h


def rest_headers():
    h = {"Accept": "application/json"}
    if ANON:
        h["apikey"] = ANON
        h["Authorization"] = f"Bearer {ANON}"
    return h


def main():
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "steps": [], "ids": {}}
    con = db()
    sid = con.execute(
        "select session_id from class_sessions where status='active' order by rowid desc limit 1"
    ).fetchone()
    if not sid:
        report["verdict"] = "FASE 5B — FLUXO FÍSICO E2E NÃO VALIDADO"
        report["stopped_at"] = "no_active_session"
        (OUT / "fase5b_physical_e2e.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report["verdict"]))
        return 1
    session_id = sid["session_id"]
    report["ids"]["session_id"] = session_id
    max_row = con.execute("select coalesce(max(rowid),0) from events").fetchone()[0]
    report["ids"]["events_max_rowid_before_wait"] = max_row
    print(f"waiting checkin p01 on session {session_id} ...", flush=True)

    checkin = None
    deadline = time.time() + 120
    while time.time() < deadline:
        con = db()
        for r in con.execute(
            "select rowid as rid, event_id, status, payload_json from events "
            "where event_type='attendance_checkin' and rowid>? order by rowid desc limit 20",
            (max_row,),
        ):
            p = json.loads(r["payload_json"])
            if p.get("student_id") == "p01" and p.get("session_id") == session_id:
                checkin = {
                    "rowid": r["rid"],
                    "event_id": r["event_id"],
                    "status": r["status"],
                    "student_id": p.get("student_id"),
                    "session_id": p.get("session_id"),
                }
                break
        if checkin:
            break
        # also accept any new p01 checkin if session_id in payload matches
        time.sleep(2)

    report["steps"].append({"name": "attendance_checkin_p01", "ok": bool(checkin), "checkin": checkin})
    if not checkin:
        # dump recent presence evidence from attendance_cache
        con = db()
        cache = [
            dict(r)
            for r in con.execute(
                "select student_id,date_key,session_id,sightings,last_seen_at from attendance_cache "
                "where student_id='p01' order by rowid desc limit 3"
            )
        ]
        report["steps"].append({"name": "cache_snapshot", "ok": False, "cache": cache})
        report["verdict"] = "FASE 5B — FLUXO FÍSICO E2E NÃO VALIDADO"
        report["stopped_at"] = "attendance_checkin"
        report["classification"] = "camera/reconhecimento — sem novo attendance_checkin após sessão com LXP ligado"
        (OUT / "fase5b_physical_e2e.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps({"verdict": report["verdict"], "stopped_at": "checkin", "cache": cache}, ensure_ascii=False))
        return 1

    report["ids"]["checkin_event_id"] = checkin["event_id"]
    report["ids"]["edge_student_id"] = checkin["student_id"]
    eid = f"lxp-att:{checkin['event_id']}"

    lxp = None
    deadline = time.time() + 90
    while time.time() < deadline:
        con = db()
        r = con.execute(
            "select event_id,status,retries,last_error,payload_json from events where event_id=?",
            (eid,),
        ).fetchone()
        if r:
            p = json.loads(r["payload_json"])
            lxp = {
                "event_id": r["event_id"],
                "status": r["status"],
                "retries": r["retries"],
                "last_error": r["last_error"],
                "lesson_id": p.get("lesson_id"),
                "student_id": p.get("student_id"),
                "edge_student_key": p.get("edge_student_key"),
                "class_session_id": p.get("class_session_id"),
            }
            if r["status"] in ("sent", "failed"):
                break
        time.sleep(2)

    report["steps"].append({"name": "outbox_lxp", "ok": bool(lxp), "lxp": lxp})
    report["steps"].append(
        {"name": "syncworker_sent", "ok": bool(lxp and lxp.get("status") == "sent"), "status": (lxp or {}).get("status")}
    )
    if not lxp or lxp.get("status") != "sent":
        report["verdict"] = "FASE 5B — FLUXO FÍSICO E2E NÃO VALIDADO"
        report["stopped_at"] = "outbox" if not lxp else "syncworker"
        (OUT / "fase5b_physical_e2e.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps({"verdict": report["verdict"], "lxp": lxp}, ensure_ascii=False))
        return 1

    report["ids"].update(
        {
            "event_id": lxp["event_id"],
            "lesson_id": lxp["lesson_id"],
            "student_id": lxp["student_id"],
        }
    )

    with httpx.Client(timeout=30.0) as c:
        r = c.get(
            f"{SIM_REST}/attendance_records",
            params={
                "select": "id,external_lesson_id,external_student_id,status,source_event_id",
                "source_event_id": f"eq.{lxp['event_id']}",
            },
            headers=rest_headers(),
        )
        rows = r.json() if r.status_code == 200 else {"http": r.status_code, "body": r.text[:300]}
        report["steps"].append(
            {"name": "simulator_attendance_records", "ok": isinstance(rows, list) and len(rows) == 1, "rows": rows}
        )
        try:
            rr = c.get(
                f"{SIM_REST}/integration_receipts",
                params={"select": "*", "source_event_id": f"eq.{lxp['event_id']}"},
                headers=rest_headers(),
            )
            receipts = rr.json() if rr.status_code == 200 else {"http": rr.status_code}
        except Exception as e:
            receipts = {"error": str(e)}
        report["steps"].append({"name": "integration_receipts", "ok": isinstance(receipts, list), "rows": receipts})

        dup = {
            "event_id": lxp["event_id"],
            "lesson_id": lxp["lesson_id"],
            "student_id": lxp["student_id"],
            "attendance": "present",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "sentimentos",
            "contract_version": "attendance.events.v1",
        }
        d1 = c.post(SIM_URL, json=dup, headers=sim_headers()).json()
        d2 = c.post(SIM_URL, json=dup, headers=sim_headers()).json()
        cnt = c.get(
            f"{SIM_REST}/attendance_records",
            params={"select": "id", "source_event_id": f"eq.{lxp['event_id']}"},
            headers=rest_headers(),
        ).json()
        report["steps"].append(
            {
                "name": "idempotency_same_event_id",
                "ok": isinstance(cnt, list) and len(cnt) == 1 and d2.get("result") == "duplicate",
                "post1": d1,
                "post2": d2,
                "db_count": len(cnt) if isinstance(cnt, list) else None,
            }
        )

    if isinstance(rows, list) and rows:
        report["ids"]["attendance_id"] = rows[0]["id"]
        report["ids"]["sim_source_event_id"] = rows[0]["source_event_id"]
        report["ids"]["sim_student_id"] = rows[0]["external_student_id"]
        report["ids"]["sim_lesson_id"] = rows[0]["external_lesson_id"]

    ids_ok = (
        report["ids"].get("event_id") == report["ids"].get("sim_source_event_id")
        and report["ids"].get("student_id") == report["ids"].get("sim_student_id") == "ext-stu-001"
        and report["ids"].get("lesson_id") == report["ids"].get("sim_lesson_id") == "lesson-8b-math-50"
        and report["ids"].get("edge_student_id") == "p01"
    )
    report["steps"].append({"name": "ids_preserved", "ok": ids_ok})
    con = db()
    cur = con.execute(
        "select session_id from class_sessions where status='active' order by rowid desc limit 1"
    ).fetchone()
    report["steps"].append(
        {"name": "session_stable", "ok": bool(cur and cur["session_id"] == session_id), "session_id": cur["session_id"] if cur else None}
    )

    critical = [
        "attendance_checkin_p01",
        "outbox_lxp",
        "syncworker_sent",
        "simulator_attendance_records",
        "ids_preserved",
        "idempotency_same_event_id",
    ]
    by = {s["name"]: s for s in report["steps"]}
    passed = all(by.get(n, {}).get("ok") for n in critical)
    report["passed"] = passed
    report["verdict"] = (
        "FASE 5B — FLUXO FÍSICO E2E VALIDADO" if passed else "FASE 5B — FLUXO FÍSICO E2E NÃO VALIDADO"
    )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (OUT / "fase5b_physical_e2e.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "passed": passed, "ids": report["ids"], "steps": [(s["name"], s.get("ok")) for s in report["steps"]]}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
