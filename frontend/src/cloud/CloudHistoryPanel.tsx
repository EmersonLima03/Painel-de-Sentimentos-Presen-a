import { useEffect, useState } from "react";
import { UnavailableState, EmptyState, LoadingState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/layout/PageHeader";
import { supabase, supabaseConfigured } from "./supabaseClient";

type SessionRow = {
  id: string;
  title: string | null;
  status: string;
  started_at: string;
  ended_at: string | null;
  schools?: { name: string } | null;
  class_groups?: { name: string } | null;
  subjects?: { name: string } | null;
};

/**
 * Histórico real a partir do Supabase (sessões sincronizadas).
 * Se cloud não configurado / sem login, estado honesto.
 */
export function CloudHistoryPanel() {
  const [rows, setRows] = useState<SessionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState<any>(null);

  useEffect(() => {
    if (!supabaseConfigured || !supabase) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr("");
      const { data: sess } = await supabase.auth.getSession();
      if (!sess.session) {
        if (!cancelled) {
          setLoading(false);
          setErr("login_required");
        }
        return;
      }
      const { data, error } = await supabase
        .from("class_sessions")
        .select(
          "id, title, status, started_at, ended_at, schools(name), class_groups(name), subjects(name)"
        )
        .order("started_at", { ascending: false })
        .limit(50);
      if (cancelled) return;
      setLoading(false);
      if (error) {
        setErr(error.message);
        return;
      }
      setRows((data as any) || []);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function openReport(sessionId: string) {
    if (!supabase) return;
    setSelected(null);
    const { data, error } = await supabase
      .from("session_report_snapshots")
      .select("report, captured_at, is_final, schema_version")
      .eq("session_id", sessionId)
      .order("captured_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    if (error) {
      setErr(error.message);
      return;
    }
    if (!data) {
      setErr("snapshot_pending");
      setSelected({ pending: true, session_id: sessionId });
      return;
    }
    setSelected(data);
    setErr("");
  }

  if (!supabaseConfigured) {
    return (
      <UnavailableState
        title="Histórico cloud ainda não configurado"
        message="Defina VITE_SUPABASE_URL e VITE_SUPABASE_ANON_KEY. Até lá, o histórico longitudinal permanece indisponível (sem dados inventados)."
      />
    );
  }

  if (err === "login_required") {
    return (
      <UnavailableState
        title="Faça login para ver o histórico"
        message="O histórico syncado vive no Sentimentos. Use a seção Cloud Auth em Configurações."
      />
    );
  }

  if (loading) return <LoadingState label="Carregando sessões…" />;

  return (
    <section className="cloud-history">
      <PageHeader title="Histórico (cloud)" subtitle="Sessões sincronizadas do Edge" />
      {err && err !== "snapshot_pending" && <p className="error-text">{err}</p>}
      {rows.length === 0 ? (
        <EmptyState title="Nenhuma sessão sincronizada" message="Quando o Edge sincronizar, as aulas aparecerão aqui." />
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Data</th>
              <th>Escola</th>
              <th>Turma</th>
              <th>Disciplina</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.started_at).toLocaleString()}</td>
                <td>{(r.schools as any)?.name || "—"}</td>
                <td>{(r.class_groups as any)?.name || "—"}</td>
                <td>{(r.subjects as any)?.name || "—"}</td>
                <td>{r.status}</td>
                <td>
                  <button type="button" className="btn-link" onClick={() => void openReport(r.id)}>
                    Relatório
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {selected?.pending && (
        <UnavailableState
          title="Relatório ainda não sincronizado"
          message="A sessão existe, mas o snapshot ainda não chegou do Edge. Estado honesto — sem inventar dados."
        />
      )}
      {selected?.report && (
        <pre className="report-json" style={{ maxHeight: 320, overflow: "auto" }}>
          {JSON.stringify(selected.report, null, 2)}
        </pre>
      )}
    </section>
  );
}
