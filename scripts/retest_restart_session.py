"""Atualiza smoke de restart: espera sessão bound (= SQLite active)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments" / "smoke_e2e_sentimentos" / "e2e_validation"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000"


def sqlite_active() -> str | None:
    con = sqlite3.connect(str(ROOT / "data" / "dulino_edge.db"))
    try:
        row = con.execute(
            "select session_id from class_sessions where status='active' order by started_at desc limit 1"
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def wait_bound_session(timeout: float = 90.0) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            live = httpx.get(f"{BASE}/api/v1/live/status", timeout=5).json()
            sid = (live.get("session") or {}).get("session_id")
            if sid:
                return sid
            sess = httpx.get(f"{BASE}/api/v1/sessions", timeout=5).json()
            items = sess.get("sessions") or []
            if items and items[0].get("session_id") and items[0].get("bound", True):
                return items[0]["session_id"]
        except Exception:
            pass
        time.sleep(1.0)
    return None


def main() -> None:
    pre_sql = sqlite_active()
    pre_live = wait_bound_session(30)
    print("PRE_SQL", pre_sql, "PRE_LIVE", pre_live)

    out = subprocess.check_output("netstat -ano", shell=True, text=True, errors="ignore")
    pids = {line.split()[-1] for line in out.splitlines() if ":8000" in line and "LISTENING" in line}
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
    time.sleep(2)

    log = OUT / "uvicorn_restart.log"
    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(ROOT),
        stdout=open(log, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    # health
    for _ in range(40):
        try:
            if httpx.get(f"{BASE}/health", timeout=2).status_code == 200:
                break
        except Exception:
            time.sleep(1)

    # Critério: session_id já no primeiro /sessions após health (bootstrap síncrono)
    immediate = None
    try:
        immediate = httpx.get(f"{BASE}/api/v1/sessions", timeout=5).json()["sessions"][0]["session_id"]
    except Exception:
        pass
    post_live = wait_bound_session(60)
    post_sql = sqlite_active()

    same = bool(pre_sql and post_sql == pre_sql and post_live == pre_sql)
    report = {
        "pre_sql": pre_sql,
        "pre_live": pre_live,
        "immediate_after_health": immediate,
        "post_live": post_live,
        "post_sql": post_sql,
        "same_session_preserved": same,
        "uvicorn_pid": proc.pid,
    }
    (OUT / "restart_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not same:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
