import { useState } from "react";
import { PageHeader } from "../layout/PageHeader";
import { MetricCard } from "../ui/MetricCard";
import { ChartCard } from "../ui/ChartCard";
import { UnavailableState, EmptyState } from "../ui/EmptyState";
import { SectionHeader } from "../ui/SectionHeader";
import { collectReviewEvents, isPendingReview } from "../../utils/events";
import { eventTypePt } from "../../labels";
import { CloudHistoryPanel } from "../../cloud/CloudHistoryPanel";

type Props = {
  events: any[];
  tracks: any[];
  report: any;
};

export function HistoryView({ events, tracks, report }: Props) {
  const [period, setPeriod] = useState<"week" | "month">("week");
  const pending = collectReviewEvents(tracks, events).filter(isPendingReview);

  const byType: Record<string, number> = {};
  for (const ev of pending) {
    const t = String(ev.event_type || "outro");
    byType[t] = (byType[t] || 0) + 1;
  }

  return (
    <section className="history-view">
      <CloudHistoryPanel />

      <PageHeader
        title="Sessão atual (edge)"
        subtitle="Pendências locais em memória — distinto do histórico cloud"
      />

      <div className="period-toggle" role="group" aria-label="Período">
        <button
          type="button"
          className={`filter-chip ${period === "week" ? "active" : ""}`}
          onClick={() => setPeriod("week")}
          aria-pressed={period === "week"}
        >
          Semanal
        </button>
        <button
          type="button"
          className={`filter-chip ${period === "month" ? "active" : ""}`}
          onClick={() => setPeriod("month")}
          aria-pressed={period === "month"}
        >
          Mensal
        </button>
      </div>

      <UnavailableState
        title="Histórico longitudinal ainda não disponível"
        message={`A sessão atual vive em memória. Quando as aulas forem persistidas, o histórico ${period === "week" ? "semanal" : "mensal"} aparecerá aqui — sem dados simulados.`}
      />

      <div className="metric-row">
        <MetricCard label="Média de presença" value="—" unavailable />
        <MetricCard label="Média de observabilidade" value="—" unavailable />
        <MetricCard label="Eventos revisados" value="—" unavailable />
        <MetricCard label="Sessões concluídas" value="—" unavailable />
      </div>

      <div className="history-charts">
        <ChartCard title="Evolução da presença" empty />
        <ChartCard title="Evolução da observabilidade" empty />
        <ChartCard title="Eventos para revisão" empty />
        <ChartCard title="Sessões concluídas" empty />
      </div>

      <div className="panel">
        <SectionHeader
          title="Ocorrências operacionais"
          subtitle="Problemas como câmera offline ou enquadramento — agregação histórica pendente"
        />
        <EmptyState
          title="Nenhuma ocorrência neste período"
          message="Não há histórico operacional agregado para o intervalo selecionado."
        />
      </div>

      <div className="panel">
        <SectionHeader
          title="Pendências de revisão (sessão atual)"
          subtitle="Somente a sessão ativa — não é histórico semanal/mensal"
        />
        {pending.length === 0 ? (
          <EmptyState
            title="Nenhuma pendência"
            message="Nenhum evento pendente de revisão na sessão atual."
          />
        ) : (
          <table className="report-table compact">
            <thead>
              <tr>
                <th>Tipo de evento</th>
                <th>Quantidade</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byType).map(([t, n]) => (
                <tr key={t}>
                  <td>{eventTypePt(t)}</td>
                  <td>{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {report?.events_reviewed != null && (
          <p className="muted">
            Revisados nesta sessão (quando informado): {report.events_reviewed}
          </p>
        )}
      </div>
    </section>
  );
}
