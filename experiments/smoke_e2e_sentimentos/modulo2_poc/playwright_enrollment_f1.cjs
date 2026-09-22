/**
 * Playwright F1 — Painel do gestor (Enrollment Escalavel A).
 *
 * Usage:
 *   node playwright_enrollment_f1.cjs
 *
 * Starts enrollment_gestor_server on an ephemeral port, drives the UI,
 * writes evidence under results/enrollment_escalavel/ui_gestor/.
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");
const { chromium } = require("playwright");

const ROOT = __dirname;
const OUT = path.join(ROOT, "results", "enrollment_escalavel", "ui_gestor");
const DB = path.join(ROOT, "results", "enrollment_escalavel", "poc_enrollment_f1_playwright.db");
const SUMMARY = path.join(ROOT, "results", "enrollment_escalavel", "F1_PLAYWRIGHT_SUMMARY.json");

function waitForServer(port, timeoutMs = 20000) {
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

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  try { fs.unlinkSync(DB); } catch (_) {}

  const port = 18766;
  const py = process.env.PYTHON || "python";
  const server = spawn(
    py,
    [
      path.join(ROOT, "scripts", "enrollment_gestor_server.py"),
      "--host", "127.0.0.1",
      "--port", String(port),
      "--db", DB,
    ],
    { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] }
  );
  let serverLog = "";
  server.stdout.on("data", (d) => { serverLog += d.toString(); });
  server.stderr.on("data", (d) => { serverLog += d.toString(); });

  const result = {
    ok: false,
    checks: {},
    screenshots: [],
    errors: [],
    share_link: null,
  };

  try {
    await waitForServer(port);
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      permissions: ["clipboard-read", "clipboard-write"],
    });
    const page = await context.newPage();
    const base = `http://127.0.0.1:${port}`;

    await page.goto(`${base}/gestor/`, { waitUntil: "networkidle" });
    result.checks.gestor_page = await page.locator("h1").innerText();

    await page.waitForFunction(() => {
      const s = document.querySelector("#schoolSelect");
      return s && s.options && s.options.length > 0;
    });
    const schoolText = await page.locator("#schoolSelect").inputValue();
    const schoolLabel = await page.locator("#schoolSelect option:checked").innerText();
    result.checks.school_demo = schoolLabel.includes("Escola Demo");
    const classLabel = await page.locator("#classSelect option:checked").innerText();
    result.checks.class_8a = classLabel.includes("8º Ano A") || classLabel.includes("8");
    const count = await page.locator("[data-testid=student-count]").innerText();
    result.checks.student_count = count.trim() === "2";

    await page.locator("[data-testid=btn-start-campaign]").click();
    await page.waitForSelector("[data-testid=campaign-panel]:not(.hidden)", { timeout: 10000 });
    await page.waitForSelector("[data-testid=qr-image]");
    await page.waitForFunction(() => {
      const img = document.querySelector("[data-testid=qr-image]");
      return img && img.complete && img.naturalWidth > 0;
    });

    const status = await page.locator("[data-testid=campaign-status]").innerText();
    result.checks.campaign_active = /ativa/i.test(status);

    const link = await page.locator("[data-testid=share-link]").inputValue();
    result.share_link = link;
    result.checks.link_has_token_only_path = /\/a\/[A-Za-z0-9_\-]+$/.test(link);
    result.checks.link_no_dulin = !/dulin/i.test(link);
    result.checks.link_no_mae = !/mae/i.test(link);
    result.checks.link_no_claim = !/claim/i.test(link);
    result.checks.link_no_embedding = !/embedding/i.test(link);

    const summary = await page.locator("[data-testid=progress-summary]").innerText();
    result.checks.progress_initial = /0 de 2/.test(summary);

    const roster = await page.locator("[data-testid=roster-list] .roster-item").allTextContents();
    result.checks.dulin_pending = roster.some((t) => /Dulin/i.test(t) && /Pendente/i.test(t));
    result.checks.mae_pending = roster.some((t) => /Mae/i.test(t) && /Pendente/i.test(t));

    await page.locator("[data-testid=btn-copy-link]").click();
    await page.waitForSelector("[data-testid=copy-feedback]:not(.hidden)", { timeout: 5000 });
    result.checks.copy_feedback = true;
    try {
      const clip = await page.evaluate(() => navigator.clipboard.readText());
      result.checks.copy_link_matches = clip === link;
    } catch (e) {
      result.checks.copy_link_matches = "clipboard_unavailable";
      result.errors.push(String(e));
    }

    const shot1 = path.join(OUT, "01_campaign_active.png");
    await page.screenshot({ path: shot1, fullPage: true });
    result.screenshots.push(shot1);

    page.once("dialog", async (d) => { await d.accept(); });
    await page.locator("[data-testid=btn-revoke]").click();
    await page.waitForFunction(() => {
      const el = document.querySelector("[data-testid=campaign-status]");
      return el && /revogad/i.test(el.textContent || "");
    }, { timeout: 8000 });
    result.checks.revoke_works = true;

    const shot2 = path.join(OUT, "02_campaign_revoked.png");
    await page.screenshot({ path: shot2, fullPage: true });
    result.screenshots.push(shot2);

    await browser.close();

    const required = [
      "school_demo",
      "class_8a",
      "student_count",
      "campaign_active",
      "link_has_token_only_path",
      "link_no_dulin",
      "link_no_mae",
      "link_no_claim",
      "link_no_embedding",
      "progress_initial",
      "dulin_pending",
      "mae_pending",
      "copy_feedback",
      "revoke_works",
    ];
    result.ok = required.every((k) => result.checks[k] === true);
  } catch (err) {
    result.ok = false;
    result.errors.push(String(err && err.stack ? err.stack : err));
  } finally {
    server.kill("SIGTERM");
    result.server_log_tail = serverLog.slice(-2000);
    fs.writeFileSync(SUMMARY, JSON.stringify(result, null, 2), "utf8");
  }

  console.log(JSON.stringify({ ok: result.ok, checks: result.checks, summary: SUMMARY }, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main();
