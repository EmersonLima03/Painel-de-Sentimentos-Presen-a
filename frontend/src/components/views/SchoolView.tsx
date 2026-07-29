import { useEffect, useState } from "react";
import { PageHeader } from "../layout/PageHeader";
import { MetricCard } from "../ui/MetricCard";
import { UnavailableState, EmptyState, LoadingState } from "../ui/EmptyState";
import { DeviceStatusCard } from "../ui/DeviceStatusCard";
import { SectionHeader } from "../ui/SectionHeader";
import { toFriendlyError } from "../../utils/friendlyError";

type Props = {
  active: boolean;
};

/**
 * Fetch de GET /dashboard/api/overview SOMENTE quando a tela está ativa.
 * Não entra no poll global de 2s. Falha silenciosa → UnavailableState.
 */
export function SchoolView({ active }: Props) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setErr("");
      try {
        const token = localStorage.getItem("api_token") || "";
        const headers: HeadersInit = token ? { "X-API-Token": token } : {};
        const r = await fetch("/dashboard/api/overview", { headers });
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const json = await r.json();
        if (!cancelled) setData(json);
      } catch (e) {
        toFriendlyError(e);
        if (!cancelled) {
          setData(null);
          setErr("overview_unavailable");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [active]);

  const cameras = data?.cameras;
  const system = data?.system;
  const observability = data?.observability;
  const session = data?.session;

  return (
    <section className="school-view">
      <PageHeader
        title="Visão da escola"
        subtitle="Visão operacional do dispositivo local — agregação multi-turma ainda não disponível"
      />

      {loading && <LoadingState label="Carregando visão da escola…" />}

      {!loading && err && (
        <UnavailableState
          title="Fonte não disponível"
          message="Não foi possível obter o resumo operacional deste dispositivo. As telas Ao vivo e Relatório não são afetadas."
        />
      )}

      {!loading && !err && (
        <>
          <div className="metric-row">
            <MetricCard label="Turmas hoje" value="—" unavailable />
            <MetricCard label="Aulas em andamento" value="—" unavailable />
            <MetricCard
              label="Alunos presentes (sessão local)"
              value={session?.present_count != null ? session.present_count : "—"}
              unavailable={session?.present_count == null}
              sub="Somente sessão deste dispositivo"
            />
            <MetricCard label="Sessões com boa cobertura" value="—" unavailable />
            <MetricCard
              label="Eventos pendentes"
              value={
                observability?.pending_review != null ? observability.pending_review : "—"
              }
              unavailable={observability?.pending_review == null}
              tone={observability?.pending_review > 0 ? "warn" : "default"}
            />
            <MetricCard
              label="Dispositivos offline"
              value={
                cameras?.total != null && cameras?.online != null
                  ? Math.max(0, Number(cameras.total) - Number(cameras.online))
                  : "—"
              }
              unavailable={cameras?.total == null || cameras?.online == null}
              tone="default"
            />
          </div>

          <div className="panel">
            <SectionHeader
              title="Turmas em andamento"
              subtitle="Agregação multi-turma / multi-escola ainda não disponível neste edge"
            />
            <EmptyState
              title="Lista de turmas indisponível"
              message="Este dispositivo não lista turmas da escola. A visão escolar completa depende de agregação backend ainda não exposta."
              hint="Use a visão Ao vivo para a sessão local."
            />
          </div>

          <div className="school-grid">
            <DeviceStatusCard
              online={cameras?.online}
              total={cameras?.total}
              items={cameras?.items}
            />
            <div className="panel">
              <SectionHeader title="Contexto do dispositivo" />
              {system?.school_id ? (
                <p>
                  Identificador configurado: <code>{system.school_id}</code>
                  <span className="muted"> (não é o nome da escola)</span>
                </p>
              ) : (
                <p className="muted">Nenhum identificador de escola configurado no payload.</p>
              )}
              {system?.device_id && (
                <p className="muted">
                  Dispositivo: <code>{system.device_id}</code>
                </p>
              )}
              <UnavailableState
                title="Filtros escola / turno / série"
                message="Filtros de data, turno, série e turma ainda não possuem dados agregados neste dispositivo."
              />
            </div>
          </div>
        </>
      )}
    </section>
  );
}
