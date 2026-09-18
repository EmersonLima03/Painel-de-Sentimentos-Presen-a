#!/usr/bin/env python3
"""Smoke API: LXP Attendance Simulator — idempotência + erros (sem LXP produção)."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

OUT = Path("experiments/smoke_e2e_sentimentos/lxp_sim_integration_results.json")
URL = os.environ.get(
    "LXP_SIM_ATTENDANCE_URL",
    "https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events",
)
TOKEN = os.environ.get("LXP_SIM_INTEGRATION_TOKEN", "homolog-lxp-sim-token-v1")
ANON = os.environ.get("LXP_SIM_ANON_KEY", "")


def headers():
    h = {"Content-Type": "application/json", "X-Integration-Token": TOKEN}
    if ANON:
        h["apikey"] = ANON
        h["Authorization"] = f"Bearer {ANON}"
    return h


def post(body: dict) -> tuple[int, dict]:
    with httpx.Client(timeout=30.0) as c:
        r = c.post(URL, json=body, headers=headers())
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:500]}
        return r.status_code, data


def get(view: str) -> tuple[int, dict]:
    with httpx.Client(timeout=30.0) as c:
        r = c.get(URL, params={"token": TOKEN, "view": view}, headers=headers())
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:500]}
        return r.status_code, data


def main() -> int:
    results: dict = {"url": URL, "cases": []}

    # invalid token
    bad = httpx.post(
        URL,
        json={"event_id": "x"},
        headers={"Content-Type": "application/json", "X-Integration-Token": "wrong"},
        timeout=20.0,
    )
    results["cases"].append(
        {"name": "invalid_token", "http": bad.status_code, "ok": bad.status_code == 401}
    )

    # invalid payload
    code, body = post({"event_id": "only-id"})
    results["cases"].append(
        {"name": "invalid_payload", "http": code, "body": body, "ok": code == 400}
    )

    # lesson not found
    code, body = post(
        {
            "event_id": f"evt-missing-lesson-{uuid.uuid4()}",
            "lesson_id": "lesson-does-not-exist",
            "student_id": "ext-stu-001",
            "attendance": "present",
            "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "sentimentos",
        }
    )
    results["cases"].append(
        {"name": "lesson_not_found", "http": code, "body": body, "ok": code == 404}
    )

    # student not found
    code, body = post(
        {
            "event_id": f"evt-missing-stu-{uuid.uuid4()}",
            "lesson_id": "lesson-8b-math-50",
            "student_id": "ext-stu-unknown",
            "attendance": "present",
            "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "sentimentos",
        }
    )
    results["cases"].append(
        {"name": "student_not_found", "http": code, "body": body, "ok": code == 404}
    )

    # happy path + idempotency
    event_id = f"evt-idem-{uuid.uuid4()}"
    payload = {
        "event_id": event_id,
        "lesson_id": "lesson-8b-math-50",
        "student_id": "ext-stu-001",
        "attendance": "present",
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "sentimentos",
        "contract_version": "attendance.events.v1",
    }
    codes = []
    att_ids = []
    for i in range(10):
        code, body = post(payload)
        codes.append(code)
        att_ids.append(body.get("attendance_id"))
        results["cases"].append(
            {
                "name": f"idempotent_send_{i+1}",
                "http": code,
                "result": body.get("result"),
                "attendance_id": body.get("attendance_id"),
                "ok": code == 200 and body.get("status") == "accepted",
            }
        )

    unique_att = {a for a in att_ids if a}
    results["idempotency"] = {
        "event_id": event_id,
        "sends": 10,
        "all_http_200": all(c == 200 for c in codes),
        "unique_attendance_ids": list(unique_att),
        "ok": len(unique_att) == 1 and all(c == 200 for c in codes),
    }

    # GET views
    for view in ("lessons", "attendance", "receipts"):
        code, body = get(view)
        results["cases"].append(
            {
                "name": f"get_{view}",
                "http": code,
                "ok": code == 200 and body.get("ok") is True,
                "keys": list(body.keys()) if isinstance(body, dict) else [],
            }
        )

    results["passed"] = all(c.get("ok") for c in results["cases"]) and results["idempotency"]["ok"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"passed": results["passed"], "out": str(OUT)}, ensure_ascii=False))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
