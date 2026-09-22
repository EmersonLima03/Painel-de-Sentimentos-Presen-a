const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), { data, status: r.status });
  return data;
}

function qualityText(label) {
  if (label === "good") return "✓ Pose e qualidade OK — segure";
  if (label === "pose") return "↻ Ajuste a pose pedida";
  if (label === "adjust") return "⚠ Ajuste posição/luz";
  return "○ Rosto não detectado";
}

function renderProgress(progress) {
  const map = Object.fromEntries((progress || []).map((p) => [p.id, p.state]));
  document.querySelectorAll("#progressList li").forEach((li) => {
    const st = map[li.dataset.id] || "pending";
    li.classList.remove("active", "done");
    const dot = li.querySelector(".dot");
    if (st === "done") {
      li.classList.add("done");
      dot.textContent = "✓";
    } else if (st === "active") {
      li.classList.add("active");
      dot.textContent = "●";
    } else {
      dot.textContent = "○";
    }
  });
}

function renderDistance(log) {
  const body = $("distanceBody");
  if (!log || !log.length) {
    body.innerHTML = `<tr class="empty"><td colspan="5">Nenhum teste de distância executado ainda.</td></tr>`;
    return;
  }
  body.innerHTML = log
    .map(
      (r) => `<tr>
      <td>${r.distance_m} m</td>
      <td>${r.quality ?? "—"}</td>
      <td>${r.top1_score ?? "—"}</td>
      <td>${r.margin ?? "—"}</td>
      <td>${r.decision ?? "—"}</td>
    </tr>`
    )
    .join("");
}

function renderResult(state, match) {
  const panel = $("resultPanel");
  const m = match || state.last_match;
  const testMode = ["recognize", "unknown", "distance"].includes(state.phase);

  if (!m && state.phase !== "done" && !testMode) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;

  if (testMode) {
    $("doneChecklist").hidden = true;
    if (state.phase === "recognize") {
      $("resultTitle").textContent = "Resultado do reconhecimento";
    } else if (state.phase === "unknown") {
      $("resultTitle").textContent = "Teste: pessoa não cadastrada";
    } else {
      $("resultTitle").textContent = `Teste de distância (${state.distance_m ?? "—"} m)`;
    }
    if (m) {
      $("resultHuman").textContent = m.human || m.decision || "Aguardando…";
      $("resultFail").hidden = !m.fail_test;
      $("rId").textContent = m.top1_id || m.decision || "—";
      $("rScore").textContent = m.top1_score != null ? Number(m.top1_score).toFixed(3) : "—";
      $("rMargin").textContent = m.margin != null ? Number(m.margin).toFixed(3) : "—";
      $("rDecision").textContent = m.decision || "—";
    } else {
      $("resultHuman").textContent = "Olhe para a câmera — comparando com a galeria TEMP…";
      $("resultFail").hidden = true;
      $("rId").textContent = "—";
      $("rScore").textContent = "—";
      $("rMargin").textContent = "—";
      $("rDecision").textContent = "—";
    }
    return;
  }

  if (state.phase === "done") {
    $("resultTitle").textContent = "Cadastro de teste concluído";
    $("resultHuman").textContent = `${state.student_name} · ${state.n_ok_samples} amostra(s) na galeria TEMP`;
    $("resultFail").hidden = true;
    const ul = $("doneChecklist");
    ul.hidden = false;
    ul.innerHTML = (state.samples || [])
      .map((s) => `<li>✓ Captura ${s.step} (qualidade ${s.quality})</li>`)
      .concat(["✓ Embeddings gerados", "✓ Galeria temporária criada"])
      .map((t) => `<li>${t}</li>`)
      .join("");
    // Se já houver um match recente, mostra embaixo do checklist
    if (m) {
      $("rId").textContent = m.top1_id || m.decision || "—";
      $("rScore").textContent = m.top1_score != null ? Number(m.top1_score).toFixed(3) : "—";
      $("rMargin").textContent = m.margin != null ? Number(m.margin).toFixed(3) : "—";
      $("rDecision").textContent = m.decision || "—";
    }
    return;
  }

  $("doneChecklist").hidden = true;
  if (m) {
    $("resultTitle").textContent = "Resultado";
    $("resultHuman").textContent = m.human || m.decision;
    $("resultFail").hidden = !m.fail_test;
    $("rId").textContent = m.top1_id || m.decision || "—";
    $("rScore").textContent = m.top1_score != null ? Number(m.top1_score).toFixed(3) : "—";
    $("rMargin").textContent = m.margin != null ? Number(m.margin).toFixed(3) : "—";
    $("rDecision").textContent = m.decision || "—";
  }
}

