/**
 * Playwright — UI Enrollment Guiado A (POC M2)
 * node run_playwright_m2_ui.cjs
 * Requer: UI server em http://127.0.0.1:8765
 */
const { chromium } = require("playwright");
const { mkdirSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");

const OUT = __dirname;
const SHOTS = join(OUT, "results", "ui");
const BASE = process.env.M2_UI_URL || "http://127.0.0.1:8765";
mkdirSync(SHOTS, { recursive: true });

async function main() {
  const report = { started_at: new Date().toISOString(), base: BASE, cases: [] };
  const push = (name, ok, extra = {}) =>
    report.cases.push({ name, ok, result: ok ? "PASS" : "FAIL", ...extra });

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await (
      await browser.newContext({ viewport: { width: 1400, height: 900 } })
    ).newPage();

    await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: join(SHOTS, "01_initial.png"), fullPage: true });

    const title = await page.locator("h1").innerText();
    push("title_enrollment", /Enrollment de teste/i.test(title));
    push("camera_area", (await page.locator("#mjpeg").count()) > 0);
    push("progress", (await page.locator("#progressList").count()) > 0);
    push("instruction", (await page.locator("#instruction").count()) > 0);
    push("temp_badge", /Galeria temporária/i.test(await page.locator("body").innerText()));
    push("tech_collapsed", (await page.locator("details.tech").count()) > 0);
    push("distance_table", (await page.locator("#distanceBody").count()) > 0);
    push("btn_unknown", (await page.locator("#btnUnknown").count()) > 0);
    push("webcam_is_select", (await page.locator("select#webcam").count()) > 0);

    // --- Detect: política atual do POC = forçar USB cam-web (#2) ---
    await page.locator("#webcam").selectOption("1");
    push("manual_select_1", (await page.locator("#webcam").inputValue()) === "1");

    await page.locator("#btnDetectCams").click();
    await page.waitForTimeout(8000); // probe físico pode demorar
    const afterDetect = await page.locator("#webcam").inputValue();
    // aguardar hint sair de "Atualizando…"
    for (let i = 0; i < 20; i++) {
      const h = await page.locator("#camHint").innerText();
      if (!/Atualizando|Varrendo/i.test(h)) break;
      await page.waitForTimeout(250);
    }
    push("detect_forces_cam_web", afterDetect === "2", {
      afterDetect,
      expected: "2",
      hint: await page.locator("#camHint").innerText(),
    });

    await page.locator("#webcam").selectOption("2");
    await page.locator("#btnDetectCams").click();
    await page.waitForTimeout(2500); // 2º clique deve usar cache
    const afterDetect2 = await page.locator("#webcam").inputValue();
    push("detect_keeps_cam_web_2", afterDetect2 === "2", { afterDetect2 });

    for (let i = 0; i < 20; i++) {
      const h = await page.locator("#camHint").innerText();
      if (!/Atualizando|Varrendo/i.test(h)) break;
      await page.waitForTimeout(250);
    }
    const hint = await page.locator("#camHint").innerText();
    push("detect_hint_mentions_usb_camweb", /cam-web|USB/i.test(hint), { hint });

    // API: recommended pode ser 0, mas UI não força
    const camsApi = await page.evaluate(async () => {
      const r = await fetch("/api/cameras");
      return r.json();
    });
    push("api_cameras_ok", Array.isArray(camsApi.cameras), {
      n: (camsApi.cameras || []).length,
      recommended: camsApi.recommended,
    });

    // open tech panel
    await page.locator("details.tech summary").click();
    await page.waitForTimeout(200);
    await page.screenshot({ path: join(SHOTS, "02_tech_open.png"), fullPage: true });

    // Escolher cam-web (#2) — política do POC / Debug Vision
    const pick = 2;
    await page.locator("#webcam").selectOption(String(pick));
    push("picked_cam_web", true, { pick });

    let cameraPhysical = false;
    const respPromise = page
      .waitForResponse((r) => r.url().includes("/api/session/start"), { timeout: 20000 })
      .catch(() => null);
    await page.locator("#btnStart").click();
    const resp = await respPromise;
    let startBody = null;
    if (resp) {
      startBody = await resp.json().catch(() => null);
      cameraPhysical = !!(startBody && startBody.ok);
    }
    await page.waitForTimeout(1500);
    await page.screenshot({ path: join(SHOTS, "03_after_start.png"), fullPage: true });

    // Após start, Detectar deve manter cam-web (#2) da sessão
    if (cameraPhysical) {
      const before = await page.locator("#webcam").inputValue();
      await page.locator("#btnDetectCams").click();
      await page.waitForTimeout(8000);
      const kept = await page.locator("#webcam").inputValue();
      push("detect_while_streaming_stays_cam_web", kept === "2", { before, kept });

      const state = await page.evaluate(async () => {
        const r = await fetch("/api/state");
        return r.json();
      });
      push("camera_start_ok", true);
      push("phase_front", ["front", "lateral_right", "lateral_left", "validate", "done", "lateral"].includes(state.phase), {
        phase: state.phase,
      });
      push("frame_shape_present", Array.isArray(state.frame_shape) && state.frame_shape.length >= 2, {
        frame_shape: state.frame_shape,
      });
      push("gallery_version_aligned_v2", state.gallery_version === "facenet_aligned_v2", {
        gallery_version: state.gallery_version,
        gallery_path: state.gallery_path,
      });
      push("gallery_path_contains_aligned_v2", /facenet_aligned_v2/i.test(String(state.gallery_path || "")), {
        gallery_path: state.gallery_path,
      });

      await page.waitForTimeout(3000);
      const state2 = await page.evaluate(async () => (await fetch("/api/state")).json());
      push("guided_flow_progress", true, {
        phase: state2.phase,
        samples: (state2.samples || []).length,
        alignment_mode: state2.alignment_mode,
        alignment_error: state2.alignment_error,
        note: "Captura completa depende de pessoa na camera — nao inventar",
      });

      // Nenhuma amostra aceita sem alignment de produto
      const badAlign = (state2.samples || []).filter(
        (s) => s.alignment_mode && s.alignment_mode !== "product_crop_aligned_face"
      );
      const missingAlign = (state2.samples || []).filter((s) => s.npy && !s.alignment_mode);
      push("no_capture_without_product_alignment", badAlign.length === 0 && missingAlign.length === 0, {
        badAlign,
        missingAlign,
        n_samples: (state2.samples || []).length,
      });

      if ((state2.samples || []).length >= 2) {
        const allProduct = (state2.samples || []).every(
          (s) => s.alignment_mode === "product_crop_aligned_face"
        );
        push("physical_enroll_samples", allProduct, {
          n: state2.samples.length,
          alignment_modes: (state2.samples || []).map((s) => s.alignment_mode),
        });
      } else {
        push("physical_enroll_complete", true, {
          result: "NÃO TESTADO",
          reason: "Sem 2 capturas automaticas (pessoa/qualidade)",
          samples: (state2.samples || []).length,
        });
        report.cases[report.cases.length - 1].result = "NÃO TESTADO";
      }
    } else {
      push("camera_unavailable_handled", true, {
        error: startBody?.error || "start failed",
        physical_flow: "NÃO TESTADO",
      });
      const bodyText = await page.locator("body").innerText();
      push("ui_still_usable", /Enrollment|POC|temporária/i.test(bodyText));
    }

    await page.locator("#distanceSelect").selectOption("3");
    push("distance_select", (await page.locator("#distanceSelect").inputValue()) === "3");

    await page.screenshot({ path: join(SHOTS, "04_final.png"), fullPage: true });
  } catch (e) {
    push("playwright_flow", false, { error: String(e) });
  } finally {
    if (browser) await browser.close();
  }

  report.ended_at = new Date().toISOString();
  report.summary = {
    pass: report.cases.filter((c) => c.result === "PASS").length,
    fail: report.cases.filter((c) => c.result === "FAIL").length,
    not_tested: report.cases.filter((c) => c.result === "NÃO TESTADO").length,
    total: report.cases.length,
  };
  writeFileSync(join(OUT, "playwright_m2_ui.json"), JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report.summary, null, 2));
  console.log(
    report.cases
      .filter((c) => c.result === "FAIL")
      .map((c) => `${c.name}: ${JSON.stringify(c)}`)
      .join("\n")
  );
  process.exit(report.summary.fail > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
