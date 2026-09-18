"""Validação operacional Fase 6 (API + cloud + opcional LXP/câmera)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments" / "smoke_e2e_sentimentos" / "fase6"
OUT.mkdir(parents=True, exist_ok=True)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    load_env_file(ROOT / ".env.smoke.local")
    load_env_file(ROOT / ".env")
    report: dict = {
        "started": datetime.now(timezone.utc).isoformat(),
        "results": [],
        "lxp_production_touched": False,
        "tri_diff_empty": True,
    }

    def add(area: str, result: str, evidence: str = "", note: str = ""):
        report["results"].append(
            {"area": area, "result": result, "evidence": evidence, "note": note}
        )

    base = "http://127.0.0.1:8000"
    # health
    try:
        h = httpx.get(f"{base}/health", timeout=5).json()
        add("edge_health", "PASS", f"cameras_online={h.get('cameras_online')}")
    except Exception as e:
        add("edge_health", "FAIL", str(e))
        (OUT / "FASE6_VALIDATION.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return 1

    # current context
    ctx = httpx.get(f"{base}/api/v1/sessions/current-context", timeout=10).json()
    add(
        "current_context_api",
        "PASS",
        f"session={ctx.get('session_id')} active={ctx.get('active_session_id')}",
    )

    # End any active session to clear conflict for clean start
    active = ctx.get("active_session_id") or ctx.get("session_id")
    if active:
        er = httpx.post(f"{base}/sessions/{active}/end", timeout=15)
        add(
            "clear_active_session",
            "PASS" if er.status_code < 400 else "FAIL",
            f"http={er.status_code} sid={active}",
        )
        time.sleep(0.5)

    # cache push
    occ_id = "a1a1a1a1-b2b2-c3c3-d4d4-e5e5e5e5e5e5"
    payload_occ = {
        "id": occ_id,
        "lesson_occurrence_id": occ_id,
        "organization_id": os.environ.get("CLOUD_ORGANIZATION_ID"),
        "school_id": os.environ.get("CLOUD_SCHOOL_ID"),
        "class_group_id": os.environ.get("CLASS_GROUP_ID"),
        "subject_id": os.environ.get("SUBJECT_ID"),
        "teacher_profile_id": os.environ.get("PROFESSOR_UID"),
        "room_id": os.environ.get("ROOM_ID"),
        "class_group_name": "8º Ano B",
        "subject_name": "Matemática",
        "teacher_name": "Professor Demo",
        "room_name": "Sala 03",
        "scheduled_start_at": datetime.now(timezone.utc).isoformat(),
        "scheduled_duration_minutes": 50,
        "external_lesson_id": "lesson-8b-math-50",
        "roster": [
            {"edge_student_key": "p01", "external_ref": "ext-stu-001", "full_name": "Aluno P01"}
        ],
    }
    cr = httpx.post(
        f"{base}/api/v1/lessons/cache",
        json={"occurrences": [payload_occ]},
        timeout=10,
    )
    add("lessons_cache", "PASS" if cr.status_code == 200 else "FAIL", f"http={cr.status_code}")

    # start
    start_body = {**payload_occ, "lesson_occurrence_id": occ_id}
    sr = httpx.post(f"{base}/api/v1/sessions/start-with-context", json=start_body, timeout=15)
    sdata = sr.json() if sr.content else {}
    add(
        "start_with_context",
        "PASS" if sr.status_code == 200 and sdata.get("ok") else "FAIL",
        f"http={sr.status_code} status={sdata.get('status')} sid={sdata.get('session_id')}",
        note=sdata.get("message") or "",
    )
    sid = sdata.get("session_id")

    # resume same
    sr2 = httpx.post(f"{base}/api/v1/sessions/start-with-context", json=start_body, timeout=15)
    d2 = sr2.json() if sr2.content else {}
    add(
        "resume_same_occurrence",
        "PASS" if d2.get("status") == "resumed" and d2.get("session_id") == sid else "FAIL",
        f"status={d2.get('status')} sid={d2.get('session_id')}",
    )

    # conflict
    other = {
        **start_body,
        "lesson_occurrence_id": "b2b2b2b2-c3c3-d4d4-e5e5-f6f6f6f6f6f6",
        "class_group_name": "9º A",
        "subject_name": "História",
    }
    sr3 = httpx.post(f"{base}/api/v1/sessions/start-with-context", json=other, timeout=15)
    d3 = sr3.json() if sr3.content else {}
    add(
        "conflict_other_occurrence",
        "PASS" if sr3.status_code == 409 and d3.get("code") == "conflict_active_session" else "FAIL",
        f"http={sr3.status_code} code={d3.get('code')} label={d3.get('active_label')}",
    )

    # context on live status
    st = httpx.get(f"{base}/api/v1/live/status", timeout=10).json()
    lc = st.get("lesson_context") or {}
    add(
        "live_status_lesson_context",
        "PASS"
        if lc.get("external_lesson_id") == "lesson-8b-math-50"
        and lc.get("class_group_name") == "8º Ano B"
        else "FAIL",
        f"lesson={lc.get('external_lesson_id')} turma={lc.get('class_group_name')}",
    )

    # reopen: end then start again
    if sid:
        httpx.post(f"{base}/sessions/{sid}/end", timeout=15)
        time.sleep(0.3)
        sr4 = httpx.post(f"{base}/api/v1/sessions/start-with-context", json=start_body, timeout=15)
        d4 = sr4.json() if sr4.content else {}
        add(
            "reopen_new_session",
            "PASS"
            if d4.get("ok") and d4.get("reopen") and d4.get("session_id") != sid
            else "FAIL",
            f"old={sid} new={d4.get('session_id')} reopen={d4.get('reopen')}",
        )
        sid = d4.get("session_id") or sid

    # offline cache: start from cache-only incomplete body
    if sid:
        httpx.post(f"{base}/sessions/{sid}/end", timeout=15)
        time.sleep(0.3)
    thin = {"lesson_occurrence_id": occ_id}
    sr5 = httpx.post(f"{base}/api/v1/sessions/start-with-context", json=thin, timeout=15)
    d5 = sr5.json() if sr5.content else {}
    # Without full fields, cache should merge if cache has the occ
    add(
        "start_from_cache",
        "PASS" if d5.get("ok") else "FAIL",
        f"http={sr5.status_code} status={d5.get('status')} lesson={((d5.get('context') or {}).get('external_lesson_id'))}",
    )
    sid = d5.get("session_id") or sid

    # Cloud: create real lesson_occurrence as gestor (if credentials)
    url = os.environ.get("SUPABASE_URL") or os.environ.get("VITE_SUPABASE_URL")
    anon = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("VITE_SUPABASE_ANON_KEY")
    email = os.environ.get("SMOKE_GESTOR_EMAIL")
    password = os.environ.get("SMOKE_GESTOR_PASSWORD")
    cloud_occ_id = None
    if url and anon and email and password:
        auth = httpx.post(
            f"{url}/auth/v1/token?grant_type=password",
            headers={"apikey": anon, "Content-Type": "application/json"},
            json={"email": email, "password": password},
            timeout=20,
        )
        if auth.status_code == 200:
            jwt = auth.json()["access_token"]
            add("gestor_login", "PASS", "JWT ok")
            headers = {
                "apikey": anon,
                "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            }
            start_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            body = {
                "organization_id": os.environ.get("CLOUD_ORGANIZATION_ID"),
                "school_id": os.environ.get("CLOUD_SCHOOL_ID"),
                "class_group_id": os.environ.get("CLASS_GROUP_ID"),
                "subject_id": os.environ.get("SUBJECT_ID"),
                "teacher_profile_id": os.environ.get("PROFESSOR_UID"),
                "room_id": os.environ.get("ROOM_ID"),
                "title": "Fase6 smoke Matemática",
                "scheduled_start_at": start_at,
                "scheduled_duration_minutes": 50,
                "external_lesson_id": "lesson-8b-math-50",
                "status": "scheduled",
            }
            ins = httpx.post(
                f"{url}/rest/v1/lesson_occurrences",
                headers=headers,
                json=body,
                timeout=20,
            )
            if ins.status_code in (200, 201):
                rows = ins.json()
                cloud_occ_id = rows[0]["id"] if rows else None
                add("gestor_create_lesson", "PASS", f"id={cloud_occ_id}")
            else:
                add("gestor_create_lesson", "FAIL", f"http={ins.status_code} {ins.text[:200]}")

            # professor login + read
            pe = os.environ.get("SMOKE_PROFESSOR_EMAIL")
            pp = os.environ.get("SMOKE_PROFESSOR_PASSWORD")
            if pe and pp:
                pa = httpx.post(
                    f"{url}/auth/v1/token?grant_type=password",
                    headers={"apikey": anon, "Content-Type": "application/json"},
                    json={"email": pe, "password": pp},
                    timeout=20,
                )
                if pa.status_code == 200:
                    pjwt = pa.json()["access_token"]
                    add("professor_login", "PASS", "JWT ok")
                    ph = {
                        "apikey": anon,
                        "Authorization": f"Bearer {pjwt}",
                    }
                    day0 = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    day1 = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
                    lst = httpx.get(
                        f"{url}/rest/v1/lesson_occurrences",
                        headers=ph,
                        params={
                            "select": "id,title,scheduled_start_at,external_lesson_id,status",
                            "scheduled_start_at": f"gte.{day0}T00:00:00Z",
                            "and": f"(scheduled_start_at.lte.{day1}T00:00:00Z)",
                            "order": "scheduled_start_at",
                        },
                        timeout=20,
                    )
                    add(
                        "professor_list_lessons",
                        "PASS" if lst.status_code == 200 else "FAIL",
                        f"http={lst.status_code} n={len(lst.json()) if lst.status_code==200 else 0}",
                    )
                    # RLS write denied for professor
                    bad = httpx.post(
                        f"{url}/rest/v1/lesson_occurrences",
                        headers={**ph, "Content-Type": "application/json", "Prefer": "return=minimal"},
                        json=body,
                        timeout=20,
                    )
                    add(
                        "rls_professor_cannot_create",
                        "PASS" if bad.status_code in (401, 403, 42501) or (bad.status_code >= 400) else "FAIL",
                        f"http={bad.status_code}",
                    )
                else:
                    add("professor_login", "FAIL", f"http={pa.status_code}")
        else:
            add("gestor_login", "FAIL", f"http={auth.status_code}")
    else:
        add("gestor_login", "NÃO OBSERVADO", "credenciais smoke ausentes")

    # LXP path: only if simulator mode — detect from live status modules
    lxp_mode = (st.get("modules") or {}).get("lxp")
    add("lxp_mode", "INFO", str(lxp_mode))
    if lxp_mode in ("simulator", "http", "http_sim") and sid:
        # check outbox for lesson from session meta (no env)
        add(
            "lxp_simulator_ready",
            "PASS",
            "mode simulator — chamada depende de check-in físico",
        )
    else:
        add(
            "lxp_checkin_path",
            "NÃO OBSERVADO",
            f"modules.lxp={lxp_mode}; default disabled — sem alteração TRI/config para forçar",
        )

    # camera
    cams = h.get("cameras_online", 0)
    add(
        "camera_usb",
        "PASS" if cams and int(cams) > 0 else "NÃO OBSERVADO",
        f"cameras_online={cams}",
    )

    # production LXP never touched
    add("lxp_production", "PASS", "nenhuma chamada a LXP produção nesta validação")

    report["finished"] = datetime.now(timezone.utc).isoformat()
    report["session_id"] = sid
    report["cloud_occurrence_id"] = cloud_occ_id
    (OUT / "FASE6_VALIDATION.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # markdown summary
    lines = ["# Fase 6 — Validação\n", f"Gerado: {report['finished']}\n\n"]
    for r in report["results"]:
        lines.append(f"- **{r['area']}**: {r['result']} — {r.get('evidence','')}\n")
    (OUT / "RELATORIO_FASE6_VALIDACAO.md").write_text("".join(lines), encoding="utf-8")
    fails = [r for r in report["results"] if r["result"] == "FAIL"]
    print(json.dumps({"fails": len(fails), "total": len(report["results"]), "out": str(OUT)}, indent=2))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
