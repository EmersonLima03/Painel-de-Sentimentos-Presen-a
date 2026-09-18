/**
 * Fase 5B — Playwright E2E (Sentimentos UI + Simulator admin).
 * Evidências em experiments/smoke_e2e_sentimentos/fase5b/
 */
import { chromium } from "playwright";
import { readFileSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "experiments/smoke_e2e_sentimentos/fase5b");
const SHOTS = join(OUT, "screenshots");
const JSON_DIR = join(OUT, "json");
mkdirSync(SHOTS, { recursive: true });
mkdirSync(JSON_DIR, { recursive: true });

function loadEnv(path) {
  const env = {};
  if (!existsSync(path)) return env;
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const i = line.indexOf("=");
    env[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return env;
}

const smoke = { ...loadEnv(join(ROOT, ".env")), ...loadEnv(join(ROOT, ".env.smoke.local")) };
const FE = process.env.FASE5B_FE_URL || "http://127.0.0.1:5173";
const EDGE = process.env.FASE5B_EDGE_URL || "http://127.0.0.1:8000";
const ADMIN = join(ROOT, "experiments/lxp_attendance_simulator/admin.html");

const jargon = [
  /\bbox\b/i,
  /\btrack[_ ]?id\b/i,
  /\byolo\b/i,
  /\bfusion\b/i,
  /\bphone_yolo\b/i,
  /\bhsemotion\b/i,
  /\bvgaf\b/i,
  /\bembedding\b/i,
  /\blandmark\b/i,
];

async function shot(page, name) {
  const p = join(SHOTS, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function main() {
  const report = {
    started_at: new Date().toISOString(),
    fe: FE,
    edge: EDGE,
    cases: [],
    jargon_hits: [],
    sidebar: [],
  };
  const push = (name, ok, extra = {}) =>
    report.cases.push({ name, ok, result: ok ? "PASS" : "FAIL", ...extra });

  // Edge health
  try {
    const r = await fetch(`${EDGE}/health`);
    push("edge_health", r.ok, { status: r.status });
  } catch (e) {
    push("edge_health", false, { error: String(e) });
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // --- Simulator admin (file://) ---
  try {
    await page.goto(`file:///${ADMIN.replace(/\\/g, "/")}`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(800);
    await shot(page, "01_sim_admin");
    const bodyText = await page.locator("body").innerText();
    push(
      "sim_admin_loads",
      /aula|lesson|attendance|chamada|simulator/i.test(bodyText),
      { snippet: bodyText.slice(0, 200) },
    );
  } catch (e) {
    push("sim_admin_loads", false, { error: String(e) });
  }

  // --- Sentimentos frontend ---
  try {
    await page.goto(FE, { waitUntil: "networkidle", timeout: 45000 });
    await page.waitForTimeout(1500);
    await shot(page, "02_login");

    const email = smoke.SMOKE_GESTOR_EMAIL;
    const password = smoke.SMOKE_GESTOR_PASSWORD;
    if (!email || !password) {
      push("gestor_login", false, { error: "missing SMOKE_GESTOR credentials" });
    } else {
      // Prefer labeled fields; fall back to inputs
      const emailInput = page.getByLabel(/e-?mail/i).first();
      const passInput = page.getByLabel(/senha|password/i).first();
      if ((await emailInput.count()) > 0) {
        await emailInput.fill(email);
        await passInput.fill(password);
      } else {
        await page.locator('input[type="email"], input[name="email"]').first().fill(email);
        await page.locator('input[type="password"]').first().fill(password);
      }
      const entrar = page.getByRole("button", { name: /entrar|login/i }).first();
      await entrar.click();
      await page.waitForTimeout(3500);
      await shot(page, "03_after_login");
      const sidebar = await page.locator(".sidebar-item, nav button, aside button").allTextContents();
      report.sidebar = sidebar.map((s) => s.trim()).filter(Boolean);
      push("gestor_login", report.sidebar.length > 0 || /dashboard|administração|ao vivo/i.test(await page.content()), {
        sidebar: report.sidebar.slice(0, 20),
      });
    }

    const clickNav = async (label, shotName) => {
      const btn = page.getByRole("button", { name: new RegExp(label, "i") }).first();
      if ((await btn.count()) === 0) {
        push(`nav_${shotName}`, false, { error: `button not found: ${label}` });
        return false;
      }
      await btn.click();
      await page.waitForTimeout(1200);
      await shot(page, shotName);
      push(`nav_${shotName}`, true);
      return true;
    };

    await clickNav("Administração", "04_admin");
    // Subnav inside admin if present
    for (const [label, name] of [
      ["Escola", "05_escola"],
      ["Turmas", "06_turmas"],
      ["Alunos", "07_alunos"],
      ["Disciplinas", "08_disciplinas"],
    ]) {
      const b = page.getByRole("button", { name: new RegExp(`^${label}$`, "i") }).first();
      if ((await b.count()) > 0) {
        await b.click();
        await page.waitForTimeout(900);
        await shot(page, name);
        push(`section_${name}`, true);
      } else {
        push(`section_${name}`, false, { result: "NÃO OBSERVADO", note: "botão não encontrado nesta tela" });
      }
    }

    await clickNav("Dashboard", "09_dashboard");
    await clickNav("Ao vivo", "10_ao_vivo");
    await clickNav("Histórico", "11_historico");
    await clickNav("Configurações", "12_config");

    // Jargon scan on visible text of a few pages
    for (const [label, name] of [
      ["Dashboard", "jargon_dashboard"],
      ["Ao vivo", "jargon_live"],
      ["Histórico", "jargon_hist"],
    ]) {
      const b = page.getByRole("button", { name: new RegExp(label, "i") }).first();
      if ((await b.count()) === 0) continue;
      await b.click();
      await page.waitForTimeout(800);
      const text = await page.locator("body").innerText();
      const hits = jargon.filter((re) => re.test(text)).map((re) => String(re));
      if (hits.length) report.jargon_hits.push({ page: name, hits });
    }
    push("no_tri_jargon_in_ui", report.jargon_hits.length === 0, { hits: report.jargon_hits });
  } catch (e) {
    push("sentimentos_ui", false, { error: String(e) });
    try {
      await shot(page, "99_error");
    } catch (_) {}
  }

  await browser.close();
  report.finished_at = new Date().toISOString();
  report.summary = {
    total: report.cases.length,
    pass: report.cases.filter((c) => c.ok).length,
    fail: report.cases.filter((c) => !c.ok).length,
  };
  const outPath = join(JSON_DIR, "fase5b_playwright.json");
  writeFileSync(outPath, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify({ out: outPath, summary: report.summary }, null, 2));
  process.exit(report.summary.fail > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