function renderTech(state) {
  $("tCam").textContent = state.camera_ok ? `index OK` : state.camera_error || "indisponível";
  $("tRes").textContent = state.frame_shape ? state.frame_shape.join(" × ") : "—";
  $("tFace").textContent = state.face_px ? state.face_px.join(" × ") : "—";
  $("tQ").textContent = state.quality_score != null ? state.quality_score.toFixed(3) : "—";
  $("tModel").textContent = state.model_name || "—";
  const m = state.last_match;
  $("tSM").textContent = m ? `${m.top1_score ?? "—"} / ${m.margin ?? "—"}` : "—";
  $("tDist").textContent = state.distance_m != null ? `${state.distance_m} m` : "—";
  $("tTs").textContent = new Date().toISOString();
  $("tGal").textContent = state.gallery_path || "—";
  $("tDec").textContent = m?.decision || "—";
  $("tThr").textContent = `T=${state.threshold_exp} M=${state.margin_exp} (POC)`;
}

function applyState(state) {
  $("instruction").textContent = state.instruction || "";
  $("statusHuman").textContent = state.status_human || "";
  const pill = $("qualityPill");
  pill.className = `pill q-${state.quality_label || "none"}`;
  pill.textContent = qualityText(state.quality_label);
  renderProgress(state.progress);
  renderDistance(state.distance_log);
  renderResult(state);
  renderTech(state);
  $("captureFlash").hidden = !state.capturing;

  const poseEl = $("poseHint");
  if (poseEl) {
    const yaw =
      state.yaw == null ? "—" : (state.yaw > 0 ? "+" : "") + Number(state.yaw).toFixed(2);
    poseEl.textContent = state.pose_hint
      ? `${state.pose_hint} · yaw ${yaw}`
      : `yaw ${yaw}`;
  }
  const bar = $("stableBar");
  if (bar) {
    const pct = Math.max(0, Math.min(100, state.stable_pct || 0));
    bar.style.width = pct + "%";
    bar.dataset.ok = state.pose_ok && state.quality_label === "good" ? "1" : "0";
  }
  const hold = $("holdLabel");
  if (hold) {
    if (state.phase === "done") hold.textContent = "Cadastro OK — use os testes à direita";
    else if (state.phase === "recognize") hold.textContent = "Modo: reconhecimento";
    else if (state.phase === "unknown") hold.textContent = "Modo: UNKNOWN";
    else if (state.phase === "distance") hold.textContent = `Modo: distância ${state.distance_m} m`;
    else hold.textContent = `Segure: ${state.stable || 0}/${state.stable_needed || 18}`;
  }
  const guide = $("guideOverlay");
  if (guide) {
    const g = state.pose_guide || "none";
    guide.className = `guide-overlay guide-${g}` + (state.pose_ok ? " guide-ok" : "");
  }
}

async function poll() {
  try {
    const state = await api("/api/state");
    applyState(state);
  } catch (_) {
    /* ignore transient */
  }
}

function webcamIndex() {
  const n = Number($("webcam").value);
  return Number.isFinite(n) ? n : 0;
}

function fillWebcamSelect(cams, { keepSelection = true, recommended = null, camWeb = null } = {}) {
  const sel = $("webcam");
  const prev = keepSelection ? sel.value : null;
  const cfgIdx = camWeb && camWeb.index != null ? String(camWeb.index) : "2";
  sel.innerHTML = "";
  const list = cams.length
    ? cams
    : [{ index: 2, has_image: true, w: 1920, h: 1080 }, { index: 0 }, { index: 1 }];
  for (const c of list) {
    const opt = document.createElement("option");
    opt.value = String(c.index);
    const tag = c.has_image === false ? "preto" : c.has_image ? "ok" : "";
    const res = c.w && c.h ? `${c.w}x${c.h}` : "";
    const isUsb = String(c.index) === cfgIdx;
    opt.textContent =
      `#${c.index}${res ? " " + res : ""}${tag ? " (" + tag + ")" : ""}` +
      (isUsb ? " ← USB cam-web" : "");
    sel.appendChild(opt);
  }
  // Preferir cam-web; so mantem escolha previa se o usuario ja mudou de proposito
  if (prev != null && prev !== cfgIdx && [...sel.options].some((o) => o.value === prev)) {
    sel.value = prev;
  } else if ([...sel.options].some((o) => o.value === cfgIdx)) {
    sel.value = cfgIdx;
  } else if (recommended != null && [...sel.options].some((o) => o.value === String(recommended))) {
    sel.value = String(recommended);
  }
}

