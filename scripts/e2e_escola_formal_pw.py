"""E2E escolar real — gestor inicia aula formal → Ao vivo → LXP.

Não usa mocks, force-step nem fixtures de presença.
Requer Edge+M2+Tunnel bootados e Emerson com face cadastrada.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "e2e_escola_formal"
OUT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get("PRESENCA_BASE", "https://presenca.sistemadulino.com.br")
LOCAL = os.environ.get("PRESENCA_LOCAL", "http://127.0.0.1:8000")


def load_env() -> None:
    for p in (
        ROOT.parent / "Presenca" / ".env.smoke.local",
        ROOT.parent / "Presenca" / ".env",
        ROOT / ".env.smoke.local",
        ROOT / ".env",
    ):
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api_get(path: str) -> dict:
    r = httpx.get(f"{LOCAL}{path}", timeout=20.0)
    r.raise_for_status()
    return r.json()


def wait_until(fn, timeout_s: float = 90.0, interval: float = 2.0, label: str = "cond"):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timeout waiting for {label}: last={last!r}")


def main() -> int:
    load_env()
    email = os.environ["SMOKE_GESTOR_EMAIL"]
    password = os.environ["SMOKE_GESTOR_PASSWORD"]
    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base": BASE,
        "phases": {},
        "ok": False,
    }

    # Pré-checagens
    health = api_get("/health")
    assert health.get("status") == "ok", health
    assert health.get("faiss_enabled") is True
    m2 = api_get("/m2/healthz")
    assert m2.get("ok") is True
    report["phases"]["preflight"] = {
        "edge": True,
        "faiss": True,
        "m2": True,
        "embeddings": (health.get("presence_debug") or {}).get("matcher_embeddings"),
    }

    start_resp = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True, viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        network: list[dict] = []

        def on_response(resp):
            u = resp.url
            if any(
                x in u
                for x in (
                    "start-with-context",
                    "lessons/cache",
                    "current-context",
                    "live/status",
                    "homolog",
                )
            ):
                entry = {"status": resp.status, "url": u, "method": resp.request.method}
                try:
                    if "json" in (resp.headers.get("content-type") or ""):
                        entry["body"] = resp.json()
                except Exception:
                    pass
                network.append(entry)

        page.on("response", on_response)

        # --- Cenário 1: Login gestor + iniciar aula ---
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)
        # Login wall
        if page.locator('input[type="email"], input[name="email"]').count():
            page.fill('input[type="email"], input[name="email"]', email)
            page.fill('input[type="password"], input[name="password"]', password)
            login_btn = page.get_by_role("button", name="Entrar")
            if login_btn.count() == 0:
                login_btn = page.locator('button[type="submit"]')
            login_btn.first.click()
            page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "01_after_login.png"), full_page=True)

        # Administração → Aulas (evita encoding quebrado de "Administração" no shell)
        page.locator("button.sidebar-item, button", has_text="Administra").first.click()
        page.wait_for_timeout(800)
        page.locator("button", has_text="Aulas").first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "02_aulas.png"), full_page=True)

        # Garantir cache + iniciar primeira aula do dia
        cache_btn = page.locator("button", has_text="Enviar aulas do dia ao Edge")
        if cache_btn.count():
            cache_btn.first.click()
            page.wait_for_timeout(2000)

        start_btn = page.locator("button.btn.primary", has_text="Iniciar aula").first
        assert start_btn.count() >= 1, "Botão Iniciar aula ausente para gestor"
        start_btn.click()
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / "03_after_start.png"), full_page=True)

        # Capturar resposta start-with-context
        for n in reversed(network):
            if "start-with-context" in n.get("url", "") and n.get("status") == 200:
                start_resp = n.get("body") or {}
                break
        report["phases"]["gestor_start"] = {
            "ui_clicked": True,
            "http": start_resp,
            "network_hits": [n for n in network if "start-with-context" in n.get("url", "")],
        }
        assert start_resp.get("ok") is True or start_resp.get("session_id"), start_resp

        # --- Cenário 2: Ao vivo ---
        page.get_by_role("button", name="Ao vivo").click()
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUT / "04_ao_vivo.png"), full_page=True)

        def _ctx_ready():
            c = api_get("/api/v1/sessions/current-context")
            if (c.get("context") or {}).get("lesson_occurrence_id"):
                return c
            return None

        ctx = wait_until(_ctx_ready, timeout_s=45, label="lesson_context")
        live = api_get("/api/v1/live/status")
        summary = api_get("/api/v1/live/classroom-summary")
        report["phases"]["ao_vivo"] = {
            "current_context": ctx,
            "lesson_context": live.get("lesson_context"),
            "session_title": (ctx or {}).get("title"),
            "classroom_summary_keys": list(summary.keys())[:20] if isinstance(summary, dict) else None,
        }
        assert (ctx.get("context") or {}).get("lesson_occurrence_id")
        assert live.get("lesson_context")
        assert "Sessão automática" not in str(ctx.get("title") or "")

        # Esperar Emerson / presença (câmera real)
        def presence_ok():
            st = api_get("/api/v1/live/status")
            kpis = st.get("kpis") or {}
            present = kpis.get("recognized_people") or kpis.get("present") or 0
            matches = st.get("overlay_matches") or st.get("debug", {}).get("overlay_matches") or []
            try:
                ov = api_get("/dashboard/api/overview")
            except Exception:
                ov = {}
            result = {
                "present": present,
                "matches": matches,
                "overview_present": (ov.get("kpis") or {}).get("present"),
                "ok": int(present or 0) >= 1
                or any("p01" in str(m) for m in (matches if isinstance(matches, list) else [])),
            }
            return result if result["ok"] else None

        presence = wait_until(presence_ok, timeout_s=120, label="presence_p01")
        report["phases"]["presenca"] = presence

        # TRI / engajamento sinal presente no live status
        live2 = api_get("/api/v1/live/status")
        report["phases"]["tri"] = {
            "has_kpis": bool(live2.get("kpis")),
            "pipeline_hints": {
                "detector": health.get("detector_backend"),
                "embedder": health.get("embedder_backend"),
                "faiss": health.get("faiss_enabled"),
            },
            "kpis_sample": {k: live2.get("kpis", {}).get(k) for k in list((live2.get("kpis") or {}).keys())[:12]},
        }

        page.screenshot(path=str(OUT / "05_ao_vivo_presence.png"), full_page=True)

        # Relatórios
        page.get_by_role("button", name="Relatórios").click()
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "06_relatorios.png"), full_page=True)
        report["phases"]["relatorios"] = {"opened": True}

        # --- Cenário 3: LXP Homologação ---
        page.get_by_role("button", name="LXP Homologação").click()
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUT / "07_lxp.png"), full_page=True)
        body_text = page.inner_text("body")
        report["phases"]["lxp_ui"] = {
            "has_ext_stu": "ext-stu-001" in body_text or "Emerson" in body_text or "present" in body_text.lower(),
            "snippet": body_text[:800],
        }

        browser.close()

    # APIs / outbox / LXP após UI
    sid = (start_resp.get("session_id") or (report["phases"]["ao_vivo"]["current_context"] or {}).get("session_id"))
    report["phases"]["session_id"] = sid

    # Dar tempo ao SyncWorker
    time.sleep(8)
    try:
        homolog = api_get("/api/v1/homolog/lxp")
    except Exception as e:
        homolog = {"error": str(e)}
    report["phases"]["lxp_api"] = homolog

    # Critério mínimo LXP: evento enfileirado OU registro no simulador
    lxp_ok = False
    if isinstance(homolog, dict):
        blob = json.dumps(homolog, ensure_ascii=False)
        lxp_ok = ("ext-stu-001" in blob) or ("lesson-8b-math-50" in blob) or ("attendance" in blob.lower())
    report["phases"]["lxp_ok"] = lxp_ok

    report["ok"] = bool(
        report["phases"].get("gestor_start")
        and report["phases"]["ao_vivo"].get("lesson_context")
        and report["phases"].get("presenca")
        and report["phases"].get("tri", {}).get("has_kpis")
    )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "out": str(OUT), "lxp_ok": lxp_ok, "session_id": sid}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        err = {"ok": False, "error": str(e)}
        (OUT / "report.json").write_text(json.dumps(err, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(err, indent=2), file=sys.stderr)
        raise
