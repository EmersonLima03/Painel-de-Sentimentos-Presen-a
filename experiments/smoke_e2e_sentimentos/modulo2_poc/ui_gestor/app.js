(() => {
  const STATUS_PT = {
    not_enrolled: "Não cadastrado",
    in_progress: "Em andamento",
    enrolled: "Cadastrado",
    expired: "Expirado",
    revoked: "Revogado",
    failed: "Falhou",
  };

  const els = {
    schoolSelect: document.getElementById("schoolSelect"),
    classSelect: document.getElementById("classSelect"),
    studentCount: document.getElementById("studentCount"),
    setupHint: document.getElementById("setupHint"),
    sourceBadge: document.getElementById("sourceBadge"),
    studentsPanel: document.getElementById("studentsPanel"),
    studentList: document.getElementById("studentList"),
    classHeading: document.getElementById("classHeading"),
    statusSummary: document.getElementById("statusSummary"),
    invitePanel: document.getElementById("invitePanel"),
    inviteName: document.getElementById("inviteName"),
    inviteMeta: document.getElementById("inviteMeta"),
    qrImage: document.getElementById("qrImage"),
    shareLink: document.getElementById("shareLink"),
    btnCopy: document.getElementById("btnCopyLink"),
    copyFeedback: document.getElementById("copyFeedback"),
    btnCloseInvite: document.getElementById("btnCloseInvite"),
    btnRevokeInvite: document.getElementById("btnRevokeInvite"),
  };

  let schools = [];
  let currentInvite = null;
  let pollTimer = null;

  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    const res = await fetch(path, { ...opts, headers, credentials: "same-origin" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(
        (typeof data.detail === "string" ? data.detail : null) ||
          data.error ||
          `HTTP ${res.status}`
      );
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
    const src = data.roster_source || "—";
    if (els.sourceBadge) {
      els.sourceBadge.textContent =
        src === "supabase"
          ? "Dados oficiais (Supabase A)"
          : src === "fixtures"
            ? "Fixtures (lab/teste)"
            : src;
      els.sourceBadge.className = "badge-source " + (src === "supabase" ? "ok" : "lab");
    }
    els.schoolSelect.innerHTML =
      `<option value="">Selecione a escola</option>` +
      schools.map((s) => `<option value="${s.id}">${s.name}</option>`).join("");
    fillClasses();
  }

  function fillClasses() {
    const school = schools.find((s) => s.id === els.schoolSelect.value);
    const groups = school ? school.class_groups : [];
    els.classSelect.innerHTML =
      `<option value="">Selecione a turma</option>` +
      groups.map((c) => `<option value="${c.id}">${c.label}</option>`).join("");
    refreshStatus();
  }

  function statusLabel(raw) {
    return STATUS_PT[raw] || raw;
  }

  function actionButton(st) {
    if (st.facial_status === "enrolled") {
      return `<button type="button" class="btn ghost btn-enroll" data-action="recadastrar" data-student-id="${st.student_id}">Recadastrar</button>`;
    }
    if (st.facial_status === "in_progress") {
      return `<button type="button" class="btn primary btn-enroll" data-action="reabrir" data-student-id="${st.student_id}">Ver convite</button>`;
    }
    return `<button type="button" class="btn primary btn-enroll" data-action="cadastrar" data-student-id="${st.student_id}">Cadastrar rosto</button>`;
  }

  function renderStudents(payload) {
    const items = payload.students || [];
    els.studentsPanel.classList.remove("hidden");
    els.classHeading.textContent = `${payload.school_name} · ${payload.class_label}`;
    els.statusSummary.textContent =
      `${payload.enrolled} cadastrado(s) · ${payload.in_progress} em andamento · ${payload.not_enrolled} sem cadastro`;
    els.studentCount.textContent = `${payload.total} aluno${payload.total === 1 ? "" : "s"}`;
    if (!items.length) {
      els.studentList.innerHTML =
        `<li class="roster-item muted-row"><span class="roster-name">Turma sem alunos ativos</span></li>`;
      return;
    }
    els.studentList.innerHTML = items
      .map(
        (st) => `
      <li class="roster-item student-row" data-status="${st.facial_status}" data-student-id="${st.student_id || ""}">
        <div class="student-main">
          <span class="roster-name">${st.display_name}</span>
          <span class="badge-status ${st.facial_status}">${statusLabel(st.facial_status)}</span>
        </div>
        <div class="student-actions">${actionButton(st)}</div>
      </li>`
      )
      .join("");
  }

  async function refreshStatus() {
    const schoolId = els.schoolSelect.value;
    const classId = els.classSelect.value;
    if (!schoolId || !classId) {
      els.studentsPanel.classList.add("hidden");
      els.studentCount.textContent = "—";
      els.setupHint.textContent = "Selecione a escola e a turma para ver o status facial de cada aluno.";
      return;
    }
    els.setupHint.textContent = "Status facial atualizado a partir do cadastro permanente.";
    try {
      const data = await api(
        `/api/gestor/class-facial-status?school_id=${encodeURIComponent(schoolId)}&class_group_id=${encodeURIComponent(classId)}`
      );
      renderStudents(data);
    } catch (err) {
      els.setupHint.textContent = err.message || "Falha ao carregar status";
    }
  }

  function showInvite(payload) {
    currentInvite = payload;
    els.invitePanel.classList.remove("hidden");
    els.inviteName.textContent = payload.display_name;
    els.inviteMeta.textContent = `${payload.school_name} · ${payload.class_label}`;
    els.shareLink.value = payload.share_link;
    els.qrImage.src =
      payload.qr_image_url ||
      `/api/gestor/students/enroll/qr.png?token=${encodeURIComponent(payload.invite_token)}&t=${Date.now()}`;
    els.studentsPanel.classList.add("hidden");
  }

  function hideInvite() {
    currentInvite = null;
    els.invitePanel.classList.add("hidden");
    refreshStatus();
  }

  async function startEnroll(studentId, replace) {
    const schoolId = els.schoolSelect.value;
    const classId = els.classSelect.value;
    if (!schoolId || !classId || !studentId) return;
    const created = await api("/api/gestor/students/enroll", {
      method: "POST",
      body: JSON.stringify({
        school_id: schoolId,
        class_group_id: classId,
        student_id: studentId,
        replace: !!replace,
      }),
    });
    showInvite(created);
  }

  els.schoolSelect.addEventListener("change", fillClasses);
  els.classSelect.addEventListener("change", () => {
    hideInvite();
    refreshStatus();
  });

  els.studentList.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".btn-enroll");
    if (!btn) return;
    const studentId = btn.getAttribute("data-student-id");
    const action = btn.getAttribute("data-action");
    try {
      btn.disabled = true;
      await startEnroll(studentId, action === "recadastrar");
    } catch (err) {
      alert(err.message || "Falha ao iniciar cadastro");
    } finally {
      btn.disabled = false;
    }
  });

  els.btnCopy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(els.shareLink.value);
      els.copyFeedback.classList.remove("hidden");
      setTimeout(() => els.copyFeedback.classList.add("hidden"), 1800);
    } catch {
      els.shareLink.select();
    }
  });

  els.btnCloseInvite.addEventListener("click", hideInvite);

  els.btnRevokeInvite.addEventListener("click", async () => {
    if (!currentInvite) return;
    try {
      await api("/api/gestor/students/revoke", {
        method: "POST",
        body: JSON.stringify({
          student_id: currentInvite.student_id,
          campaign_id: currentInvite.campaign_id,
        }),
      });
      hideInvite();
    } catch (err) {
      alert(err.message || "Falha ao revogar");
    }
  });

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => {
      if (!els.invitePanel.classList.contains("hidden")) return;
      if (els.schoolSelect.value && els.classSelect.value) refreshStatus();
    }, 8000);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  api("/api/gestor/schools")
    .then((data) => {
      fillSchools(data);
      startPolling();
    })
    .catch((err) => {
      els.setupHint.textContent = err.message || "Falha ao carregar escolas";
    });
})();
