"""Smoke Auth + RLS via Supabase REST (anon + user JWT).

Não imprime senhas. Resultados em experiments/smoke_e2e_sentimentos/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments" / "smoke_e2e_sentimentos"
OUT.mkdir(parents=True, exist_ok=True)


def load_env() -> dict[str, str]:
    data: dict[str, str] = {}
    for name in (".env", ".env.smoke.local"):
        p = ROOT / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    data.update({k: v for k, v in os.environ.items() if k in data or k.startswith("SMOKE_") or k.startswith("VITE_") or k.startswith("SUPABASE_")})
    return data


def login(env: dict, email: str, password: str) -> str | None:
    url = f"{env.get('SUPABASE_URL') or env.get('VITE_SUPABASE_URL')}/auth/v1/token?grant_type=password"
    headers = {"apikey": env["SUPABASE_ANON_KEY"], "Content-Type": "application/json"}
    r = httpx.post(url, headers=headers, json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get("access_token")


def rest_get(env: dict, token: str, path: str) -> tuple[int, object]:
    base = env.get("SUPABASE_URL") or env.get("VITE_SUPABASE_URL")
    headers = {
        "apikey": env["SUPABASE_ANON_KEY"],
        "Authorization": f"Bearer {token}",
    }
    r = httpx.get(f"{base}/rest/v1/{path}", headers=headers, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = r.text[:200]
    return r.status_code, body


def main() -> None:
    env = load_env()
    # ensure project URL
    if not env.get("SUPABASE_URL"):
        env["SUPABASE_URL"] = env.get("VITE_SUPABASE_URL", "https://rmiaadljzxyehwyuhhgd.supabase.co")
    results = []

    roles = [
        ("gestor", env["SMOKE_GESTOR_EMAIL"], env["SMOKE_GESTOR_PASSWORD"]),
        ("professor", env["SMOKE_PROFESSOR_EMAIL"], env["SMOKE_PROFESSOR_PASSWORD"]),
        ("monitor", env["SMOKE_MONITOR_EMAIL"], env["SMOKE_MONITOR_PASSWORD"]),
    ]
    tokens: dict[str, str] = {}
    for role, email, pw in roles:
        tok = login(env, email, pw)
        results.append({"test": f"login_{role}", "ok": bool(tok), "email": email})
        if tok:
            tokens[role] = tok

    school_a = "22222222-2222-2222-2222-222222222222"
    school_b = env.get("SCHOOL_B_ID", "33333333-3333-3333-3333-333333333333")

    if "gestor" in tokens:
        code, body = rest_get(env, tokens["gestor"], "schools?select=id,name")
        names = [r["name"] for r in body] if isinstance(body, list) else []
        results.append(
            {
                "test": "gestor_sees_school_a",
                "ok": code == 200 and any("Demo" in n for n in names),
                "schools": names,
            }
        )
        code_b, body_b = rest_get(env, tokens["gestor"], f"schools?id=eq.{school_b}&select=id,name")
        # RLS should return empty for school B (no membership)
        results.append(
            {
                "test": "gestor_denied_school_b",
                "ok": code_b == 200 and body_b == [],
                "http": code_b,
                "rows": body_b if isinstance(body_b, list) else str(body_b)[:100],
            }
        )
        code_s, body_s = rest_get(
            env,
            tokens["gestor"],
            "class_sessions?select=id,title,status&order=started_at.desc&limit=5",
        )
        results.append(
            {
                "test": "gestor_history_sessions",
                "ok": code_s == 200 and isinstance(body_s, list) and len(body_s) > 0,
                "count": len(body_s) if isinstance(body_s, list) else 0,
                "titles": [r.get("title") for r in body_s] if isinstance(body_s, list) else [],
            }
        )
        # write attempt on school B subjects should fail
        base = env["SUPABASE_URL"]
        r = httpx.post(
            f"{base}/rest/v1/subjects",
            headers={
                "apikey": env["SUPABASE_ANON_KEY"],
                "Authorization": f"Bearer {tokens['gestor']}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={
                "organization_id": "11111111-1111-1111-1111-111111111111",
                "school_id": school_b,
                "name": "Should Fail",
            },
            timeout=30,
        )
        results.append(
            {
                "test": "gestor_cannot_write_school_b",
                "ok": r.status_code in (401, 403) or (r.status_code >= 400),
                "http": r.status_code,
            }
        )

    if "professor" in tokens:
        code, body = rest_get(
            env,
            tokens["professor"],
            "class_groups?select=id,name,school_id",
        )
        ids = [r["id"] for r in body] if isinstance(body, list) else []
        results.append(
            {
                "test": "professor_only_assigned_classes",
                "ok": code == 200
                and "3f4b690c-d809-4dbb-a471-f5b93db84e1e" in ids
                and "44444444-4444-4444-4444-444444444444" not in ids,
                "class_ids": ids,
            }
        )
        code_b, body_b = rest_get(env, tokens["professor"], f"schools?id=eq.{school_b}&select=id")
        results.append({"test": "professor_denied_school_b", "ok": code_b == 200 and body_b == [], "rows": body_b})

    if "monitor" in tokens:
        # monitor can select class_groups in school but cannot write students
        base = env["SUPABASE_URL"]
        r = httpx.post(
            f"{base}/rest/v1/students",
            headers={
                "apikey": env["SUPABASE_ANON_KEY"],
                "Authorization": f"Bearer {tokens['monitor']}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={
                "organization_id": "11111111-1111-1111-1111-111111111111",
                "school_id": school_a,
                "full_name": "Aluno Indevido",
            },
            timeout=30,
        )
        results.append(
            {
                "test": "monitor_cannot_write_students",
                "ok": r.status_code in (401, 403) or r.status_code >= 400,
                "http": r.status_code,
            }
        )
        code, body = rest_get(env, tokens["monitor"], "schools?select=name")
        results.append(
            {
                "test": "monitor_can_read_school",
                "ok": code == 200 and isinstance(body, list) and len(body) >= 1,
                "schools": body,
            }
        )

    report = {"results": results, "pass": all(r.get("ok") for r in results)}
    (OUT / "auth_rls_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
