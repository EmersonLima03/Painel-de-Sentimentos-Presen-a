/**
 * Playwright F3 — fluxo facial com hooks (sem câmera física).
 * Sobe servidor com M2_POC_TEST_HOOKS=1.
 *
 *   node playwright_enrollment_f3.cjs
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");
const { chromium } = require("playwright");

const ROOT = __dirname;
const OUT = path.join(ROOT, "results", "enrollment_escalavel", "ui_aluno_f3");
const DB = path.join(ROOT, "results", "enrollment_escalavel", "poc_enrollment_f3_playwright.db");
const SUMMARY = path.join(ROOT, "results", "enrollment_escalavel", "F3_PLAYWRIGHT_SUMMARY.json");
const PORT = 18768;

function waitForServer(port, timeoutMs = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get({ host: "127.0.0.1", port, path: "/gestor/", timeout: 1000 }, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) reject(new Error("server timeout"));
        else setTimeout(tick, 300);
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

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  try { fs.unlinkSync(DB); } catch (_) {}

  const py = process.env.PYTHON || "python";
  const env = { ...process.env, M2_POC_TEST_HOOKS: "1" };
  const server = spawn(
    py,
    [
      path.join(ROOT, "scripts", "enrollment_gestor_server.py"),
      "--host", "127.0.0.1",
      "--port", String(PORT),
      "--db", DB,
    ],
    { cwd: ROOT, env, stdio: ["ignore", "pipe", "pipe"] }
  );
  let serverLog = "";
  server.stdout.on("data", (d) => { serverLog += d.toString(); });
  server.stderr.on("data", (d) => { serverLog += d.toString(); });

  const result = {
    ok: false,
    checks: {},
    screenshots: [],
    errors: [],
    physical: {
      note: "Reconhecimento facial real / celular físico = NÃO TESTADO nesta execução automatizada",
      tested_here: ["UI states", "hooks force-step", "glasses yes/no", "gestor completed"],
      not_tested: ["getUserMedia real", "YuNet on phone", "pose física", "iluminação"],
    },
  };
  const base = `http://127.0.0.1:${PORT}`;

  try {
    await waitForServer(PORT);
    const camp = (await api(base, "POST", "/api/gestor/campaigns", {
      school_id: "escola_demo_presenca",
      class_group_id: "turma_familia_lab",
    })).data;
    const code = camp.claim_sheet.find((r) => r.display_name === "Dulin").claim_code;

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();

    await page.goto(`${base}/a/${camp.campaign_token}`, { waitUntil: "networkidle" });
    await page.waitForSelector("[data-testid=screen-claim]:not(.hidden)");
    await page.locator("[data-testid=claim-code]").fill(code);
    await page.locator("[data-testid=btn-claim-continue]").click();
    await page.waitForSelector("[data-testid=screen-confirm]:not(.hidden)");
    await page.locator("[data-testid=btn-confirm]").click();
    await page.waitForSelector("[data-testid=screen-intro]:not(.hidden)");
    result.checks.intro_ok = true;

    // Start session without real camera via test helper
    await page.evaluate(async () => {
      const st = window.__m2Test.getState();
      // sessionToken set after claim — startWithoutCamera
      return window.__m2Test.startWithoutCamera();
    });
    await page.waitForSelector("[data-testid=screen-capture]:not(.hidden)");
    result.checks.capture_screen = true;
    const title = await page.locator("[data-testid=capture-title]").innerText();
    result.checks.front_title = /Olhe para a câmera/i.test(title);
    // No technical jargon
    const bodyText = await page.locator("body").innerText();
    result.checks.no_facenet = !/FaceNet|YuNet|FAISS|threshold|embedding/i.test(bodyText);

    for (const step of ["front", "lateral_right", "lateral_left", "validate"]) {
      const r = await page.evaluate(async (s) => window.__m2Test.forceStep(s), step);
      if (!r.data.ok) throw new Error("forceStep failed " + step);
    }
    await page.waitForSelector("[data-testid=screen-glasses]:not(.hidden)");
    result.checks.glasses_ask = true;
    const shotG = path.join(OUT, "01_glasses_ask.png");
    await page.screenshot({ path: shotG, fullPage: true });
    result.screenshots.push(shotG);

    await page.locator("[data-testid=btn-glasses-no]").click();
    await page.waitForSelector("[data-testid=screen-done]:not(.hidden)");
    const done = await page.locator("[data-testid=done-title]").innerText();
    result.checks.done_no_glasses = /Cadastro concluído/i.test(done);
    const shotD = path.join(OUT, "02_done_no_glasses.png");
    await page.screenshot({ path: shotD, fullPage: true });
    result.screenshots.push(shotD);

    const prog = await api(base, "GET", `/api/gestor/campaigns/${camp.campaign_id}/progress`);
    const dulin = prog.data.items.find((i) => i.display_name === "Dulin");
    result.checks.gestor_sees_completed = dulin && dulin.status === "completed";

    // --- glasses YES path (Mae)
    const codeMae = camp.claim_sheet.find((r) => r.display_name === "Mae").claim_code;
    await page.goto(`${base}/a/${camp.campaign_token}`, { waitUntil: "networkidle" });
    await page.waitForSelector("[data-testid=screen-claim]:not(.hidden)");
    await page.locator("[data-testid=claim-code]").fill(codeMae);
    await page.locator("[data-testid=btn-claim-continue]").click();
    await page.waitForSelector("[data-testid=screen-confirm]:not(.hidden)");
    await page.locator("[data-testid=btn-confirm]").click();
    await page.waitForSelector("[data-testid=screen-intro]:not(.hidden)");
    await page.evaluate(() => window.__m2Test.startWithoutCamera());
    await page.waitForSelector("[data-testid=screen-capture]:not(.hidden)");
    for (const step of ["front", "lateral_right", "lateral_left", "validate"]) {
      await page.evaluate(async (s) => window.__m2Test.forceStep(s), step);
    }
    await page.waitForSelector("[data-testid=screen-glasses]:not(.hidden)");
    await page.locator("[data-testid=btn-glasses-yes]").click();
    await page.waitForSelector("[data-testid=screen-capture]:not(.hidden)");
    const gTitle = await page.locator("[data-testid=capture-title]").innerText();
    result.checks.glasses_capture_title = /óculos/i.test(gTitle);
    await page.evaluate(async () => window.__m2Test.forceStep("glasses_habitual"));
    await page.waitForSelector("[data-testid=screen-done]:not(.hidden)");
    result.checks.done_with_glasses = true;
    const shotG2 = path.join(OUT, "03_done_with_glasses.png");
    await page.screenshot({ path: shotG2, fullPage: true });
    result.screenshots.push(shotG2);

    const prog2 = await api(base, "GET", `/api/gestor/campaigns/${camp.campaign_id}/progress`);
    result.checks.both_completed = prog2.data.completed === 2;

    // camera denied path (mock)
    const context2 = await browser.newContext({
      viewport: { width: 412, height: 915 },
      isMobile: true,
      permissions: [],
    });
    await context2.grantPermissions([], { origin: base });
    // Deny by overriding getUserMedia
    const page2 = await context2.newPage();
    await page2.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = () =>
        Promise.reject(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
    });
    const camp2 = (await api(base, "POST", "/api/gestor/campaigns", {
      school_id: "escola_demo_presenca",
      class_group_id: "turma_familia_lab",
    })).data;
    const c2 = camp2.claim_sheet[0].claim_code;
    await page2.goto(`${base}/a/${camp2.campaign_token}`, { waitUntil: "networkidle" });
    await page2.locator("[data-testid=claim-code]").fill(c2);
    await page2.locator("[data-testid=btn-claim-continue]").click();
    await page2.waitForSelector("[data-testid=screen-confirm]:not(.hidden)");
    await page2.locator("[data-testid=btn-confirm]").click();
    await page2.waitForSelector("[data-testid=screen-intro]:not(.hidden)");
    await page2.locator("[data-testid=btn-start-enroll]").click();
    await page2.waitForSelector("[data-testid=screen-cam-denied]:not(.hidden)");
    result.checks.camera_denied_ui = true;
    const shotDen = path.join(OUT, "04_camera_denied.png");
    await page2.screenshot({ path: shotDen, fullPage: true });
    result.screenshots.push(shotDen);

    await browser.close();

    const required = [
      "intro_ok",
      "capture_screen",
      "front_title",
      "no_facenet",
      "glasses_ask",
      "done_no_glasses",
      "gestor_sees_completed",
      "glasses_capture_title",
      "done_with_glasses",
      "both_completed",
      "camera_denied_ui",
    ];
    result.ok = required.every((k) => result.checks[k] === true);
    result.required = required;
  } catch (err) {
    result.ok = false;
    result.errors.push(String(err && err.stack ? err.stack : err));
  } finally {
    server.kill("SIGTERM");
    result.server_log_tail = serverLog.slice(-3000);
    fs.writeFileSync(SUMMARY, JSON.stringify(result, null, 2), "utf8");
  }

  console.log(JSON.stringify({ ok: result.ok, checks: result.checks, summary: SUMMARY }, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main();
