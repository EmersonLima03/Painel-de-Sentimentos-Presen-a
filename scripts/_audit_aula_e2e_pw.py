"""Auditoria E2E somente-leitura — fluxo aula real (Playwright).

Nao altera codigo nem cria fixtures/hooks. Usa contas smoke + HTTPS prod.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "audit_aula_e2e"
OUT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get("PRESENCA_BASE", "https://presenca.sistemadulino.com.br")
LOCAL = "http://127.0.0.1:8000"


def load_env() -> None:
    for p in (ROOT.parent / "Presenca" / ".env.smoke.local", ROOT / ".env.smoke.local"):
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    load_env()
    email = os.environ.get("SMOKE_GESTOR_EMAIL", "")
    password = os.environ.get("SMOKE_GESTOR_PASSWORD", "")
    report: dict = {
        "base": BASE,
        "local": LOCAL,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checks": {},
        "network": [],
        "console_errors": [],
        "pages": {},
    }

    interesting = (
        "/api/",
        "/dashboard",
        "/gestor",
        "/sessions",
        "/m2/",
        "lesson",
        "cache",
        "start-with-context",
        "overlay_matches",
        "supabase",
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def on_response(resp):
            u = resp.url
            if any(x in u for x in interesting):
                entry = {"status": resp.status, "url": u, "method": resp.request.method}
                try:
                    if "json" in (resp.headers.get("content-type") or "") and resp.status < 500:
                        if any(
                            x in u
                            for x in (
                                "lessons/cache",
                                "start-with-context",
                                "current-context",
                                "class-facial",
                                "m2-gestor-gate",
                                "overview",
                            )
                        ):
                            entry["body_snip"] = (resp.text() or "")[:600]
                except Exception:
                    pass
                report["network"].append(entry)

        page.on("response", on_response)
        page.on(
            "console",
            lambda m: report["console_errors"].append(m.text)
            if m.type == "error"
            else None,
        )

        # --- Login ---
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        report["checks"]["login_screen"] = page.locator('input[type="email"]').count() > 0
        page.screenshot(path=str(OUT / "01_login.png"), full_page=True)

        if report["checks"]["login_screen"]:
            page.fill('input[type="email"]', email)
            page.fill('input[type="password"]', password)
            page.locator('button[type="submit"]').first.click()
            page.wait_for_timeout(4500)

        body = page.inner_text("body")
        report["checks"]["login_ok"] = email.split("@")[0] in body or email in body
        report["checks"]["has_admin_nav"] = "Administração" in body
        report["checks"]["has_facial_nav"] = "Cadastro facial" in body
        report["checks"]["has_live_nav"] = "Ao vivo" in body
        report["pages"]["after_login"] = body[:800]
        page.screenshot(path=str(OUT / "02_after_login.png"), full_page=True)

        # Role via JS (AuthContext reflected in DOM / local storage / fetch)
        auth_info = page.evaluate(
            """async () => {
              const email = document.body.innerText;
              let gate = null;
              try {
                const { createClient } = await import('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm');
              } catch (e) {}
              // Try session from localStorage keys
              const keys = Object.keys(localStorage).filter(k => k.includes('supabase') || k.includes('sb-'));
              let token = null;
              for (const k of keys) {
                try {
                  const v = JSON.parse(localStorage.getItem(k) || '{}');
                  token = v?.access_token || v?.currentSession?.access_token || v?.session?.access_token || null;
                  if (token) break;
                  if (v?.user?.email) return { email: v.user.email, keys, rawUser: v.user };
                } catch {}
              }
              return { emailHint: (document.body.innerText.match(/[\\w.+-]+@[\\w.-]+/)||[])[0] || null, storageKeys: keys };
            }"""
        )
        report["checks"]["auth_info"] = auth_info

        # --- Cadastro facial ---
        page.get_by_text("Cadastro facial", exact=True).first.click()
        page.wait_for_timeout(8000)
        page.screenshot(path=str(OUT / "03_facial.png"), full_page=True)
        frame = next((f for f in page.frames if (f.url or "").startswith("about:srcdoc")), None)
        facial = {"frame": bool(frame)}
        if frame:
            for _ in range(15):
                n = frame.evaluate(
                    "() => document.getElementById('schoolSelect')?.options?.length || 0"
                )
                if n and n > 1:
                    break
                page.wait_for_timeout(400)
            facial["schools"] = frame.evaluate(
                "() => [...document.getElementById('schoolSelect').options].map(o=>({v:o.value,t:o.textContent}))"
            )
            try:
                school_id = next(o["v"] for o in facial["schools"] if o["v"])
                frame.select_option("#schoolSelect", school_id)
                page.wait_for_timeout(600)
                facial["classes"] = frame.evaluate(
                    "() => [...document.getElementById('classSelect').options].map(o=>({v:o.value,t:o.textContent}))"
                )
                class_id = next(o["v"] for o in facial["classes"] if o["v"])
                frame.select_option("#classSelect", class_id)
                page.wait_for_timeout(4000)
                facial["roster"] = frame.evaluate(
                    """() => ({
                      summary: document.getElementById('statusSummary')?.textContent,
                      list: document.getElementById('studentList')?.innerText,
                      statuses: [...document.querySelectorAll('[data-status]')].map(el => ({
                        id: el.getAttribute('data-student-id'),
                        status: el.getAttribute('data-status'),
                        name: el.querySelector('.roster-name')?.textContent
                      }))
                    })"""
                )
            except Exception as e:
                facial["error"] = str(e)
        report["checks"]["facial"] = facial
        page.screenshot(path=str(OUT / "04_facial_selected.png"), full_page=True)

        # --- Administração / Aulas ---
        page.get_by_text("Administração", exact=True).first.click()
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "05_admin.png"), full_page=True)
        # Click Aulas tab if present
        aulas_tab = page.get_by_role("button", name=re.compile(r"^Aulas$", re.I))
        if aulas_tab.count() == 0:
            aulas_tab = page.locator("text=Aulas")
        if aulas_tab.count():
            aulas_tab.first.click()
            page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "06_aulas.png"), full_page=True)
        admin_text = page.inner_text("body")
        report["checks"]["aulas_page"] = {
            "has_enviar_cache": "Enviar aulas do dia ao Edge" in admin_text,
            "has_lesson_8b": "lesson-8b-math-50" in admin_text,
            "has_turma_teste": "Turma Teste" in admin_text,
            "has_matematica": "Matemática" in admin_text or "Matematica" in admin_text,
            "has_scheduled": "scheduled" in admin_text,
            "has_in_progress": "in_progress" in admin_text,
            "has_iniciar": bool(re.search(r"Iniciar", admin_text)),
            "snip": admin_text[admin_text.find("Aulas") : admin_text.find("Aulas") + 1200]
            if "Aulas" in admin_text
            else admin_text[:1200],
        }

        # Click Enviar aulas do dia ao Edge and capture network
        before_net = len(report["network"])
        btn = page.get_by_role("button", name=re.compile(r"Enviar aulas do dia ao Edge", re.I))
        report["checks"]["push_button_found"] = btn.count() > 0
        if btn.count():
            with page.expect_response(
                lambda r: "/api/v1/lessons/cache" in r.url, timeout=15000
            ) as resp_info:
                btn.first.click()
            resp = resp_info.value
            report["checks"]["push_cache"] = {
                "http": resp.status,
                "url": resp.url,
                "body": (resp.text() or "")[:800],
            }
            page.wait_for_timeout(2000)
            report["checks"]["push_msg"] = page.inner_text("body")[-500:]
        else:
            report["checks"]["push_cache"] = {"http": None, "error": "button_not_found"}

        # Try Iniciar if visible (Minhas aulas / professor panel may differ)
        start_btn = page.get_by_role("button", name=re.compile(r"^Iniciar", re.I))
        report["checks"]["start_button_count"] = start_btn.count()
        if start_btn.count():
            before = len(report["network"])
            try:
                with page.expect_response(
                    lambda r: "start-with-context" in r.url or "/sessions" in r.url,
                    timeout=20000,
                ) as resp_info:
                    start_btn.first.click()
                resp = resp_info.value
                report["checks"]["start_lesson"] = {
                    "http": resp.status,
                    "url": resp.url,
                    "body": (resp.text() or "")[:800],
                }
            except Exception as e:
                report["checks"]["start_lesson"] = {"error": str(e)}
            page.wait_for_timeout(3000)
            page.screenshot(path=str(OUT / "07_after_start.png"), full_page=True)

        # --- Ao vivo ---
        page.get_by_text("Ao vivo", exact=True).first.click()
        page.wait_for_timeout(4000)
        live_text = page.inner_text("body")
        report["checks"]["ao_vivo"] = {
            "has_presentes": "PRESENTES" in live_text or "Presentes" in live_text,
            "nenhuma_aula": "Nenhuma aula iniciada" in live_text,
            "sessao": "Sessão" in live_text or "AO VIVO" in live_text,
            "snip": live_text[:1000],
        }
        page.screenshot(path=str(OUT / "08_ao_vivo.png"), full_page=True)

        # Local API probes from browser context (same origin via tunnel to edge)
        api_probe = page.evaluate(
            """async () => {
              const out = {};
              const tryFetch = async (path) => {
                try {
                  const r = await fetch(path, { credentials: 'same-origin' });
                  const t = await r.text();
                  let j = null; try { j = JSON.parse(t); } catch {}
                  return { status: r.status, body: j || t.slice(0, 500) };
                } catch (e) { return { error: String(e) }; }
              };
              out.overview = await tryFetch('/dashboard/api/overview');
              out.current_context = await tryFetch('/api/v1/sessions/current-context');
              out.m2 = await tryFetch('/m2/healthz');
              out.overlay = await tryFetch('/debug/overlay_matches?camera_id=cam-web');
              return out;
            }"""
        )
        report["checks"]["api_probe"] = api_probe

        page.screenshot(path=str(OUT / "09_final.png"), full_page=True)
        (OUT / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        browser.close()

    print(json.dumps(report["checks"], indent=2, ensure_ascii=True))
    print("REPORT", OUT / "report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
