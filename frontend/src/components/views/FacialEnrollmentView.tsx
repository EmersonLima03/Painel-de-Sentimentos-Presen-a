import { useEffect, useState } from "react";
import { useAuth } from "../../cloud/AuthContext";
import { supabase } from "../../cloud/supabaseClient";

/**
 * Cadastro facial — same-origin M2 gestor UI (Edge → M2 :8766).
 *
 * Cloudflare often blocks iframe *navigation* to /gestor/ (frame stays about:blank
 * or never runs app.js). Fetching HTML after the gate cookie and injecting via
 * srcDoc keeps same-origin APIs/cookies and still runs the gestor boot script.
 */
export function FacialEnrollmentView() {
  const auth = useAuth();
  const [frameHtml, setFrameHtml] = useState<string | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const [m2Down, setM2Down] = useState(false);
  const [loadingFrame, setLoadingFrame] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setGateError(null);
      setFrameHtml(null);
      setLoadingFrame(false);

      if (!auth.canManageFacial) {
        if (!cancelled) {
          setGateError(
            "Seu perfil não tem permissão para cadastro facial. Use uma conta de gestor, coordenador ou administrador.",
          );
        }
        return;
      }

      try {
        const health = await fetch("/m2/healthz");
        if (!cancelled) setM2Down(!health.ok);
        if (!health.ok) return;
      } catch {
        if (!cancelled) setM2Down(true);
        return;
      }

      let access_token: string | undefined;
      if (supabase) {
        const { data } = await supabase.auth.getSession();
        access_token = data.session?.access_token;
      }
      if (!access_token) {
        if (!cancelled) setGateError("Sessão expirada. Faça login novamente.");
        return;
      }

      try {
        const r = await fetch("/dashboard/api/m2-gestor-gate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            access_token,
            school_id: auth.activeSchoolId,
          }),
        });
        if (!r.ok) {
          const detail = await r.text();
          if (!cancelled) {
            setGateError(
              detail.includes("forbidden") || r.status === 403
                ? "Permissão insuficiente para cadastro facial nesta escola."
                : "Não foi possível autorizar o cadastro facial. Faça login como gestor.",
            );
          }
          return;
        }

        if (cancelled) return;
        setLoadingFrame(true);
        const htmlRes = await fetch(`/gestor/?embed=1&v=${Date.now()}`, {
          credentials: "same-origin",
          headers: { Accept: "text/html" },
        });
        const html = await htmlRes.text();
        if (!htmlRes.ok || !html.includes("schoolSelect")) {
          if (!cancelled) {
            setGateError(
              "Não foi possível carregar a interface de cadastro facial. Recarregue a página.",
            );
          }
          return;
        }
        if (!cancelled) {
          setFrameHtml(html);
          setLoadingFrame(false);
        }
      } catch {
        if (!cancelled) {
          setLoadingFrame(false);
          setGateError("Falha ao preparar sessão do cadastro facial.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [auth.email, auth.userId, auth.canManageFacial, auth.activeSchoolId]);

  if (auth.loading) {
    return <p className="muted">Carregando…</p>;
  }

  if (gateError) {
    return (
      <section>
        <h1>Cadastro facial</h1>
        <p className="muted">{gateError}</p>
      </section>
    );
  }

  if (m2Down) {
    return (
      <section>
        <h1>Cadastro facial</h1>
        <p className="muted">
          O serviço de cadastro facial (M2) está offline. O restante do painel continua disponível.
          Inicie o M2 na porta 8766 ou use o script de boot Edge+M2.
        </p>
      </section>
    );
  }

  if (!frameHtml || loadingFrame) {
    return (
      <section>
        <h1>Cadastro facial</h1>
        <p className="muted">Preparando sessão…</p>
      </section>
    );
  }

  return (
    <section className="facial-enrollment-view">
      <h1>Cadastro facial</h1>
      <iframe
        title="Cadastro facial — gestor"
        srcDoc={frameHtml}
        className="facial-enrollment-frame"
        allow="camera; microphone"
      />
    </section>
  );
}
