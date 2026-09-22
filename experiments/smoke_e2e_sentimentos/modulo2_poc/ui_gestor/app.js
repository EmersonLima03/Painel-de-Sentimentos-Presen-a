(() => {
  const STATUS_PT = {
    pending: "Pendente",
    claimed: "Código usado",
    in_progress: "Em andamento",
    completed: "Concluído",
    failed: "Falhou",
    expired: "Expirado",
    active: "Ativa",
    revoked: "Revogada",
  };

  const els = {
    schoolSelect: document.getElementById("schoolSelect"),
    classSelect: document.getElementById("classSelect"),
    studentCount: document.getElementById("studentCount"),
    btnStart: document.getElementById("btnStartCampaign"),
    setupHint: document.getElementById("setupHint"),
    campaignPanel: document.getElementById("campaignPanel"),
    campaignTitle: document.getElementById("campaignTitle"),
    progressNumbers: document.getElementById("progressNumbers"),
    progressFill: document.getElementById("progressFill"),
    campaignStatus: document.getElementById("campaignStatus"),
    qrImage: document.getElementById("qrImage"),
    shareLink: document.getElementById("shareLink"),
    btnCopy: document.getElementById("btnCopyLink"),
    copyFeedback: document.getElementById("copyFeedback"),
    btnRevoke: document.getElementById("btnRevoke"),
    rosterList: document.getElementById("rosterList"),
    codeList: document.getElementById("codeList"),
  };

  let schools = [];
  let campaignId = null;
  let pollTimer = null;
  let claimSheet = [];

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  function currentClass() {
    const school = schools.find((s) => s.id === els.schoolSelect.value);
    if (!school) return null;
    return school.class_groups.find((c) => c.id === els.classSelect.value) || null;
  }

  function fillSchools(data) {
    schools = data.schools || [];
    els.schoolSelect.innerHTML = schools
      .map((s) => `<option value="${s.id}">${s.name}</option>`)
      .join("");
    fillClasses();
  }

  function fillClasses() {
    const school = schools.find((s) => s.id === els.schoolSelect.value);
    const groups = school ? school.class_groups : [];
    els.classSelect.innerHTML = groups
      .map((c) => `<option value="${c.id}">${c.label}</option>`)
      .join("");
    updateCount();
  }

  function updateCount() {
    const cg = currentClass();
    const n = cg ? cg.student_count : 0;
    els.studentCount.textContent = String(n);
  }

  function statusLabel(raw) {
    return STATUS_PT[raw] || raw;
  }

  function renderRoster(items) {
    els.rosterList.innerHTML = (items || [])
      .map(
        (it) => `
      <li class="roster-item" data-name="${it.display_name}" data-status="${it.status}">
        <span class="roster-name">${it.display_name}</span>
        <span class="badge-status ${it.status}">${statusLabel(it.status)}</span>
      </li>`
      )
      .join("");
  }

  function renderCodes(sheet) {
    claimSheet = sheet || claimSheet;
    els.codeList.innerHTML = claimSheet
      .map(
        (row) => `
      <li class="code-item">
        <span class="code-name">${row.display_name}</span>
        <span class="code-value">${row.claim_code}</span>
      </li>`
      )
      .join("");
  }

  function applyProgress(prog) {
    const total = prog.total || 0;
    const done = prog.completed || 0;
    const pct = total ? (100 * done) / total : 0;
    els.progressNumbers.textContent = `${done} de ${total}`;
    els.progressFill.style.width = `${pct}%`;
    els.campaignTitle.textContent = `Cadastro facial — ${prog.class_label || ""}`;
    els.campaignStatus.textContent = statusLabel(prog.status);
    els.campaignStatus.className = `pill ${prog.status}`;
    const eyebrow = document.querySelector(".hero-copy .eyebrow");
    if (eyebrow) {
      if (prog.status === "active") eyebrow.textContent = "Campanha ativa";
      else if (prog.status === "revoked") eyebrow.textContent = "Campanha revogada";
      else if (prog.status === "expired") eyebrow.textContent = "Campanha expirada";
      else eyebrow.textContent = "Campanha";
    }
    renderRoster(prog.items);
    const active = prog.status === "active";
    els.btnRevoke.disabled = !active;
    els.btnStart.disabled = active;
  }

  function showCampaign(payload) {
    campaignId = payload.campaign_id;
    els.campaignPanel.classList.remove("hidden");
    els.shareLink.value = payload.share_link;
    els.qrImage.src = `/api/gestor/campaigns/${campaignId}/qr.png?t=${Date.now()}`;
    if (payload.claim_sheet) renderCodes(payload.claim_sheet);
    applyProgress({
      total: payload.total ?? payload.roster_count,
      completed: payload.completed ?? 0,
      class_label: payload.class_label,
      status: payload.status,
      items: payload.items || (payload.claim_sheet || []).map((r) => ({
        display_name: r.display_name,
        claim_code: r.claim_code,
        status: "pending",
      })),
    });
    startPolling();
  }

  async function refreshProgress() {
    if (!campaignId) return;
    const prog = await api(`/api/gestor/campaigns/${campaignId}/progress`);
    applyProgress(prog);
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => {
      refreshProgress().catch(() => {});
    }, 2000);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  async function startCampaign() {
    els.btnStart.disabled = true;
    els.setupHint.textContent = "Criando campanha…";
    try {
      const created = await api("/api/gestor/campaigns", {
        method: "POST",
        body: JSON.stringify({
          school_id: els.schoolSelect.value,
          class_group_id: els.classSelect.value,
        }),
      });
      const full = await api(`/api/gestor/campaigns/${created.campaign_id}`);
      showCampaign({ ...created, ...full, claim_sheet: created.claim_sheet });
      els.setupHint.textContent = "Campanha ativa. Compartilhe o QR com a turma.";
    } catch (err) {
      els.setupHint.textContent = `Erro: ${err.message}`;
      els.btnStart.disabled = false;
    }
  }

  async function revokeCampaign() {
    if (!campaignId) return;
    if (!window.confirm("Revogar esta campanha? Novos acessos serão bloqueados.")) return;
    await api(`/api/gestor/campaigns/${campaignId}/revoke`, { method: "POST" });
    await refreshProgress();
    els.setupHint.textContent = "Campanha revogada.";
  }

  async function copyLink() {
    const link = els.shareLink.value;
    try {
      await navigator.clipboard.writeText(link);
    } catch {
      els.shareLink.select();
      document.execCommand("copy");
    }
    els.copyFeedback.classList.remove("hidden");
    setTimeout(() => els.copyFeedback.classList.add("hidden"), 2000);
  }

  els.schoolSelect.addEventListener("change", fillClasses);
  els.classSelect.addEventListener("change", updateCount);
  els.btnStart.addEventListener("click", startCampaign);
  els.btnRevoke.addEventListener("click", revokeCampaign);
  els.btnCopy.addEventListener("click", copyLink);

  api("/api/gestor/schools")
    .then(fillSchools)
    .catch((err) => {
      els.setupHint.textContent = `Falha ao carregar escolas: ${err.message}`;
    });
})();