$("btnDetectCams").onclick = async (ev) => {
  const sel = $("webcam");
  const before = sel.value;
  const force = !!(ev && ev.shiftKey);
  $("camHint").textContent = force
    ? "Varrendo de novo (LED pode piscar)…"
    : "Atualizando lista…";
  try {
    const data = await api(force ? "/api/cameras?refresh=1" : "/api/cameras");
    const cams = data.cameras || [];
    if (!cams.length) {
      $("camHint").textContent = "Nenhuma câmera encontrada. Reconecte o USB e feche apps que usem webcam.";
      return;
    }
    fillWebcamSelect(cams, {
      keepSelection: false, // apos detectar, forca cam-web (USB)
      recommended: data.recommended,
      camWeb: data.cam_web,
    });
    const after = sel.value;
    const cw = data.cam_web || {};
    $("camHint").textContent =
      `USB cam-web = #${cw.index ?? 2} @ ${cw.width || 1920}x${cw.height || 1080} (igual Debug Vision). ` +
      cams
        .map((c) => {
          const tag = c.has_image ? "ok" : "preto";
          return `#${c.index} ${c.w || "?"}x${c.h || "?"} (${tag})`;
        })
        .join(" · ") +
      ` · selecionada #${after}` +
      (data.cached ? " · cache" : "");
  } catch (e) {
    $("camHint").textContent = "Falha ao detectar: " + e.message;
  }
};

$("btnStart").onclick = async () => {
  try {
    const data = await api("/api/session/start", {
      method: "POST",
      body: JSON.stringify({
        student_id: $("studentId").value.trim() || "lab01",
        student_name: $("studentName").value.trim() || "Pessoa de teste",
        webcam: webcamIndex(),
      }),
    });
    applyState(data.state || (await api("/api/state")));
    // refresh mjpeg
    $("mjpeg").src = "/api/mjpeg?" + Date.now();
  } catch (e) {
    alert("Câmera indisponível: " + (e.data?.error || e.message));
    if (e.data?.state) applyState(e.data.state);
  }
};

$("btnStop").onclick = async () => {
  const data = await api("/api/session/stop", { method: "POST", body: "{}" });
  applyState(data.state);
};

async function runMatch(extra = {}) {
  const data = await api("/api/match", {
    method: "POST",
    body: JSON.stringify(extra),
  });
  const state = await api("/api/state");
  applyState(state);
  renderResult(state, data);
  return data;
}

$("btnRecognize").onclick = async () => {
  $("instruction").textContent = "Teste de reconhecimento em andamento…";
  $("statusHuman").textContent = "Comparando com a galeria TEMP";
  await api("/api/mode/recognize", {
    method: "POST",
    body: JSON.stringify({ webcam: webcamIndex() }),
  });
  $("mjpeg").src = "/api/mjpeg?" + Date.now();
  const data = await runMatch({ expected: $("studentId").value.trim() || "lab01" });
  $("resultPanel").hidden = false;
  $("resultPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  if (data && data.ok === false) {
    $("statusHuman").textContent = "Não reconhecido / falha no teste";
  } else if (data) {
    $("statusHuman").textContent = data.human || "Reconhecimento concluído";
  }
};

$("btnUnknown").onclick = async () => {
  await api("/api/mode/unknown", {
    method: "POST",
    body: JSON.stringify({ webcam: webcamIndex() }),
  });
  $("mjpeg").src = "/api/mjpeg?" + Date.now();
  await runMatch({ expected: "UNKNOWN" });
};

$("btnDistance").onclick = async () => {
  const d = Number($("distanceSelect").value);
  await api("/api/mode/distance", {
    method: "POST",
    body: JSON.stringify({ distance_m: d, webcam: webcamIndex() }),
  });
  $("mjpeg").src = "/api/mjpeg?" + Date.now();
  await runMatch({ expected: $("studentId").value.trim() || "lab01" });
};

setInterval(poll, 400);
poll();
