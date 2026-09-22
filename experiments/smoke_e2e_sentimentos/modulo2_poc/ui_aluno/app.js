(() => {
  const TOKEN_RE = /^\/a\/([^/]+)\/?$/;
  const INVITE_RE = /^\/e\/([^/]+)\/?$/;
  const match = window.location.pathname.match(TOKEN_RE);
  const inviteMatch = window.location.pathname.match(INVITE_RE);
  const campaignToken = match ? decodeURIComponent(match[1]) : null;
  const inviteToken = inviteMatch ? decodeURIComponent(inviteMatch[1]) : null;
  const TEST_HOOKS = new URLSearchParams(window.location.search).get("test_hooks") === "1";

  const state = {
    campaignToken,
    inviteToken,
    campaign: null,
    sessionToken: null,
    displayName: null,
    classLabel: null,
    stream: null,
    loopTimer: null,
    sending: false,
  };

  const $ = (id) => document.getElementById(id);
  const screens = {
    boot: $("screenBoot"),
    blocked: $("screenBlocked"),
    claim: $("screenClaim"),
    confirm: $("screenConfirm"),
    intro: $("screenIntro"),
    camDenied: $("screenCamDenied"),
    capture: $("screenCapture"),
    glasses: $("screenGlasses"),
    done: $("screenDone"),
  };

  function show(name) {
    Object.entries(screens).forEach(([k, el]) => {
      if (!el) return;
      el.classList.toggle("hidden", k !== name);
    });
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    return { res, data };
  }

  function paintCodeBoxes(value) {
    const digits = (value || "").replace(/\D/g, "").slice(0, 6).split("");
    const spans = $("codeBoxes").querySelectorAll("span");
    spans.forEach((span, i) => {
      const d = digits[i] || "";
      span.textContent = d;
      span.classList.toggle("filled", Boolean(d));
    });
    $("btnClaimContinue").disabled = digits.length !== 6;
  }

  function setClaimError(msg) {
    const el = $("claimError");
    if (!msg) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    el.textContent = msg;
    el.classList.remove("hidden");
  }

  async function applyClaimedSession(data) {
    state.sessionToken = data.session_token;
    state.displayName = data.display_name;
    state.classLabel = data.class_label;
    sessionStorage.setItem("m2_enroll_session", data.session_token);
    if ($("helloTitle")) $("helloTitle").textContent = `Olá, ${data.display_name}!`;
    if ($("confirmName")) $("confirmName").textContent = data.display_name || "—";
    if ($("confirmClass")) $("confirmClass").textContent = data.class_label || "—";
    if ($("confirmSchool")) $("confirmSchool").textContent = data.school_name || "—";
    show("confirm");
  }

  async function loadInvite() {
    if (!inviteToken) {
      $("blockedTitle").textContent = "Link inválido";
      $("blockedMsg").textContent = "Este endereço de cadastro não é válido.";
      show("blocked");
      return;
    }
    const { res, data } = await api(`/api/aluno/invite/${encodeURIComponent(inviteToken)}`);
    if (!res.ok || !data.ok) {
      $("blockedTitle").textContent = "Convite indisponível";
      $("blockedMsg").textContent =
        data.error || "Este convite expirou ou foi revogado. Peça um novo link ao gestor.";
      show("blocked");
      return;
    }
    await applyClaimedSession(data);
  }

  async function loadCampaign() {
    if (inviteToken) {
      return loadInvite();
    }
    if (!campaignToken) {
      $("blockedTitle").textContent = "Link inválido";
      $("blockedMsg").textContent = "Este endereço de cadastro não é válido.";
      show("blocked");
      return;
    }
    const { res, data } = await api(`/api/aluno/campaign/${encodeURIComponent(campaignToken)}`);
    if (!res.ok || !data.ok) {
      $("blockedTitle").textContent = "Cadastro não encontrado";
      $("blockedMsg").textContent = "Verifique o QR Code com o gestor.";
      show("blocked");
      return;
    }
    if (data.status !== "active") {
      const map = {
        expired: ["Cadastro expirado", "O prazo deste convite terminou. Peça um novo QR ao gestor."],
        revoked: ["Cadastro encerrado", "Este convite foi revogado e não aceita novos cadastros."],
      };
      const pair = map[data.status] || ["Indisponível", "Este cadastro não está disponível no momento."];
      $("blockedTitle").textContent = pair[0];
      $("blockedMsg").textContent = pair[1];
      show("blocked");
      return;
    }
    state.campaign = data;
    $("claimClassLabel").textContent = data.class_label || "Turma";
    show("claim");
    $("claimCode").focus();
  }

  async function submitClaim() {
    const code = ($("claimCode").value || "").replace(/\D/g, "");
    if (code.length !== 6) return;
    setClaimError("");
    $("btnClaimContinue").disabled = true;
    const { res, data } = await api("/api/aluno/claim", {
      method: "POST",
      body: JSON.stringify({
        campaign_token: state.campaignToken,
        claim_code: code,
      }),
    });
    if (!res.ok || !data.ok) {
      setClaimError(data.error || "codigo invalido ou indisponivel");
      $("btnClaimContinue").disabled = false;
      return;
    }
    await applyClaimedSession(data);
  }

  async function declineIdentity() {
    if (state.sessionToken) {
      await api("/api/aluno/session/decline", {
        method: "POST",
        body: JSON.stringify({ session_token: state.sessionToken }),
      });
    }
    stopCamera();
    state.sessionToken = null;
    state.displayName = null;
    sessionStorage.removeItem("m2_enroll_session");
    $("claimCode").value = "";
    paintCodeBoxes("");
    setClaimError("");
    show("claim");
    $("claimCode").focus();
  }

  function goIntro() {
    show("intro");
  }

  function stopCamera() {
    if (state.loopTimer) {
      clearInterval(state.loopTimer);
      state.loopTimer = null;
    }
    if (state.stream) {
      state.stream.getTracks().forEach((t) => t.stop());
      state.stream = null;
    }
    const v = $("camVideo");
    if (v) v.srcObject = null;
  }

  async function startEnrollment() {
    $("btnStartEnroll").disabled = true;
    // 1) Activate session on server
    const { res, data } = await api("/api/aluno/session/start", {
      method: "POST",
      body: JSON.stringify({ session_token: state.sessionToken }),
    });
    if (!res.ok || !data.ok) {
      $("btnStartEnroll").disabled = false;
      setClaimError(data.error || "Sessão indisponível");
      show("claim");
      return;
    }
    state.classLabel = data.class_label || state.classLabel;

    // 2) Camera permission only now
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: "user",
          width: { ideal: 720 },
          height: { ideal: 960 },
        },
      });
    } catch (err) {
      $("btnStartEnroll").disabled = false;
      $("camDeniedMsg").textContent =
        err && err.name === "NotAllowedError"
          ? "Você negou o acesso à câmera. Permita nas configurações do navegador para continuar."
          : "Câmera indisponível neste dispositivo. Tente outro navegador ou aparelho.";
      show("camDenied");
      return;
    }

    $("camVideo").srcObject = state.stream;
    await $("camVideo").play().catch(() => {});
    show("capture");
    applyCaptureUi(data.capture || { step_label: "1 de 4", title: "Olhe para a câmera", subtitle: "", status_human: "Posicione o rosto", pose_guide: "center", stable_pct: 0 });
    startFrameLoop();
  }

  function applyCaptureUi(cap) {
    if (!cap) return;
    if (cap.phase === "glasses_ask" || cap.ui_code === "glasses_ask") {
      stopFrameLoopOnly();
      show("glasses");
      return;
    }
    if (cap.completed || cap.phase === "completed" || cap.ui_code === "completed") {
      finishDone(cap);
      return;
    }
    $("stepPill").textContent = cap.step_label || "";
    $("captureTitle").textContent = cap.title || "";
    $("captureSub").textContent = cap.subtitle || "";
    $("captureStatus").textContent = cap.status_human || "";
    $("holdFill").style.width = `${cap.stable_pct || 0}%`;
    const guide = $("faceGuide");
    guide.classList.remove("guide-center", "guide-left", "guide-right");
    guide.classList.add(`guide-${cap.pose_guide || "center"}`);
    if (cap.capture_flash) {
      const flash = $("captureFlash");
      flash.classList.remove("hidden");
      setTimeout(() => flash.classList.add("hidden"), 400);
    }
    const retry = $("btnRetryStep");
    const showRetry = ["alignment", "adjust"].includes(cap.ui_code);
    retry.classList.toggle("hidden", !showRetry);
  }

  function stopFrameLoopOnly() {
    if (state.loopTimer) {
      clearInterval(state.loopTimer);
      state.loopTimer = null;
    }
  }

  function finishDone(cap) {
    stopCamera();
    // Capture pode concluir no celular e o promote no Edge falhar — nao mentir "sucesso".
    if (cap && cap.product_enrolled === false) {
      $("blockedTitle").textContent = "Cadastro incompleto";
      $("blockedMsg").textContent =
        cap.status_human ||
        cap.promote_error ||
        "A captura terminou, mas a identidade nao foi gravada. Peca um novo convite ao gestor.";
      show("blocked");
      return;
    }
    $("doneMeta").textContent = `${state.displayName || (cap && cap.display_name) || ""} · ${state.classLabel || ""}`;
    show("done");
  }

  function startFrameLoop() {
    stopFrameLoopOnly();
    state.loopTimer = setInterval(() => {
      pushFrame().catch(() => {});
    }, 120);
  }

  async function pushFrame() {
    if (state.sending || !state.sessionToken) return;
    const video = $("camVideo");
    const canvas = $("camCanvas");
    if (!video || video.readyState < 2) return;
    const w = video.videoWidth || 480;
    const h = video.videoHeight || 640;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, w, h);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (!blob) return;
    state.sending = true;
    try {
      const fd = new FormData();
      fd.append("session_token", state.sessionToken);
      fd.append("frame", blob, "frame.jpg");
      const res = await fetch("/api/aluno/session/frame", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        if (res.status === 403) {
          stopCamera();
          $("blockedTitle").textContent = "Sessão encerrada";
          $("blockedMsg").textContent = data.error || "Sessão ou campanha indisponível.";
          show("blocked");
        }
        return;
      }
      applyCaptureUi(data.capture);
    } finally {
      state.sending = false;
    }
  }

  async function glassesChoice(uses) {
    const { res, data } = await api("/api/aluno/session/glasses", {
      method: "POST",
      body: JSON.stringify({ session_token: state.sessionToken, uses_glasses: uses }),
    });
    if (!res.ok || !data.ok) {
      $("captureStatus").textContent = data.error || "Erro";
      return;
    }
    if (data.capture && data.capture.completed) {
      finishDone(data.capture);
      return;
    }
    // needs glasses capture
    show("capture");
    applyCaptureUi(data.capture);
    startFrameLoop();
  }

  // --- Test hooks (Playwright): force steps without real camera ---
  window.__m2Test = {
    forceStep: async (step) => {
      const { res, data } = await api("/api/aluno/session/test/force-step", {
        method: "POST",
        body: JSON.stringify({ session_token: state.sessionToken, step }),
      });
      if (data.capture) applyCaptureUi(data.capture);
      return { res, data };
    },
    startWithoutCamera: async () => {
      const { res, data } = await api("/api/aluno/session/start", {
        method: "POST",
        body: JSON.stringify({ session_token: state.sessionToken }),
      });
      if (res.ok) {
        show("capture");
        applyCaptureUi(data.capture);
      }
      return { res, data };
    },
    getState: () => ({ ...state, sessionToken: state.sessionToken }),
  };

  $("claimCode").addEventListener("input", (e) => {
    const cleaned = e.target.value.replace(/\D/g, "").slice(0, 6);
    e.target.value = cleaned;
    paintCodeBoxes(cleaned);
    setClaimError("");
  });
  $("codeBoxes").addEventListener("click", () => $("claimCode").focus());
  $("btnClaimContinue").addEventListener("click", submitClaim);
  $("btnNotMe").addEventListener("click", declineIdentity);
  $("btnConfirm").addEventListener("click", goIntro);
  $("btnStartEnroll").addEventListener("click", startEnrollment);
  $("btnRetryCam").addEventListener("click", () => {
    $("btnStartEnroll").disabled = false;
    show("intro");
  });
  $("btnRetryStep").addEventListener("click", () => {
    $("captureStatus").textContent = "Vamos tentar de novo — posicione o rosto.";
  });
  $("btnGlassesNo").addEventListener("click", () => glassesChoice(false));
  $("btnGlassesYes").addEventListener("click", () => glassesChoice(true));

  loadCampaign().catch(() => {
    $("blockedTitle").textContent = "Erro de conexão";
    $("blockedMsg").textContent = "Não foi possível carregar a campanha.";
    show("blocked");
  });
})();
