"""Diagnose Cadastro facial empty schools dropdown via Playwright."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "diag_facial_schools"
OUT.mkdir(parents=True, exist_ok=True)

BASE = os.environ.get("PRESENCA_BASE", "https://presenca.sistemadulino.com.br")
EMAIL = os.environ.get("SMOKE_GESTOR_EMAIL", "gestor.demo@sentimentos.test")
PASSWORD = os.environ.get("SMOKE_GESTOR_PASSWORD", "")


def load_smoke_env() -> None:
    for name in (".env.smoke.local", ".env"):
        p = ROOT / name
        if not p.is_file():
            # boot loads from Presenca sibling
            p = ROOT.parent / "Presenca" / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def main() -> int:
    load_smoke_env()
    global PASSWORD, EMAIL
    EMAIL = os.environ.get("SMOKE_GESTOR_EMAIL", EMAIL)
    PASSWORD = os.environ.get("SMOKE_GESTOR_PASSWORD", PASSWORD)
    if not PASSWORD:
        print("FAIL: no SMOKE_GESTOR_PASSWORD")
        return 2

    report: dict = {"base": BASE, "email": EMAIL, "steps": [], "network": [], "console": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        def on_console(msg):
            report["console"].append({"type": msg.type, "text": msg.text})

        def on_response(resp):
            url = resp.url
            if any(
                x in url
                for x in (
                    "/gestor",
                    "/api/gestor",
                    "/m2/",
                    "m2-gestor-gate",
                    "gestor-static",
                )
            ):
                report["network"].append(
                    {"url": url, "status": resp.status, "ct": resp.headers.get("content-type", "")}
                )

        page.on("console", on_console)
        page.on("response", on_response)

        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "01_login.png"), full_page=True)

        # Login form
        if page.locator('input[type="email"], input[name="email"]').count():
            page.fill('input[type="email"], input[name="email"]', EMAIL)
            page.fill('input[type="password"]', PASSWORD)
            page.locator('button[type="submit"]').first.click()
            page.wait_for_timeout(4000)
        page.screenshot(path=str(OUT / "02_after_login.png"), full_page=True)
        report["steps"].append({"after_login_url": page.url, "body_snip": page.inner_text("body")[:500]})

        # Click Cadastro facial
        facial = page.get_by_role("button", name=re.compile("Cadastro facial", re.I))
        if facial.count() == 0:
            facial = page.locator("text=Cadastro facial")
        facial.first.click()
        # gate + fetch HTML + srcDoc boot
        page.wait_for_timeout(8000)
        page.screenshot(path=str(OUT / "03_facial_tab.png"), full_page=True)

        # Parent page state
        parent = page.evaluate(
            """() => ({
              h1: document.querySelector('h1')?.textContent,
              muted: [...document.querySelectorAll('.muted')].map(e => e.textContent),
              iframeCount: document.querySelectorAll('iframe').length,
              iframeSrc: document.querySelector('iframe')?.src || null,
            })"""
        )
        report["parent"] = parent

        frame = None
        for f in page.frames:
            u = f.url or ""
            if "/gestor" in u or u.startswith("about:srcdoc"):
                frame = f
                break
        if frame is None:
            for f in page.frames:
                if f != page.main_frame:
                    frame = f
                    break

        report["all_frames"] = [f.url for f in page.frames]

        if frame is None:
            report["iframe"] = {"error": "no_gestor_frame", "frames": [f.url for f in page.frames]}
        else:
            # wait for boot to populate schools (srcDoc + app.js)
            for _ in range(20):
                try:
                    n = frame.evaluate(
                        "() => document.getElementById('schoolSelect')?.options?.length || 0"
                    )
                    if n and n > 1:
                        break
                except Exception:
                    pass
                page.wait_for_timeout(500)
            iframe_state = frame.evaluate(
                """() => {
                  const sel = document.getElementById('schoolSelect');
                  const cls = document.getElementById('classSelect');
                  const hint = document.getElementById('setupHint');
                  const badge = document.getElementById('sourceBadge');
                  return {
                    url: location.href,
                    scripts: [...document.scripts].map(s => s.src),
                    schoolOptions: sel ? [...sel.options].map(o => ({v:o.value, t:o.textContent})) : null,
                    classOptions: cls ? [...cls.options].map(o => ({v:o.value, t:o.textContent})) : null,
                    hint: hint?.textContent || null,
                    badge: badge?.textContent || null,
                    schoolOuter: sel?.outerHTML?.slice(0, 300) || null,
                  };
                }"""
            )
            report["iframe"] = iframe_state

            # Direct fetch from inside iframe context
            try:
                fetch_result = frame.evaluate(
                    """async () => {
                      try {
                        const r = await fetch('/api/gestor/schools', {credentials:'same-origin'});
                        const text = await r.text();
                        return {status: r.status, body: text.slice(0, 800)};
                      } catch (e) {
                        return {error: String(e)};
                      }
                    }"""
                )
                report["iframe_fetch_schools"] = fetch_result
            except Exception as e:
                report["iframe_fetch_schools"] = {"eval_error": str(e)}

            # Cookie presence (names only)
            cookies = context.cookies()
            report["cookies"] = [
                {"name": c["name"], "secure": c.get("secure"), "path": c.get("path")}
                for c in cookies
                if "gestor" in c["name"] or "supabase" in c["name"].lower() or "sb-" in c["name"]
            ]

            page.screenshot(path=str(OUT / "04_iframe_state.png"), full_page=True)

            # Try select if options exist
            opts = (iframe_state or {}).get("schoolOptions") or []
            real = [o for o in opts if o.get("v")]
            if real:
                frame.select_option("#schoolSelect", real[0]["v"])
                page.wait_for_timeout(500)
                class_opts = frame.evaluate(
                    """() => [...document.getElementById('classSelect').options].map(o => ({v:o.value,t:o.textContent}))"""
                )
                report["after_school_select_classes"] = class_opts
                real_c = [o for o in class_opts if o.get("v")]
                if real_c:
                    frame.select_option("#classSelect", real_c[0]["v"])
                    page.wait_for_timeout(2000)
                    roster = frame.evaluate(
                        """() => ({
                          count: document.getElementById('studentCount')?.textContent,
                          list: document.getElementById('studentList')?.innerText?.slice(0,500),
                          hint: document.getElementById('setupHint')?.textContent,
                        })"""
                    )
                    report["after_class_select"] = roster
                page.screenshot(path=str(OUT / "05_selected.png"), full_page=True)

        (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        browser.close()

    print(json.dumps(report, indent=2, ensure_ascii=True))
    schools_ok = False
    opts = (report.get("iframe") or {}).get("schoolOptions") or []
    if any(o.get("v") for o in opts):
        schools_ok = True
    print("VERDICT:", "SCHOOLS_OK" if schools_ok else "SCHOOLS_EMPTY")
    return 0 if schools_ok else 1


if __name__ == "__main__":
    sys.exit(main())
