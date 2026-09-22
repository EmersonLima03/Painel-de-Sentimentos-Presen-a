/**
 * Playwright F2 — fluxo mobile do aluno (sem camera).
 *
 *   node playwright_enrollment_f2.cjs
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");
const { chromium } = require("playwright");

const ROOT = __dirname;
const OUT = path.join(ROOT, "results", "enrollment_escalavel", "ui_aluno");
const DB = path.join(ROOT, "results", "enrollment_escalavel", "poc_enrollment_f2_playwright.db");
const SUMMARY = path.join(ROOT, "results", "enrollment_escalavel", "F2_PLAYWRIGHT_SUMMARY.json");
const PORT = 18767;

function waitForServer(port, timeoutMs = 25000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get({ host: "127.0.0.1", port, path: "/gestor/", timeout: 1000 }, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) reject(new Error("server timeout"));
        else setTimeout(tick, 250);
      });
    };
    tick();
  });
}

async function api(base, method, urlPath, body) {
  const res = await fetch(`${base}${urlPath}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

async function noHorizontalScroll(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth <= Math.ceil(window.innerWidth) + 1;
  });
}

async function fillClaim(page, code) {
  await page.locator("[data-testid=claim-code]").fill(code);
  await page.locator("[data-testid=btn-claim-continue]").click();
}

async function runHappyPath(page, base, camp, viewportName) {
  const code = camp.claim_sheet.find((r) => r.display_name === "Dulin").claim_code;
  await page.goto(`${base}/a/${camp.campaign_token}`, { waitUntil: "networkidle" });
  await page.waitForSelector("[data-testid=screen-claim]:not(.hidden)");
  const checks = {};
  checks[`${viewportName}_claim_visible`] = true;
  checks[`${viewportName}_no_hscroll`] = await noHorizontalScroll(page);

  await fillClaim(page, code);
  await page.waitForSelector("[data-testid=screen-confirm]:not(.hidden)");
  const hello = await page.locator("[data-testid=hello-title]").innerText();
  checks[`${viewportName}_hello_dulin`] = /Olá,\s*Dulin!/i.test(hello);
  const cls = await page.locator("[data-testid=confirm-class]").innerText();
  checks[`${viewportName}_class`] = /8º Ano A/.test(cls);

  await page.locator("[data-testid=btn-confirm]").click();
  await page.waitForSelector("[data-testid=screen-intro]:not(.hidden)");
  const intro = await page.locator("#screenIntro h1").innerText();
  checks[`${viewportName}_ready`] = /Tudo pronto/i.test(intro);
  checks[`${viewportName}_start_btn`] = await page.locator("[data-testid=btn-start-enroll]").isVisible();
  // F2 boundary: do NOT open camera here (F3). Ensure no live video yet.
  checks[`${viewportName}_no_camera_ui`] = !(await page.locator("[data-testid=screen-capture]:not(.hidden)").count());
  checks[`${viewportName}_no_hscroll_ready`] = await noHorizontalScroll(page);

  const shot = path.join(OUT, `${viewportName}_ready.png`);
  await page.screenshot({ path: shot, fullPage: true });
  return { checks, shot };
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  try { fs.unlinkSync(DB); } catch (_) {}

  const py = process.env.PYTHON || "python";
  const server = spawn(
    py,
    [
      path.join(ROOT, "scripts", "enrollment_gestor_server.py"),
      "--host", "127.0.0.1",
      "--port", String(PORT),
      "--db", DB,
    ],
    { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] }
  );
  let serverLog = "";
  server.stdout.on("data", (d) => { serverLog += d.toString(); });
  server.stderr.on("data", (d) => { serverLog += d.toString(); });

  const result = { ok: false, checks: {}, screenshots: [], errors: [] };
  const base = `http://127.0.0.1:${PORT}`;

  try {
    await waitForServer(PORT);
    const created = await api(base, "POST", "/api/gestor/campaigns", {
      school_id: "escola_demo_presenca",
      class_group_id: "turma_familia_lab",
    });
    if (!created.data.ok) throw new Error("create campaign failed");
    const camp = created.data;

    const browser = await chromium.launch({ headless: true });

    // --- 390x844 happy path
    {
      const context = await browser.newContext({
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      });
      const page = await context.newPage();
      const happy = await runHappyPath(page, base, camp, "v390");
      Object.assign(result.checks, happy.checks);
      result.screenshots.push(happy.shot);

      // Não sou eu on a fresh campaign
      const camp2 = (await api(base, "POST", "/api/gestor/campaigns", {
        school_id: "escola_demo_presenca",
        class_group_id: "turma_familia_lab",
      })).data;
      const code2 = camp2.claim_sheet.find((r) => r.display_name === "Mae").claim_code;
      await page.goto(`${base}/a/${camp2.campaign_token}`, { waitUntil: "networkidle" });
      await page.waitForSelector("[data-testid=screen-claim]:not(.hidden)");
      await fillClaim(page, code2);
      await page.waitForSelector("[data-testid=screen-confirm]:not(.hidden)");
      await page.locator("[data-testid=btn-not-me]").click();
      await page.waitForSelector("[data-testid=screen-claim]:not(.hidden)");
      result.checks.nao_sou_eu_returns_claim = true;
      // reclaim same code
      await fillClaim(page, code2);
      await page.waitForSelector("[data-testid=screen-confirm]:not(.hidden)");
      result.checks.nao_sou_eu_allows_reclaim = true;
      await context.close();
    }

    // --- 412x915 happy path (new campaign — previous Dulin completed? camp1 Dulin is in_progress)
    {
      const camp3 = (await api(base, "POST", "/api/gestor/campaigns", {
        school_id: "escola_demo_presenca",
        class_group_id: "turma_familia_lab",
      })).data;
      const context = await browser.newContext({
        viewport: { width: 412, height: 915 },
        isMobile: true,
        hasTouch: true,
      });
      const page = await context.newPage();
      const happy = await runHappyPath(page, base, camp3, "v412");
      Object.assign(result.checks, happy.checks);
      result.screenshots.push(happy.shot);

      // claim inválido
      await page.goto(`${base}/a/${camp3.campaign_token}`, { waitUntil: "networkidle" });
      // Mae still pending on camp3 if we used Dulin in happy path
      await page.waitForSelector("[data-testid=screen-claim]:not(.hidden)", { timeout: 5000 }).catch(() => {});
      // After happy path we're on ready; go again with same token — Dulin already in_progress/claimed
      await page.goto(`${base}/a/${camp3.campaign_token}`, { waitUntil: "networkidle" });
      await page.waitForSelector("[data-testid=screen-claim]:not(.hidden)");
      await fillClaim(page, "000000");
      await page.waitForSelector("[data-testid=claim-error]:not(.hidden)");
      const err = await page.locator("[data-testid=claim-error]").innerText();
      result.checks.claim_invalido_generico = /codigo invalido|indisponivel/i.test(err);
      result.checks.claim_invalido_no_name_leak = !/Dulin|Mae/i.test(err);
      const shotErr = path.join(OUT, "v412_claim_invalid.png");
      await page.screenshot({ path: shotErr, fullPage: true });
      result.screenshots.push(shotErr);
      await context.close();
    }

    // --- campanha revogada
    {
      const camp4 = (await api(base, "POST", "/api/gestor/campaigns", {
        school_id: "escola_demo_presenca",
        class_group_id: "turma_familia_lab",
      })).data;
      await api(base, "POST", `/api/gestor/campaigns/${camp4.campaign_id}/revoke`);
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
      const page = await context.newPage();
      await page.goto(`${base}/a/${camp4.campaign_token}`, { waitUntil: "networkidle" });
      await page.waitForSelector("[data-testid=screen-blocked]:not(.hidden)");
      const title = await page.locator("#blockedTitle").innerText();
      result.checks.campanha_revogada_bloqueia = /encerrada|revogad|indispon/i.test(title);
      const shot = path.join(OUT, "revoked_blocked.png");
      await page.screenshot({ path: shot, fullPage: true });
      result.screenshots.push(shot);
      await context.close();
    }

    // --- claim já concluído
    {
      const camp5 = (await api(base, "POST", "/api/gestor/campaigns", {
        school_id: "escola_demo_presenca",
        class_group_id: "turma_familia_lab",
      })).data;
      const code = camp5.claim_sheet.find((r) => r.display_name === "Dulin").claim_code;
      const claimed = await api(base, "POST", "/api/aluno/claim", {
        campaign_token: camp5.campaign_token,
        claim_code: code,
      });
      await api(base, "POST", "/api/aluno/session/start", {
        session_token: claimed.data.session_token,
      });
      await api(base, "POST", "/api/aluno/session/complete", {
        session_token: claimed.data.session_token,
      });
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
      const page = await context.newPage();
      await page.goto(`${base}/a/${camp5.campaign_token}`, { waitUntil: "networkidle" });
      await page.waitForSelector("[data-testid=screen-claim]:not(.hidden)");
      await fillClaim(page, code);
      await page.waitForSelector("[data-testid=claim-error]:not(.hidden)");
      const err = await page.locator("[data-testid=claim-error]").innerText();
      result.checks.claim_concluido_bloqueia = /codigo invalido|indisponivel/i.test(err);
      await context.close();
    }

    await browser.close();

    const required = [
      "v390_claim_visible",
      "v390_no_hscroll",
      "v390_hello_dulin",
      "v390_class",
      "v390_ready",
      "v390_start_btn",
      "v390_no_camera_ui",
      "v412_claim_visible",
      "v412_no_hscroll",
      "v412_hello_dulin",
      "v412_ready",
      "v412_start_btn",
      "v412_no_camera_ui",
      "nao_sou_eu_returns_claim",
      "nao_sou_eu_allows_reclaim",
      "claim_invalido_generico",
      "claim_invalido_no_name_leak",
      "campanha_revogada_bloqueia",
      "claim_concluido_bloqueia",
    ];
    result.ok = required.every((k) => result.checks[k] === true);
    result.required = required;
  } catch (err) {
    result.ok = false;
    result.errors.push(String(err && err.stack ? err.stack : err));
  } finally {
    server.kill("SIGTERM");
    result.server_log_tail = serverLog.slice(-2500);
    fs.writeFileSync(SUMMARY, JSON.stringify(result, null, 2), "utf8");
  }

  console.log(JSON.stringify({ ok: result.ok, checks: result.checks, summary: SUMMARY }, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main();
