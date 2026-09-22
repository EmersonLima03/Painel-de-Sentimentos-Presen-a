"""E2E Playwright: Cadastro facial gestor — escola/turma/status Emerson enrolled."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "e2e_facial_promote"
OUT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get("PRESENCA_BASE", "https://presenca.sistemadulino.com.br")
SCHOOL = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
CLASS = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1"


def load_env() -> None:
    for name in (ROOT.parent / "Presenca" / ".env.smoke.local", ROOT / ".env.smoke.local"):
        if not name.is_file():
            continue
        for line in name.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    load_env()
    email = os.environ["SMOKE_GESTOR_EMAIL"]
    password = os.environ["SMOKE_GESTOR_PASSWORD"]
    report: dict = {"checks": {}, "network": [], "console": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(ignore_https_errors=True)

        page.on(
            "response",
            lambda r: report["network"].append({"status": r.status, "url": r.url})
            if any(x in r.url for x in ("/gestor", "/api/gestor", "m2-gestor", "class-facial"))
            else None,
        )
        page.on(
            "console",
            lambda m: report["console"].append({"type": m.type, "text": m.text})
            if m.type in ("error", "warning")
            else None,
        )

        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded", timeout=60000)
        page.fill('input[type="email"]', email)
        page.fill('input[type="password"]', password)
        page.locator('button[type="submit"]').first.click()
        page.wait_for_timeout(4000)
        report["checks"]["login_ok"] = "Cadastro facial" in page.inner_text("body")

        page.get_by_text("Cadastro facial", exact=True).first.click()
        page.wait_for_timeout(7000)
        page.screenshot(path=str(OUT / "01_facial.png"), full_page=True)

        frame = next((f for f in page.frames if (f.url or "").startswith("about:srcdoc")), None)
        report["checks"]["srcdoc_frame"] = frame is not None
        if not frame:
            (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2, ensure_ascii=True))
            print("VERDICT: FAIL no srcdoc")
            return 1

        # wait schools
        for _ in range(20):
            n = frame.evaluate("() => document.getElementById('schoolSelect')?.options?.length || 0")
            if n > 1:
                break
            page.wait_for_timeout(400)

        opts = frame.evaluate(
            "() => [...document.getElementById('schoolSelect').options].map(o => ({v:o.value,t:o.textContent}))"
        )
        report["checks"]["schools"] = opts
        report["checks"]["has_escola_e2e"] = any(o.get("v") == SCHOOL for o in opts)

        frame.select_option("#schoolSelect", SCHOOL)
        page.wait_for_timeout(500)
        frame.select_option("#classSelect", CLASS)
        page.wait_for_timeout(5000)
        page.screenshot(path=str(OUT / "02_selected.png"), full_page=True)

        state = frame.evaluate(
            """() => {
              const row = document.querySelector('[data-student-id]');
              return {
                count: document.getElementById('studentCount')?.textContent,
                summary: document.getElementById('statusSummary')?.textContent,
                list: document.getElementById('studentList')?.innerText,
                status: row?.getAttribute('data-status') || null,
                name: row?.querySelector('.roster-name')?.textContent || null,
                badge: document.getElementById('sourceBadge')?.textContent,
              };
            }"""
        )
        report["checks"]["roster"] = state
        report["checks"]["emerson_enrolled"] = (
            (state.get("name") or "").lower().find("emerson") >= 0
            and state.get("status") == "enrolled"
        )
        report["checks"]["summary_has_cadastrado"] = "1 cadastrado" in (state.get("summary") or "")

        # API direct from frame
        api = frame.evaluate(
            f"""async () => {{
              const r = await fetch('/api/gestor/class-facial-status?school_id={SCHOOL}&class_group_id={CLASS}', {{credentials:'same-origin'}});
              return {{status: r.status, body: await r.json()}};
            }}"""
        )
        report["checks"]["api_status"] = api

        page.screenshot(path=str(OUT / "03_final.png"), full_page=True)
        (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        browser.close()

    ok = all(
        [
            report["checks"].get("login_ok"),
            report["checks"].get("srcdoc_frame"),
            report["checks"].get("has_escola_e2e"),
            report["checks"].get("emerson_enrolled"),
        ]
    )
    print(json.dumps(report["checks"], indent=2, ensure_ascii=True))
    print("VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
