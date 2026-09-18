/**
 * Runner local — importa playwright do node_modules desta pasta.
 * node experiments/smoke_e2e_sentimentos/fase5b/run_playwright.mjs
 */
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(__dirname, "package.json"));
const playwrightPath = require.resolve("playwright");

// Patch: run the e2e script with playwright resolvable via import map workaround
const { chromium } = await import(pathToFileURL(playwrightPath).href);
const { readFileSync, mkdirSync, writeFileSync, existsSync } = await import("node:fs");

const ROOT = join(__dirname, "../../..");
const OUT = __dirname;
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

const jargon = [/\bbox\b/i, /\btrack[_ ]?id\b/i, /\byolo\b/i, /\bfusion\b/i, /\bphone_yolo\b/i, /\bhsemotion\b/i, /\bvgaf\b/i, /\bembedding\b/i, /\blandmark\b/i];

async function shot(page, name) {
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
}

async function main() {
  const report = { started_at: new Date().toISOString(), fe: FE, edge: EDGE, cases: [], jargon_hits: [], sidebar: [] };
  const push = (name, ok, extra = {}) => report.cases.push({ name, ok, result: ok ? "PASS" : "FAIL", ...extra });

  try {
    const r = await fetch(`${EDGE}/health`);
    push("edge_health", r.ok, { status: r.status });
  } catch (e) {
    push("edge_health", false, { error: String(e) });
  }

  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();

  try {
    await page.goto(`file:///${ADMIN.replace(/\\/g, "/")}`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(1000);
    await shot(page, "01_sim_admin");
    const bodyText = await page.locator("body").innerText();
    push("sim_admin_loads", /aula|lesson|attendance|chamada|simulator|LXP/i.test(bodyText), { snippet: bodyText.slice(0, 240) });
  } catch (e) {
    push("sim_admin_loads", false, { error: String(e) });
  }

  try {
    await page.goto(FE, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForTimeout(1500);
    await shot(page, "02_login");

    const email = smoke.SMOKE_GESTOR_EMAIL;
    const password = smoke.SMOKE_GESTOR_PASSWORD;
    if (!email || !password) {
      push("gestor_login", false, { error: "missing SMOKE_GESTOR credentials" });
    } else {
      const emailInput = page.getByLabel(/e-?mail/i).first();
      if ((await emailInput.count()) > 0) {
        await emailInput.fill(email);
        await page.getByLabel(/senha|password/i).first().fill(password);
      } else {
        await page.locator('input[type="email"], input[name="email"]').first().fill(email);
        await page.locator('input[type="password"]').first().fill(password);
      }
      await page.getByRole("button", { name: /entrar|login/i }).first().click();
      await page.waitForTimeout(4000);
      await shot(page, "03_after_login");
      report.sidebar = (await page.locator(".sidebar-item, nav button, aside button").allTextContents()).map((s) => s.trim()).filter(Boolean);
      push("gestor_login", report.sidebar.length > 0, { sidebar: report.sidebar.slice(0, 25) });
    }

    const clickNav = async (label, shotName) => {
      const btn = page.getByRole("button", { name: new RegExp(label, "i") }).first();
      if ((await btn.count()) === 0) {
        push(`nav_${shotName}`, false, { error: `not found: ${label}` });
        return;
      }
      await btn.click();
      await page.waitForTimeout(1200);
      await shot(page, shotName);
      push(`nav_${shotName}`, true);
    };

    await clickNav("Administração", "04_admin");
    for (const [label, name] of [["Escola", "05_escola"], ["Turmas", "06_turmas"], ["Alunos", "07_alunos"], ["Disciplinas", "08_disciplinas"]]) {
      const b = page.getByRole("button", { name: new RegExp(`^${label}$`, "i") }).first();
      if ((await b.count()) > 0) {
        await b.click();
        await page.waitForTimeout(900);
        await shot(page, name);
        push(`section_${name}`, true);
      } else {
        push(`section_${name}`, false, { result: "NÃO OBSERVADO", note: "botão não encontrado" });
      }
    }
    await clickNav("Dashboard", "09_dashboard");
    await clickNav("Ao vivo", "10_ao_vivo");
    await clickNav("Histórico", "11_historico");
    await clickNav("Configurações", "12_config");

    for (const label of ["Dashboard", "Ao vivo", "Histórico"]) {
      const b = page.getByRole("button", { name: new RegExp(label, "i") }).first();
      if ((await b.count()) === 0) continue;
      await b.click();
      await page.waitForTimeout(800);
      const text = await page.locator("body").innerText();
      const hits = jargon.filter((re) => re.test(text)).map(String);
      if (hits.length) report.jargon_hits.push({ page: label, hits });
    }
    push("no_tri_jargon_in_ui", report.jargon_hits.length === 0, { hits: report.jargon_hits });
  } catch (e) {
    push("sentimentos_ui", false, { error: String(e) });
    try { await shot(page, "99_error"); } catch (_) {}
  }

  await browser.close();
  report.finished_at = new Date().toISOString();
  report.summary = {
    total: report.cases.length,
    pass: report.cases.filter((c) => c.ok).length,
    fail: report.cases.filter((c) => !c.ok).length,
  };
  writeFileSync(join(JSON_DIR, "fase5b_playwright.json"), JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify({ summary: report.summary, out: "fase5b/json/fase5b_playwright.json" }, null, 2));
  process.exit(report.summary.fail > 0 ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
