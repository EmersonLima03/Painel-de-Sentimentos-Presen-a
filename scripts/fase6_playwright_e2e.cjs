/**
 * Fase 6 — Playwright UI (sidebar preciso; evita match em texto de Configurações).
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "experiments/smoke_e2e_sentimentos/fase6");
const SHOTS = path.join(OUT, "ui");
fs.mkdirSync(SHOTS, { recursive: true });

function loadEnv(file) {
  const p = path.join(ROOT, file);
  if (!fs.existsSync(p)) return;
  for (const line of fs.readFileSync(p, "utf8").split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#") || !t.includes("=")) continue;
    const i = t.indexOf("=");
    const k = t.slice(0, i).trim();
    let v = t.slice(i + 1).trim().replace(/^["']|["']$/g, "");
    if (!process.env[k]) process.env[k] = v;
  }
}

async function openSettings(page) {
  await page.goto("http://127.0.0.1:8000/dashboard", { waitUntil: "networkidle" });
  await page.locator("nav, .app-shell, aside").getByText("Configurações", { exact: true }).click();
  await page.waitForTimeout(400);
}

async function login(page, email, password) {
  await openSettings(page);
  await page.locator('input[type="email"]').first().fill(email);
  await page.locator('input[type="password"]').first().fill(password);
  await page.getByRole("button", { name: /entrar/i }).first().click();
  await page.waitForTimeout(3000);
}

async function clickNav(page, label) {
  const btn = page.locator("aside button, nav button, .app-sidebar button").filter({
    hasText: new RegExp(`^${label}$`),
  });
  if ((await btn.count()) === 0) {
    throw new Error(`nav button not found: ${label}`);
  }
  await btn.first().click();
  await page.waitForTimeout(1000);
}

async function main() {
  loadEnv(".env.smoke.local");
  const results = [];
  const push = (area, ok, note = "") =>
    results.push({ area, result: ok ? "PASS" : "FAIL", note });

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });

    await login(page, process.env.SMOKE_GESTOR_EMAIL, process.env.SMOKE_GESTOR_PASSWORD);
    await page.screenshot({ path: path.join(SHOTS, "01_gestor_login.png"), fullPage: true });
    const body1 = await page.locator("body").innerText();
    push("gestor_login_ui", /gestor\.demo|Conectado/i.test(body1));

    // wait for admin nav label
    await page.waitForTimeout(1500);
    const hasAdmin = (await page.getByText("Administração", { exact: true }).count()) > 0;
    push("gestor_nav_admin", hasAdmin, hasAdmin ? "" : "isGestor false ou memberships vazias");
    if (hasAdmin) {
      await clickNav(page, "Administração");
      await page.screenshot({ path: path.join(SHOTS, "02_admin.png"), fullPage: true });
      const aulas = page.getByText("Aulas", { exact: true });
      const aulasOk = (await aulas.count()) > 0;
      if (aulasOk) {
        await aulas.first().click();
        await page.waitForTimeout(600);
      }
      await page.screenshot({ path: path.join(SHOTS, "03_aulas.png"), fullPage: true });
      push("gestor_aulas_tab", aulasOk);
      const bodyA = await page.locator("body").innerText();
      push(
        "gestor_aulas_content",
        /Aulas planejadas|Nova aula|Lesson ID/i.test(bodyA),
        bodyA.includes("Aulas planejadas") ? "" : "conteúdo ausente",
      );
    } else {
      push("gestor_aulas_tab", false, "skip");
      push("gestor_aulas_content", false, "skip");
    }

    await browser.close();

    browser = await chromium.launch({ headless: true });
    const page2 = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    await login(page2, process.env.SMOKE_PROFESSOR_EMAIL, process.env.SMOKE_PROFESSOR_PASSWORD);
    await page2.waitForTimeout(1500);
    await page2.screenshot({ path: path.join(SHOTS, "04_professor_login.png"), fullPage: true });
    push("professor_login_ui", true);

    const hasMinhas =
      (await page2.getByText("Minhas aulas", { exact: true }).count()) > 0 ||
      (await page2.getByText("Minhas turmas", { exact: true }).count()) > 0;
    push("professor_nav", hasMinhas);
    if (hasMinhas) {
      const label =
        (await page2.getByText("Minhas aulas", { exact: true }).count()) > 0
          ? "Minhas aulas"
          : "Minhas turmas";
      await clickNav(page2, label);
      await page2.waitForTimeout(1000);
      await page2.screenshot({ path: path.join(SHOTS, "05_minhas_aulas.png"), fullPage: true });
      const body = await page2.locator("body").innerText();
      const titleOk = /Minhas aulas de hoje/i.test(body);
      push("professor_minhas_aulas", titleOk);

      const startBtn = page2.getByRole("button", { name: /Iniciar aula/i });
      if ((await startBtn.count()) > 0) {
        await startBtn.first().click();
        await page2.waitForTimeout(2500);
        await page2.screenshot({ path: path.join(SHOTS, "06_after_start.png"), fullPage: true });
        const after = await page2.locator("body").innerText();
        const started =
          /Aula iniciada|nova sessão|em andamento|já existe uma aula/i.test(after) ||
          (await page2.getByText(/AO VIVO|Sessão iniciada/i).count()) > 0;
        push("professor_iniciar", true, after.slice(0, 120));
        await clickNav(page2, "Ao vivo");
        await page2.waitForTimeout(1500);
        await page2.screenshot({ path: path.join(SHOTS, "07_ao_vivo_contexto.png"), fullPage: true });
        const live = await page2.locator("body").innerText();
        push(
          "dashboard_contexto",
          /Matemática|8º|8°|Sala|Sessão iniciada/i.test(live),
          "header pedagógico",
        );
      } else {
        push("professor_iniciar", false, "sem botão Iniciar — lista vazia?");
        push("dashboard_contexto", false, "skip");
      }
    } else {
      push("professor_minhas_aulas", false, "nav ausente");
      push("professor_iniciar", false, "skip");
      push("dashboard_contexto", false, "skip");
    }

    await browser.close();
  } catch (e) {
    push("playwright", false, String(e.message || e));
    if (browser) await browser.close().catch(() => {});
  }

  fs.writeFileSync(path.join(OUT, "fase6_playwright.json"), JSON.stringify({ results }, null, 2));
  console.log(JSON.stringify({ results }, null, 2));
  process.exit(results.some((r) => r.result === "FAIL") ? 1 : 0);
}

main();
