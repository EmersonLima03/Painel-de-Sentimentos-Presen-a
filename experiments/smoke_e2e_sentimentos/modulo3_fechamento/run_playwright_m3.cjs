/**
 * Playwright — painel LXP Homologação
 * node experiments/smoke_e2e_sentimentos/modulo3_fechamento/run_playwright_m3.cjs
 */
const { chromium } = require("playwright");
const { readFileSync, mkdirSync, writeFileSync, existsSync } = require("node:fs");
const { join } = require("node:path");

const OUT = __dirname;
const ROOT = join(__dirname, "../../..");
const SHOTS = join(OUT, "ui");
mkdirSync(SHOTS, { recursive: true });

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
const FE = process.env.M3_FE_URL || "http://127.0.0.1:5173";
const EDGE = process.env.M3_EDGE_URL || "http://127.0.0.1:8000";

async function shot(page, name) {
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
}

async function main() {
  const report = { started_at: new Date().toISOString(), fe: FE, edge: EDGE, cases: [] };
  const push = (name, ok, extra = {}) =>
    report.cases.push({ name, ok, result: ok ? "PASS" : "FAIL", ...extra });

  try {
    const r = await fetch(`${EDGE}/health`);
    const j = await r.json();
    push("edge_health", r.ok, { cameras_online: j.cameras_online });
  } catch (e) {
    push("edge_health", false, { error: String(e) });
  }

  try {
    const tok = smoke.API_TOKEN || smoke.DEVICE_TOKEN || "";
    const h = await fetch(`${EDGE}/api/v1/homolog/lxp`, { headers: { "X-API-Token": tok } });
    const body = await h.json();
    push("homolog_api", h.ok && body.ok !== false, {
      sim: body.simulator?.status,
      host: body.simulator?.host,
      history: (body.history || []).length,
    });
  } catch (e) {
    push("homolog_api", false, { error: String(e) });
  }

  const browser = await chromium.launch({ headless: true });
  const page = await (
    await browser.newContext({ viewport: { width: 1440, height: 900 } })
  ).newPage();

  try {
    await page.goto(FE, { waitUntil: "domcontentloaded", timeout: 60000 });
    // injeta token Edge se necessário
    const tok = smoke.API_TOKEN || smoke.DEVICE_TOKEN || "";
    if (tok) {
      await page.evaluate((t) => localStorage.setItem("api_token", t), tok);
      await page.reload({ waitUntil: "domcontentloaded" });
    }
    await page.waitForTimeout(1500);

    const nav = page.getByRole("button", { name: /LXP Homologa/i }).first();
    push("nav_lxp_homolog", (await nav.count()) > 0);
    if ((await nav.count()) > 0) {
      await nav.click();
      await page.waitForTimeout(2500);
    }
    await shot(page, "01_lxp_homolog");

    const view = page.getByTestId("lxp-homolog-view");
    push("view_loaded", (await view.count()) > 0);

    const bodyText = await page.locator("body").innerText();
    push("header_simulator_badge", /SIMULATOR/i.test(bodyText));
    push("disclaimer_prod", /n[aã]o conectado ao LXP de produ/i.test(bodyText));
    push("simulator_project", /zasbmqwwkecmjbebejev/i.test(bodyText));
    push("context_section", (await page.getByTestId("lxp-homolog-context").count()) > 0);
    push("pipeline_section", (await page.getByTestId("lxp-homolog-pipeline").count()) > 0);
    push("event_section", (await page.getByTestId("lxp-homolog-event").count()) > 0);
    push("history_section", (await page.getByTestId("lxp-homolog-history").count()) > 0);
    push("presence_section", (await page.getByTestId("lxp-homolog-presence").count()) > 0);
    push("summary_section", (await page.getByTestId("lxp-homolog-summary").count()) > 0);

    await shot(page, "02_lxp_homolog_scrolled");
  } catch (e) {
    push("playwright_flow", false, { error: String(e) });
    await shot(page, "zz_error").catch(() => {});
  }

  await browser.close();
  report.ended_at = new Date().toISOString();
  report.summary = {
    pass: report.cases.filter((c) => c.ok).length,
    fail: report.cases.filter((c) => !c.ok).length,
    total: report.cases.length,
  };
  writeFileSync(join(OUT, "playwright_m3.json"), JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report.summary, null, 2));
  process.exit(report.summary.fail > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
