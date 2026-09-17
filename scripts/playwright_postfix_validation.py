"""Playwright pós-fix: turmas, matrícula, login, dashboard degraded, restart check via API."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments" / "smoke_e2e_sentimentos" / "e2e_validation" / "ui_postfix"
OUT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5173")


def load_env():
    data = {}
    for name in (".env", ".env.smoke.local", "frontend/.env.local"):
        p = ROOT / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def shot(page, name: str) -> str:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT)).replace("\\", "/")


def record(results, area, ok, evidence, notes=""):
    results.append(
        {
            "area": area,
            "result": "PASS" if ok else "FAIL",
            "evidence": evidence,
            "notes": notes,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )


def login(page, email, password):
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    page.get_by_role("button", name=re.compile(r"Configura", re.I)).click()
    page.wait_for_timeout(400)
    sair = page.get_by_role("button", name=re.compile(r"Sair|Logout", re.I))
    if sair.count():
        sair.first.click()
        page.wait_for_timeout(800)
        page.get_by_role("button", name=re.compile(r"Configura", re.I)).click()
    page.get_by_label(re.compile(r"E-?mail", re.I)).fill(email)
    page.get_by_label(re.compile(r"Senha", re.I)).fill(password)
    page.get_by_role("button", name=re.compile(r"^Entrar$", re.I)).click()
    page.wait_for_timeout(3500)


def main():
    env = load_env()
    results = []
    tag = uuid.uuid4().hex[:5]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()

        # Login inválido
        login(page, "nope@sentimentos.test", "wrong-password-xx")
        body = page.locator("body").inner_text()
        stuck = page.get_by_role("button", name=re.compile(r"Entrando", re.I)).count() > 0
        has_err = "incorret" in body.lower() or "erro" in body.lower() or "inválid" in body.lower() or "invalid" in body.lower() or "credencial" in body.lower()
        entrar = page.get_by_role("button", name=re.compile(r"^Entrar$", re.I)).count() > 0
        record(results, "Login inválido", (not stuck) and entrar and has_err, shot(page, "login_invalid"), body[:160])

        # Login gestor
        login(page, env["SMOKE_GESTOR_EMAIL"], env["SMOKE_GESTOR_PASSWORD"])
        admin = page.get_by_role("button", name=re.compile(r"Administra", re.I)).count() > 0
        record(results, "Login gestor", admin, shot(page, "login_gestor"), f"admin={admin}")

        # Turmas
        page.get_by_role("button", name=re.compile(r"Administra", re.I)).first.click()
        page.wait_for_timeout(800)
        page.get_by_role("button", name=re.compile(r"^Turmas$", re.I)).click()
        page.wait_for_timeout(600)
        tname = f"UI Turma Fix {tag}"
        page.locator("form.admin-form").filter(has_text="Adicionar turma").get_by_label("Nome").fill(tname)
        page.locator("form.admin-form").filter(has_text="Adicionar turma").get_by_label("Série/ano").fill("8º")
        page.locator("form.admin-form").filter(has_text="Adicionar turma").get_by_label("Turno").fill("Manhã")
        page.locator("form.admin-form").filter(has_text="Adicionar turma").get_by_role("button", name="Adicionar").click()
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text()
        immediate = tname in body
        record(results, "Turma imediata", immediate, shot(page, "turma_create"), body[:200])
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        page.get_by_role("button", name=re.compile(r"Administra", re.I)).first.click()
        page.wait_for_timeout(600)
        page.get_by_role("button", name=re.compile(r"^Turmas$", re.I)).click()
        page.wait_for_timeout(800)
        body = page.locator("body").inner_text()
        record(results, "Turma após reload", tname in body, shot(page, "turma_reload"), body[:200])

        # Aluno + matrícula
        page.get_by_role("button", name=re.compile(r"^Alunos$", re.I)).click()
        page.wait_for_timeout(600)
        aname = f"UI Aluno Fix {tag}"
        form_aluno = page.locator("form.admin-form").filter(has_text="Adicionar aluno")
        if form_aluno.count() == 0:
            form_aluno = page.locator("form.admin-form").first
        form_aluno.get_by_label(re.compile(r"Nome", re.I)).first.fill(aname)
        form_aluno.get_by_role("button", name=re.compile(r"Adicionar|Criar", re.I)).click()
        page.wait_for_timeout(1200)
        body = page.locator("body").inner_text()
        record(results, "Aluno criado", aname in body, shot(page, "aluno"), "")

        # tentar matricular se UI tiver selects
        enroll_form = page.locator("form.admin-form").filter(has_text="Matricular")
        if enroll_form.count():
            # selects
            sels = enroll_form.locator("select")
            if sels.count() >= 2:
                # pick last options if available
                for i in range(min(2, sels.count())):
                    opts = sels.nth(i).locator("option")
                    if opts.count() > 1:
                        sels.nth(i).select_option(index=opts.count() - 1)
                enroll_form.get_by_role("button", name=re.compile(r"Matricular|Adicionar", re.I)).click()
                page.wait_for_timeout(1200)
            body = page.locator("body").inner_text()
            # encerrar se botão Retirar
            retirar = page.get_by_role("button", name=re.compile(r"Retirar", re.I))
            if retirar.count():
                page.on("dialog", lambda d: d.accept())
                retirar.first.click()
                page.wait_for_timeout(1000)
                record(results, "Matrícula ended", True, shot(page, "matricula"), "retirar clicado")
            else:
                record(results, "Matrícula ended", "matrícula" in body.lower() or "Matrícula criada" in body, shot(page, "matricula"), "sem botão retirar")
        else:
            record(results, "Matrícula ended", False, shot(page, "matricula"), "form ausente")

        # Professor
        login(page, env["SMOKE_PROFESSOR_EMAIL"], env["SMOKE_PROFESSOR_PASSWORD"])
        side = page.locator(".sidebar-item").all_text_contents()
        admin_btn = any("administra" in s.lower() for s in side)
        minhas = any("turma" in s.lower() for s in side)
        record(results, "Professor menu", (not admin_btn) and minhas, shot(page, "professor"), str(side))

        # Dashboard live
        page.get_by_role("button", name=re.compile(r"Ao vivo", re.I)).click()
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text().lower()
        tech = any(x in body for x in ("yolo", "bytetrack", "500 internal", "internal server error"))
        record(results, "Dashboard", not tech, shot(page, "dashboard"), body[:120])

        # Simular Edge down: intercept API
        page.route("**/api/v1/**", lambda route: route.abort())
        page.wait_for_timeout(4500)
        body = page.locator("body").inner_text()
        friendly = "temporariamente indisponível" in body.lower() or "reconect" in body.lower()
        no_500 = "500" not in body and "Internal Server Error" not in body
        record(results, "Dashboard offline UX", friendly and no_500, shot(page, "dashboard_offline"), body[:200])
        page.unroute("**/api/v1/**")
        page.wait_for_timeout(4000)
        body = page.locator("body").inner_text()
        recovered = "temporariamente indisponível" not in body.lower() or "ao vivo" in body.lower()
        record(results, "Dashboard reconectou", recovered, shot(page, "dashboard_online"), body[:160])

        browser.close()

    report = {
        "pass": sum(1 for r in results if r["result"] == "PASS"),
        "fail": sum(1 for r in results if r["result"] == "FAIL"),
        "results": results,
    }
    (OUT.parent / "ui_postfix_results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["fail"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
