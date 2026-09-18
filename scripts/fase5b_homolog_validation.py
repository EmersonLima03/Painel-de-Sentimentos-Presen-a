#!/usr/bin/env python3
"""Fase 5B — homologação E2E da chamada automática (Simulator only).

Não toca LXP produção nem TRI. Gera JSON em experiments/smoke_e2e_sentimentos/fase5b/json/
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

OUT_DIR = Path("experiments/smoke_e2e_sentimentos/fase5b/json")
URL = os.environ.get(
    "LXP_SIM_ATTENDANCE_URL",
    "https://zasbmqwwkecmjbebejev.supabase.co/functions/v1/attendance-events",
)
TOKEN = os.environ.get("LXP_SIM_INTEGRATION_TOKEN", "homolog-lxp-sim-token-v1")
ANON = os.environ.get("LXP_SIM_ANON_KEY", "")
SIM_REST = "https://zasbmqwwkecmjbebejev.supabase.co/rest/v1"


def headers_fn() -> Dict[str, str]:
    h = {"Content-Type": "application/json", "X-Integration-Token": TOKEN}
    if ANON:
        h["apikey"] = ANON
        h["Authorization"] = f"Bearer {ANON}"
    return h


def headers_rest() -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if ANON:
        h["apikey"] = ANON
        h["Authorization"] = f"Bearer {ANON}"
    return h


def post_event(body: dict) -> tuple[int, dict]:
    with httpx.Client(timeout=30.0) as c:
        r = c.post(URL, json=body, headers=headers_fn())
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text[:500]}


def get_view(view: str) -> tuple[int, dict]:
    with httpx.Client(timeout=30.0) as c:
        r = c.get(URL, params={"token": TOKEN, "view": view}, headers=headers_fn())
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text[:500]}


def rest_get(path: str, params: Optional[dict] = None) -> tuple[int, Any]:
    with httpx.Client(timeout=30.0) as c:
        r = c.get(f"{SIM_REST}/{path}", params=params or {}, headers=headers_rest())
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text[:500]


def case(name: str, ok: bool, **extra) -> dict:
    return {"name": name, "ok": ok, "result": "PASS" if ok else "FAIL", **extra}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "simulator_url": URL,
        "cases": [],
        "sections": {},
    }

    # --- 5/6 lessons seed ---
    code, lessons_body = get_view("lessons")
    lessons = lessons_body.get("lessons") or []
    by_id = {l.get("external_lesson_id"): l for l in lessons if isinstance(l, dict)}

    l50 = by_id.get("lesson-8b-math-50")
    l100 = by_id.get("lesson-8b-math-100")
    report["cases"].append(case("lesson_50_exists", bool(l50), lesson=l50))
    report["cases"].append(case("lesson_100_exists", bool(l100), lesson=l100))

    # duration: prefer lessons view (já autenticada via token); REST como fallback
    durations = {}
    for lid, row in (("lesson-8b-math-50", l50), ("lesson-8b-math-100", l100)):
        if not row:
            continue
        try:
            s = datetime.fromisoformat(str(row["starts_at"]).replace("Z", "+00:00"))
            e = datetime.fromisoformat(str(row["ends_at"]).replace("Z", "+00:00"))
            durations[lid] = round((e - s).total_seconds() / 60)
        except Exception:
            pass
    if not durations:
        code_r, rows = rest_get(
            "lessons",
            {
                "select": "external_lesson_id,title,starts_at,ends_at",
                "external_lesson_id": "in.(lesson-8b-math-50,lesson-8b-math-100)",
            },
        )
        if isinstance(rows, list):
            for row in rows:
                s = datetime.fromisoformat(str(row["starts_at"]).replace("Z", "+00:00"))
                e = datetime.fromisoformat(str(row["ends_at"]).replace("Z", "+00:00"))
                durations[row["external_lesson_id"]] = round((e - s).total_seconds() / 60)
    report["sections"]["durations_min"] = durations
    report["cases"].append(
        case("lesson_50_duration", durations.get("lesson-8b-math-50") == 50, minutes=durations.get("lesson-8b-math-50"))
    )
    report["cases"].append(
        case(
            "lesson_100_duration",
            durations.get("lesson-8b-math-100") == 100,
            minutes=durations.get("lesson-8b-math-100"),
            note="Bloco único de 100 min (um external_lesson_id), não duas aulas separadas",
        )
    )

    # students + lesson_students
    code_s, students = rest_get(
        "students",
        {"select": "external_student_id,edge_student_key,full_name", "order": "external_student_id"},
    )
    mapping_ok = False
    if isinstance(students, list):
        m = {s.get("edge_student_key"): s.get("external_student_id") for s in students}
        mapping_ok = m.get("p01") == "ext-stu-001" and m.get("p02") == "ext-stu-002" and m.get("p03") == "ext-stu-003"
        report["sections"]["student_map"] = m
    report["cases"].append(case("student_edge_map_p01_p03", mapping_ok, students=students if isinstance(students, list) else None))

    code_ls, ls = rest_get(
        "lesson_students",
        {
            "select": "lesson_id,student_id,lessons!inner(external_lesson_id),students!inner(external_student_id)",
            "lessons.external_lesson_id": "eq.lesson-8b-math-50",
        },
    )
    enrolled_50 = []
    if isinstance(ls, list):
        enrolled_50 = [x.get("students", {}).get("external_student_id") for x in ls if isinstance(x.get("students"), dict)]
    report["cases"].append(
        case(
            "lesson_50_students_linked",
            set(enrolled_50) >= {"ext-stu-001", "ext-stu-002", "ext-stu-003"},
            enrolled=enrolled_50,
        )
    )

    # --- presence → attendance for 50 min ---
    event_50 = f"fase5b-50-{uuid.uuid4()}"
    payload_50 = {
        "event_id": event_50,
        "lesson_id": "lesson-8b-math-50",
        "student_id": "ext-stu-001",
        "attendance": "present",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "sentimentos",
        "contract_version": "attendance.events.v1",
    }
    code, body = post_event(payload_50)
    att_id_50 = body.get("attendance_id")
    report["cases"].append(
        case(
            "flow_50_send",
            code == 200 and body.get("status") == "accepted" and bool(att_id_50),
            http=code,
            body=body,
        )
    )
    # confirm in DB via REST
    code_db, att_rows = rest_get(
        "attendance_records",
        {
            "select": "id,external_lesson_id,external_student_id,status,source_event_id",
            "source_event_id": f"eq.{event_50}",
        },
    )
    db_ok = (
        isinstance(att_rows, list)
        and len(att_rows) == 1
        and att_rows[0].get("external_lesson_id") == "lesson-8b-math-50"
        and att_rows[0].get("external_student_id") == "ext-stu-001"
        and att_rows[0].get("status") == "present"
    )
    report["cases"].append(case("flow_50_db_record", db_ok, rows=att_rows if isinstance(att_rows, list) else att_rows))

    # --- 100 min: one booking, one attendance (not two) ---
    event_100 = f"fase5b-100-{uuid.uuid4()}"
    payload_100 = {
        "event_id": event_100,
        "lesson_id": "lesson-8b-math-100",
        "student_id": "ext-stu-002",
        "attendance": "present",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "sentimentos",
        "contract_version": "attendance.events.v1",
    }
    code, body = post_event(payload_100)
    report["cases"].append(
        case("flow_100_send", code == 200 and body.get("status") == "accepted", http=code, body=body)
    )
    code_db, att100 = rest_get(
        "attendance_records",
        {"select": "*", "source_event_id": f"eq.{event_100}"},
    )
    report["cases"].append(
        case(
            "flow_100_single_record",
            isinstance(att100, list) and len(att100) == 1,
            rows=att100 if isinstance(att100, list) else att100,
            behavior="Um external_lesson_id de 100 min = um registro de chamada (não duplica por duração)",
        )
    )

    # --- multi student mapping ---
    multi_ids = []
    for edge, ext in [("p01", "ext-stu-001"), ("p02", "ext-stu-002"), ("p03", "ext-stu-003")]:
        eid = f"fase5b-map-{edge}-{uuid.uuid4()}"
        code, body = post_event(
            {
                "event_id": eid,
                "lesson_id": "lesson-8b-math-50",
                "student_id": ext,
                "attendance": "present",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "source": "sentimentos",
            }
        )
        multi_ids.append({"edge": edge, "ext": ext, "event_id": eid, "http": code, "ok": code == 200})
    report["cases"].append(case("map_three_students_send", all(x["ok"] for x in multi_ids), details=multi_ids))

    # --- idempotency 10x ---
    idem_id = f"fase5b-idem-{uuid.uuid4()}"
    payload_idem = {
        "event_id": idem_id,
        "lesson_id": "lesson-8b-math-50",
        "student_id": "ext-stu-003",
        "attendance": "present",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "sentimentos",
    }
    att_ids = []
    for i in range(10):
        code, body = post_event(payload_idem)
        att_ids.append(body.get("attendance_id"))
    unique = {a for a in att_ids if a}
    code_db, idem_rows = rest_get(
        "attendance_records",
        {"select": "id,source_event_id", "source_event_id": f"eq.{idem_id}"},
    )
    report["cases"].append(
        case(
            "idempotency_10x",
            len(unique) == 1 and isinstance(idem_rows, list) and len(idem_rows) == 1,
            unique_attendance_ids=list(unique),
            db_count=len(idem_rows) if isinstance(idem_rows, list) else None,
        )
    )

    # --- errors ---
    bad = httpx.post(
        URL,
        json={"event_id": "x"},
        headers={"Content-Type": "application/json", "X-Integration-Token": "wrong-token"},
        timeout=20.0,
    )
    report["cases"].append(case("error_invalid_token", bad.status_code == 401, http=bad.status_code))

    code, body = post_event(
        {
            "event_id": f"fase5b-nolesson-{uuid.uuid4()}",
            "lesson_id": "lesson-does-not-exist",
            "student_id": "ext-stu-001",
            "attendance": "present",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "sentimentos",
        }
    )
    report["cases"].append(case("error_lesson_missing", code == 404, http=code, body=body))

    code, body = post_event(
        {
            "event_id": f"fase5b-nostu-{uuid.uuid4()}",
            "lesson_id": "lesson-8b-math-50",
            "student_id": "ext-stu-unknown",
            "attendance": "present",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "sentimentos",
        }
    )
    report["cases"].append(case("error_student_missing", code == 404, http=code, body=body))

    # duplicate already covered by idempotency; mark explicit
    code, body = post_event(payload_idem)
    report["cases"].append(
        case(
            "error_duplicate_accepted",
            code == 200 and body.get("result") == "duplicate",
            http=code,
            body=body,
        )
    )

    # --- offline simulation via unit-level Fake client (documented in section) ---
    # Full SyncWorker offline is validated in pytest; here we simulate unavailable endpoint
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.post(
                "https://127.0.0.1:9/functions/v1/attendance-events",
                json=payload_50,
                headers=headers_fn(),
            )
        offline_ok = False
        offline_detail = f"unexpected_http_{r.status_code}"
    except Exception as e:
        offline_ok = True
        offline_detail = type(e).__name__
    report["cases"].append(
        case(
            "offline_endpoint_unreachable",
            offline_ok,
            detail=offline_detail,
            note="Indisponibilidade do Simulator não deve derrubar aula local (Edge continua; outbox pending)",
        )
    )

    # SyncWorker offline→online (mesmo padrão dos testes unitários)
    from app.db.init_db import close_session, get_session, init_database
    from app.db.models import Event
    from app.sync.worker import SyncWorker

    init_database()
    session = get_session()
    try:

        class Flaky:
            def __init__(self):
                self.calls = 0
                self.sent: List[dict] = []

            def configured(self):
                return True

            async def send_attendance_event(self, payload):
                self.calls += 1
                if self.calls == 1:
                    return False  # Simulator indisponível
                self.sent.append(payload)
                return True

        eid = f"lxp-att:fase5b-offline-{uuid.uuid4()}"
        payload = {
            "event_type": "lxp_attendance_event",
            "event_id": eid,
            "lesson_id": "lesson-8b-math-50",
            "student_id": "ext-stu-001",
            "attendance": "present",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "sentimentos",
        }
        session.add(
            Event(
                event_id=eid,
                event_type="lxp_attendance_event",
                payload_json=json.dumps(payload),
                status="pending",
                retries=0,
            )
        )
        session.commit()
        flaky = Flaky()
        worker = SyncWorker(lxp_client=flaky)  # type: ignore
        worker.retry_attempts = 3
        worker.retry_backoff = 0
        asyncio.run(worker.sync_batch())
        row = session.query(Event).filter(Event.event_id == eid).one()
        pending_after_fail = row.status == "pending" and row.retries >= 1
        asyncio.run(worker.sync_batch())
        session.refresh(row)
        recovered = (
            row.status == "sent"
            and len(flaky.sent) == 1
            and flaky.sent[0]["event_id"] == eid
        )
        report["cases"].append(
            case(
                "offline_to_online_syncworker",
                pending_after_fail and recovered,
                event_id=eid,
                final_status=row.status,
                sends=len(flaky.sent),
                note="event_id estável; 1 send após recovery; não duplica",
            )
        )
    finally:
        close_session(session)

    report["passed"] = all(c.get("ok") for c in report["cases"])
    report["summary"] = {
        "total": len(report["cases"]),
        "pass": sum(1 for c in report["cases"] if c.get("ok")),
        "fail": sum(1 for c in report["cases"] if not c.get("ok")),
    }
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    out = OUT_DIR / "fase5b_validation.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "summary": report["summary"], "out": str(out)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
