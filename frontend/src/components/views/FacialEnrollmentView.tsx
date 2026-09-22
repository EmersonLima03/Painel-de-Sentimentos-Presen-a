import { useEffect, useState } from "react";
import { useAuth } from "../../cloud/AuthContext";
import { supabase } from "../../cloud/supabaseClient";

/**
 * Cadastro facial — same-origin iframe to /gestor/ (Edge → M2 :8766).
 * Issues gestor gate cookie so unauthenticated browsers cannot open /gestor directly.
 */
export function FacialEnrollmentView() {
  const auth = useAuth();
  const [ready, setReady] = useState(false);
  const [gateError, setGateError] = useState<string | null>(null);
  const [m2Down, setM2Down] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setGateError(null);
      try {
        const health = await fetch("/m2/healthz");
        if (!cancelled) setM2Down(!health.ok);
      } catch {
        if (!cancelled) setM2Down(true);
      }

      let access_token: string | undefined;
      if (supabase) {
        const { data } = await supabase.auth.getSession();
        access_token = data.session?.access_token;
      }
      try {
        const r = await fetch("/dashboard/api/m2-gestor-gate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ access_token }),
        });
        if (!r.ok) {
          if (!cancelled) setGateError("Não foi possível autorizar o cadastro facial. Faça login como gestor.");
          return;
        }
        if (!cancelled) setReady(true);
      } catch {
        if (!cancelled) setGateError("Falha ao preparar sessão do cadastro facial.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [auth.email, auth.userId]);

  if (auth.loading) {
    return <p className="muted">Carregando…</p>;
  }

  if (auth.configured && !auth.email) {
    return (
      <section>
        <h1>Cadastro facial</h1>
        <p className="muted">Entre com a conta de gestor para abrir o cadastro facial.</p>
      </section>
    );
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

  if (!ready) {
    return <p className="muted">Preparando cadastro facial…</p>;
  }

  return (
    <section className="facial-enrollment">
      <header className="facial-enrollment-head">
        <h1>Cadastro facial</h1>
        <p className="muted">
          Cadastro facial permanente dos alunos oficiais (escola → turma → aluno). O QR é individual e
          temporário; o template fica associado ao student_id e disponível para o reconhecimento.
        </p>
      </header>
      <iframe
        title="Cadastro facial — gestor"
        src="/gestor/"
        className="facial-enrollment-frame"
        allow="camera; microphone"
      />
    </section>
  );
}
