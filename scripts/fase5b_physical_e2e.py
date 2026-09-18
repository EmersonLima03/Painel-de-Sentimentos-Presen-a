#!/usr/bin/env python3
"""Fase 5B physical E2E: rotate session via existing APIs, then watch checkin→LXP→Simulator.

Does NOT modify TRI/product code. Does NOT print secrets.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments/smoke_e2e_sentimentos/fase5b/json"
OUT.mkdir(parents=True, exist_ok=True)
EDGE = os.environ.get("FASE5B_EDGE_URL", "http://127.0.0.1:8000")
SIM_URL = os.environ.get(
    "LXP_SIM_ATTENDANCE_URL",
    "https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events",
)
SIM_REST = "https://zasbmqwwkecmjbebejev.supabase.co/rest/v1"
TOKEN = os.environ.get("LXP_SIM_INTEGRATION_TOKEN", "homolog-lxp-sim-token-v1")
ANON = os.environ.get("LXP_SIM_ANON_KEY", "")


def load_device_token() -> str:
    for name in (".env", ".env.smoke.local"):
        p = ROOT / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("DEVICE_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DEVICE_TOKEN", "")


def edge_headers() -> dict:
    t = load_device_token()
    return {"X-API-Token": t, "Content-Type": "application/json"} if t else {"Content-Type": "application/json"}


def sim_headers() -> dict:
    h = {"Content-Type": "application/json", "X-Integration-Token": TOKEN}
    if ANON:
        h["apikey"] = ANON
        h["Authorization"] = f"Bearer {ANON}"
    return h


def rest_headers() -> dict:
    h = {"Accept": "application/json"}
    if ANON:
        h["apikey"] = ANON
        h["Authorization"] = f"Bearer {ANON}"
    return h


def db():
    con = sqlite3.connect(ROOT / "data/dulino_edge.db")
    con.row_factory = sqlite3.Row
    return con


def active_session(con) -> str | None:
    row = con.execute(
        "select session_id from class_sessions where status='active' order by rowid desc limit 1"
    ).fetchone()
    return row["session_id"] if row else None


def latest_checkin(con, *, after_rowid: int = 0, student_id: str = "p01"):
    rows = con.execute(
        "select rowid as rid, event_id, status, payload_json from events "
        "where event_type='attendance_checkin' and rowid>? order by rowid desc limit 30",
        (after_rowid,),
    ).fetchall()
    for r in rows:
        try:
            p = json.loads(r["payload_json"])
        except Exception:
            continue
        if p.get("student_id") == student_id:
            return {
                "rowid": r["rid"],
                "event_id": r["event_id"],
                "status": r["status"],
                "student_id": p.get("student_id"),
                "session_id": p.get("session_id"),
                "payload": p,
            }
    return None


def lxp_for_checkin(con, checkin_event_id: str):
    eid = f"lxp-att:{checkin_event_id}"
    r = con.execute(
        "select event_id, status, retries, last_error, payload_json from events where event_id=?",
        (eid,),
    ).fetchone()
    if not r:
        return None
    p = json.loads(r["payload_json"])
    return {
        "event_id": r["event_id"],
        "status": r["status"],
        "retries": r["retries"],
        "last_error": r["last_error"],
        "lesson_id": p.get("lesson_id"),
        "student_id": p.get("student_id"),
        "edge_student_key": p.get("edge_student_key"),
        "class_session_id": p.get("class_session_id"),
        "source_checkin_event_id": p.get("source_checkin_event_id"),
        "payload": p,
    }


def main() -> int:
    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "ids": {},
    }

    with httpx.Client(timeout=20.0) as c:
        h = edge_headers()
        health = c.get(f"{EDGE}/health")
        report["steps"].append({"name": "edge_health", "ok": health.status_code == 200, "body": health.json() if health.status_code == 200 else health.text[:200]})

        con = db()
        old_sid = active_session(con)
        max_row = con.execute("select coalesce(max(rowid),0) from events").fetchone()[0]
        report["ids"]["session_id_before"] = old_sid
        report["ids"]["events_max_rowid_before"] = max_row

        if old_sid:
            end = c.post(f"{EDGE}/sessions/{old_sid}/end", headers=h)
            report["steps"].append({"name": "session_end", "ok": end.status_code < 400, "http": end.status_code, "body": end.text[:300]})
        else:
            report["steps"].append({"name": "session_end", "ok": True, "note": "no active"})

        start = c.post(
            f"{EDGE}/sessions/start",
            headers=h,
            json={"title": "Fase5B fisico E2E", "room_id": "DEV"},
        )
        start_body = start.json() if start.headers.get("content-type", "").startswith("application/json") else {"raw": start.text[:300]}
        report["steps"].append({"name": "session_start", "ok": start.status_code < 400, "http": start.status_code, "body": start_body})
        new_sid = start_body.get("session_id") if isinstance(start_body, dict) else None
        report["ids"]["session_id"] = new_sid

    # Wait for camera checkin p01
    deadline = time.time() + 90
    checkin = None
    while time.time() < deadline:
        con = db()
        checkin = latest_checkin(con, after_rowid=max_row, student_id="p01")
        if checkin and checkin.get("session_id") == new_sid:
            break
        time.sleep(2)

    report["steps"].append(
        {
            "name": "attendance_checkin_p01",
            "ok": bool(checkin and checkin.get("session_id") == new_sid),
            "checkin": {k: v for k, v in (checkin or {}).items() if k != "payload"},
        }
    )
    if not checkin:
        report["verdict"] = "FASE 5B — FLUXO FÍSICO E2E NÃO VALIDADO"
        report["stopped_at"] = "attendance_checkin"
        (OUT / "fase5b_physical_e2e.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps({"verdict": report["verdict"], "stopped_at": "checkin"}, ensure_ascii=False))
        return 1

    report["ids"]["checkin_event_id"] = checkin["event_id"]
    report["ids"]["edge_student_id"] = checkin["student_id"]

    # Wait for LXP outbox enqueue + sent
    lxp = None
    deadline = time.time() + 60
    while time.time() < deadline:
        con = db()
        lxp = lxp_for_checkin(con, checkin["event_id"])
        if lxp and lxp["status"] == "sent":
            break
        if lxp and lxp["status"] == "failed":
            break
        time.sleep(2)

    report["steps"].append(
        {
            "name": "outbox_lxp",
            "ok": bool(lxp),
            "lxp": {k: v for k, v in (lxp or {}).items() if k != "payload"},
        }
    )
    report["steps"].append(
        {
            "name": "syncworker_sent",
            "ok": bool(lxp and lxp.get("status") == "sent"),
            "status": (lxp or {}).get("status"),
            "last_error": (lxp or {}).get("last_error"),
        }
    )

    if not lxp:
        report["verdict"] = "FASE 5B — FLUXO FÍSICO E2E NÃO VALIDADO"
        report["stopped_at"] = "outbox"
        (OUT / "fase5b_physical_e2e.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps({"verdict": report["verdict"], "stopped_at": "outbox"}, ensure_ascii=False))
        return 1

    report["ids"]["event_id"] = lxp["event_id"]
    report["ids"]["lesson_id"] = lxp["lesson_id"]
    report["ids"]["student_id"] = lxp["student_id"]

    # Simulator DB confirmation
    with httpx.Client(timeout=30.0) as c:
        r = c.get(
            f"{SIM_REST}/attendance_records",
            params={
                "select": "id,external_lesson_id,external_student_id,status,source_event_id,created_at",
                "source_event_id": f"eq.{lxp['event_id']}",
            },
            headers=rest_headers(),
        )
        rows = r.json() if r.status_code == 200 else {"error": r.text[:400], "http": r.status_code}
        report["steps"].append({"name": "simulator_attendance_records", "ok": isinstance(rows, list) and len(rows) == 1, "rows": rows})

        receipts = None
        try:
            rr = c.get(
                f"{SIM_REST}/integration_receipts",
                params={"select": "*", "source_event_id": f"eq.{lxp['event_id']}"},
                headers=rest_headers(),
            )
            receipts = rr.json() if rr.status_code == 200 else {"http": rr.status_code, "body": rr.text[:300]}
        except Exception as e:
            receipts = {"error": str(e)}
        report["steps"].append(
            {
                "name": "integration_receipts",
                "ok": isinstance(receipts, list),
                "rows": receipts,
                "note": "ok=False se tabela/RLS não exposta; não bloqueia se attendance_records ok",
            }
        )

        # Idempotency: POST same event_id again to Simulator API (same payload), without inventing new presence
        dup_payload = {
            "event_id": lxp["event_id"],
            "lesson_id": lxp["lesson_id"],
            "student_id": lxp["student_id"],
            "attendance": "present",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "sentimentos",
            "contract_version": "attendance.events.v1",
        }
        d1 = c.post(SIM_URL, json=dup_payload, headers=sim_headers())
        d2 = c.post(SIM_URL, json=dup_payload, headers=sim_headers())
        try:
            b1, b2 = d1.json(), d2.json()
        except Exception:
            b1, b2 = {"raw": d1.text[:200]}, {"raw": d2.text[:200]}
        rcount = c.get(
            f"{SIM_REST}/attendance_records",
            params={"select": "id", "source_event_id": f"eq.{lxp['event_id']}"},
            headers=rest_headers(),
        )
        count_rows = rcount.json() if rcount.status_code == 200 else []
        report["steps"].append(
            {
                "name": "idempotency_same_event_id",
                "ok": isinstance(count_rows, list)
                and len(count_rows) == 1
                and b1.get("result") in ("duplicate", "inserted", None)
                and b2.get("result") == "duplicate",
                "post1": {"http": d1.status_code, "body": b1},
                "post2": {"http": d2.status_code, "body": b2},
                "db_count": len(count_rows) if isinstance(count_rows, list) else None,
            }
        )

    if isinstance(rows, list) and rows:
        report["ids"]["attendance_id"] = rows[0].get("id")
        report["ids"]["sim_source_event_id"] = rows[0].get("source_event_id")
        report["ids"]["sim_student_id"] = rows[0].get("external_student_id")
        report["ids"]["sim_lesson_id"] = rows[0].get("external_lesson_id")

    ids_ok = (
        report["ids"].get("event_id") == report["ids"].get("sim_source_event_id")
        and report["ids"].get("student_id") == report["ids"].get("sim_student_id")
        and report["ids"].get("lesson_id") == report["ids"].get("sim_lesson_id")
        and report["ids"].get("student_id") == "ext-stu-001"
        and report["ids"].get("edge_student_id") == "p01"
    )
    report["steps"].append({"name": "ids_preserved", "ok": ids_ok, "ids": report["ids"]})

    # Session still active
    con = db()
    cur = active_session(con)
    report["steps"].append(
        {
            "name": "session_stable",
            "ok": cur == new_sid,
            "session_id": cur,
        }
    )

    critical = ["attendance_checkin_p01", "outbox_lxp", "syncworker_sent", "simulator_attendance_records", "ids_preserved", "idempotency_same_event_id"]
    by = {s["name"]: s for s in report["steps"]}
    passed = all(by.get(n, {}).get("ok") for n in critical)
    report["passed"] = passed
    report["verdict"] = (
        "FASE 5B — FLUXO FÍSICO E2E VALIDADO" if passed else "FASE 5B — FLUXO FÍSICO E2E NÃO VALIDADO"
    )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (OUT / "fase5b_physical_e2e.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "passed": passed,
                "ids": report["ids"],
                "steps": [(s["name"], s.get("ok")) for s in report["steps"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
