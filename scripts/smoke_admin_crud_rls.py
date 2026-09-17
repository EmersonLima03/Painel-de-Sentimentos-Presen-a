"""Testes de CRUD admin + RLS via Auth JWT (sem service_role no cliente).

Usa .env.smoke.local. Não imprime senhas.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments" / "smoke_e2e_sentimentos" / "admin_crud_rls_results.json"


def load_env() -> dict[str, str]:
    data: dict[str, str] = {}
    for name in (".env", ".env.smoke.local"):
        p = ROOT / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    data.update(os.environ)
    if not data.get("SUPABASE_URL"):
        data["SUPABASE_URL"] = data.get("VITE_SUPABASE_URL", "https://rmiaadljzxyehwyuhhgd.supabase.co")
    if not data.get("SUPABASE_ANON_KEY"):
        data["SUPABASE_ANON_KEY"] = data.get("VITE_SUPABASE_ANON_KEY", "")
    return data


def login(env: dict, email: str, password: str) -> str | None:
    url = f"{env['SUPABASE_URL']}/auth/v1/token?grant_type=password"
    r = httpx.post(
        url,
        headers={"apikey": env["SUPABASE_ANON_KEY"], "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    return r.json().get("access_token")


def rest(env, token, method, path, json_body=None):
    headers = {
        "apikey": env["SUPABASE_ANON_KEY"],
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    url = f"{env['SUPABASE_URL']}/rest/v1/{path}"
    r = httpx.request(method, url, headers=headers, json=json_body, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = r.text[:200]
    return r.status_code, body


def main() -> None:
    env = load_env()
    school_a = "22222222-2222-2222-2222-222222222222"
    school_b = env.get("SCHOOL_B_ID", "33333333-3333-3333-3333-333333333333")
    org = "11111111-1111-1111-1111-111111111111"
    results = []

    g = login(env, env["SMOKE_GESTOR_EMAIL"], env["SMOKE_GESTOR_PASSWORD"])
    p = login(env, env["SMOKE_PROFESSOR_EMAIL"], env["SMOKE_PROFESSOR_PASSWORD"])
    m = login(env, env["SMOKE_MONITOR_EMAIL"], env["SMOKE_MONITOR_PASSWORD"])
    results.append({"test": "login_gestor", "ok": bool(g)})
    results.append({"test": "login_professor", "ok": bool(p)})
    results.append({"test": "login_monitor", "ok": bool(m)})
    assert g and p and m, "login failed"

    # Gestor CRUD subject
    code, body = rest(
        env,
        g,
        "POST",
        "subjects",
        {
            "organization_id": org,
            "school_id": school_a,
            "name": f"CRUD Disc {uuid.uuid4().hex[:6]}",
            "is_active": True,
        },
    )
    results.append({"test": "gestor_create_subject", "ok": code in (200, 201), "http": code})
    subject_id = body[0]["id"] if isinstance(body, list) and body else None

    # Gestor create class
    code, body = rest(
        env,
        g,
        "POST",
        "class_groups",
        {
            "organization_id": org,
            "school_id": school_a,
            "name": f"CRUD Turma {uuid.uuid4().hex[:6]}",
            "year_label": "8º",
            "shift": "Manhã",
            "is_active": True,
        },
    )
    results.append({"test": "gestor_create_class", "ok": code in (200, 201), "http": code})
    class_id = body[0]["id"] if isinstance(body, list) and body else None

    # Gestor create student + enroll
    code, body = rest(
        env,
        g,
        "POST",
        "students",
        {
            "organization_id": org,
            "school_id": school_a,
            "full_name": f"Aluno CRUD {uuid.uuid4().hex[:4]}",
            "is_active": True,
        },
    )
    results.append({"test": "gestor_create_student", "ok": code in (200, 201), "http": code})
    student_id = body[0]["id"] if isinstance(body, list) and body else None

    if student_id and class_id:
        code, body = rest(
            env,
            g,
            "POST",
            "enrollments",
            {
                "organization_id": org,
                "school_id": school_a,
                "student_id": student_id,
                "class_group_id": class_id,
                "status": "active",
            },
        )
        results.append({"test": "gestor_enroll", "ok": code in (200, 201), "http": code})

    # Room
    code, body = rest(
        env,
        g,
        "POST",
        "rooms",
        {
            "organization_id": org,
            "school_id": school_a,
            "name": f"Sala CRUD {uuid.uuid4().hex[:4]}",
            "is_active": True,
        },
    )
    results.append({"test": "gestor_create_room", "ok": code in (200, 201), "http": code})
    room_id = body[0]["id"] if isinstance(body, list) and body else None

    if room_id:
        code, body = rest(
            env,
            g,
            "POST",
            "cameras",
            {
                "organization_id": org,
                "school_id": school_a,
                "room_id": room_id,
                "label": "Cam CRUD",
                "edge_camera_id": f"cam-{uuid.uuid4().hex[:8]}",
                "is_active": True,
            },
        )
        results.append({"test": "gestor_create_camera", "ok": code in (200, 201), "http": code})

    # Cross school denied
    code, body = rest(
        env,
        g,
        "POST",
        "subjects",
        {"organization_id": org, "school_id": school_b, "name": "Should Fail", "is_active": True},
    )
    results.append({"test": "gestor_denied_school_b_write", "ok": code in (401, 403), "http": code})

    code, body = rest(env, g, "GET", f"schools?id=eq.{school_b}&select=id")
    results.append({"test": "gestor_denied_school_b_read", "ok": code == 200 and body == [], "rows": body})

    # Professor cannot create subject
    code, _ = rest(
        env,
        p,
        "POST",
        "subjects",
        {"organization_id": org, "school_id": school_a, "name": "Prof Fail", "is_active": True},
    )
    results.append({"test": "professor_cannot_write_subject", "ok": code in (401, 403), "http": code})

    # Monitor cannot create student
    code, _ = rest(
        env,
        m,
        "POST",
        "students",
        {"organization_id": org, "school_id": school_a, "full_name": "Mon Fail", "is_active": True},
    )
    results.append({"test": "monitor_cannot_write_student", "ok": code in (401, 403), "http": code})

    # Professor can read assigned class (seed 3f4b...)
    code, body = rest(env, p, "GET", "class_groups?select=id,name")
    ids = [r["id"] for r in body] if isinstance(body, list) else []
    results.append(
        {
            "test": "professor_reads_assigned_only",
            "ok": code == 200 and "3f4b690c-d809-4dbb-a471-f5b93db84e1e" in ids,
            "ids": ids,
        }
    )

    # Assign teacher to new class if possible
    if class_id and subject_id:
        prof_uid = env.get("PROFESSOR_UID", "994126e2-f0b7-544e-867e-0f580f256f8e")
        code, body = rest(
            env,
            g,
            "POST",
            "teacher_assignments",
            {
                "organization_id": org,
                "school_id": school_a,
                "class_group_id": class_id,
                "profile_id": prof_uid,
                "subject_id": subject_id,
                "is_primary": True,
            },
        )
        results.append({"test": "gestor_assign_teacher", "ok": code in (200, 201), "http": code})

    report = {"results": results, "pass": all(r.get("ok") for r in results)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
