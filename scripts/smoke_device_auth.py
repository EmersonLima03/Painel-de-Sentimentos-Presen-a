"""Smoke: autenticação do device + idempotência contra ingest-events.

Lê .env / .env.smoke.local. Não imprime tokens.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


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
    # process env overrides
    for k, v in os.environ.items():
        if k in data or k.startswith(("DEVICE_", "SUPABASE_", "CLOUD_")):
            data[k] = v
    return data


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def post(env: dict[str, str], token: str, payload: dict) -> tuple[int, dict]:
    url = env["SUPABASE_INGEST_URL"]
    headers = {
        "Content-Type": "application/json",
        "apikey": env["SUPABASE_ANON_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_ANON_KEY']}",
    }
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}token={token}"
    r = httpx.post(full, headers=headers, json=payload, timeout=30.0)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:300]}
    return r.status_code, body


def main() -> None:
    env = load_env()
    token = env["DEVICE_TOKEN"]
    org = env["CLOUD_ORGANIZATION_ID"]
    school = env["CLOUD_SCHOOL_ID"]
    school_b = env.get("SCHOOL_B_ID", "33333333-3333-3333-3333-333333333333")
    results: list[dict] = []

    # TEST 1 valid token heartbeat
    eid = str(uuid.uuid4())
    code, body = post(
        env,
        token,
        {
            "event_id": eid,
            "event_type": "device_heartbeat",
            "last_seen_at": now_iso(),
            "app_version": "smoke-1",
        },
    )
    results.append({"test": "T1_valid_token", "http": code, "status": body.get("status"), "ok": code == 200 and body.get("ok")})

    # TEST 2 invalid token
    code, body = post(
        env,
        "invalid-token-xyz",
        {"event_id": str(uuid.uuid4()), "event_type": "device_heartbeat", "last_seen_at": now_iso()},
    )
    results.append({"test": "T2_invalid_token", "http": code, "status": body.get("status"), "ok": code in (401, 403)})

    # TEST 3 revoked — handled later after revoke SQL; placeholder mark
    results.append({"test": "T3_revoked_token", "http": None, "status": "pending_sql_revoke", "ok": None})

    # TEST 4 school mismatch
    sid = str(uuid.uuid4())
    code, body = post(
        env,
        token,
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "class_session_upsert",
            "session": {
                "id": sid,
                "organization_id": org,
                "school_id": school_b,
                "title": "cross-school-should-fail",
                "status": "active",
                "started_at": now_iso(),
                "source_device_id": env.get("DEVICE_ID", "edge-demo-001"),
            },
        },
    )
    results.append({"test": "T4_school_mismatch", "http": code, "status": body.get("status"), "error": body.get("error"), "ok": code == 403})

    # TEST 5 duplicate event
    session_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    sess_payload = {
        "event_id": f"session:{session_id}",
        "event_type": "class_session_upsert",
        "session": {
            "id": session_id,
            "organization_id": org,
            "school_id": school,
            "title": "Smoke Online Session",
            "status": "active",
            "started_at": now_iso(),
            "source_device_id": env.get("DEVICE_ID", "edge-demo-001"),
        },
    }
    code1, body1 = post(env, token, sess_payload)
    code2, body2 = post(env, token, sess_payload)
    # same session_event twice
    ev_payload = {
        "event_id": event_id,
        "event_type": "session_event_upsert",
        "session_event": {
            "id": event_id,
            "session_id": session_id,
            "organization_id": org,
            "school_id": school,
            "event_type": "attention_drop",
            "opened_at": now_iso(),
            "status": "open",
            "payload": {"smoke": True},
        },
    }
    code3, body3 = post(env, token, ev_payload)
    code4, body4 = post(env, token, ev_payload)

    snap_id = str(uuid.uuid4())
    captured = now_iso()
    snap_payload = {
        "event_id": f"snap:{session_id}:{captured}",
        "event_type": "session_report_snapshot",
        "snapshot": {
            "id": snap_id,
            "session_id": session_id,
            "organization_id": org,
            "school_id": school,
            "captured_at": captured,
            "schema_version": 1,
            "is_final": False,
            "report": {"attention_now": 0.7, "smoke": True},
            "source_device_id": env.get("DEVICE_ID", "edge-demo-001"),
        },
    }
    code5, body5 = post(env, token, snap_payload)
    code6, body6 = post(env, token, snap_payload)

    results.append(
        {
            "test": "T5_idempotent_session",
            "first": {"http": code1, "status": body1.get("status")},
            "second": {"http": code2, "status": body2.get("status")},
            "session_id": session_id,
            "ok": code1 == 200 and code2 == 200,
        }
    )
    results.append(
        {
            "test": "T5_idempotent_event",
            "first": {"http": code3, "status": body3.get("status")},
            "second": {"http": code4, "status": body4.get("status")},
            "event_id": event_id,
            "ok": code3 == 200 and code4 == 200,
        }
    )
    results.append(
        {
            "test": "T5_idempotent_snapshot",
            "first": {"http": code5, "status": body5.get("status")},
            "second": {"http": code6, "status": body6.get("status")},
            "snapshot_id": snap_id,
            "ok": code5 == 200 and code6 == 200,
        }
    )

    out = ROOT / "experiments" / "smoke_e2e_sentimentos"
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "results": results,
        "ids": {"session_id": session_id, "event_id": event_id, "snapshot_id": snap_id, "captured_at": captured},
    }
    (out / "device_auth_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
