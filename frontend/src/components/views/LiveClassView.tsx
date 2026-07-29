import { useState } from "react";
import { ClimateBars } from "../ClimateBars";
import { MetricCard } from "../ui/MetricCard";
import { FilterBar } from "../ui/FilterBar";
import { Pagination } from "../ui/Pagination";
import { StudentCompactCard } from "../ui/StudentCompactCard";
import { ReviewEventCard } from "../ui/ReviewEventCard";
import { SessionTimeline } from "../ui/SessionTimeline";
import { SectionHeader } from "../ui/SectionHeader";
import { EmptyState } from "../ui/EmptyState";
import { PageHeader } from "../layout/PageHeader";
import { useLiveFilters } from "../../hooks/useLiveFilters";
import { collectReviewEvents, countReviewEvents, isPendingReview } from "../../utils/events";
import { fmtPct } from "../../labels";
import type { WsState } from "../../types";

type Props = {
  k: any;
  tracks: any[];
  events: any[];
  report: any;
  status: any;
  climateDist: any;
  obsPct: number | null;
  elapsed?: number;
  sessionId?: string;
  isDemo: boolean;
  wsState: WsState;
  timeline: any[];
  demoControl: (body: Record<string, unknown>) => Promise<void>;
  onOpenReport: () => void;
};

const FILTERS = [
  { id: "all", label: "Todos" },
  { id: "present", label: "Presentes" },
  { id: "for_review", label: "Para revisão" },
  { id: "inconclusive", label: "Inconclusivos" },
  { id: "not_visible", label: "Não visíveis" },
];

export function LiveClassView({
  k,
  tracks,
  events,
  report,
  status,
  climateDist,
  obsPct,
  elapsed,
  sessionId,
  isDemo,
  wsState,
  timeline,
  demoControl,
  onOpenReport,
}: Props) {
  const [camOpen, setCamOpen] = useState(false);
  const liveFilters = useLiveFilters(tracks);

  const present = k.recognized_people ?? k.present;
  const visible = k.visible_people ?? k.visible ?? tracks.length;
  const observable = k.observable_people ?? k.observable;
  const inconclusive = k.inconclusive_people ?? k.inconclusive;

  const reviewCount = countReviewEvents({
    tracks,
    events,
    reportEventsOpen: report?.events_open,
    kpiActiveEvents: status?.kpis?.active_events ?? k.active_behavioral_signals,
  });

  const reviewList = collectReviewEvents(tracks, events).filter(isPendingReview).slice(0, 12);

  return (
    <section className="live-class-view">
      <PageHeader
        title="Visão ao vivo da turma"
        subtitle="Presença e observação assistida — indicadores estimados"
        wsState={wsState}
        showLive
        elapsed={elapsed}
        runtimeMode={status?.runtime_mode}
        sessionId={sessionId}
        updatedHint="Atualização a cada ~2 s"
      />

      <div className="metric-row">
        <MetricCard
          label="Presentes"
          value={present != null ? present : "—"}
          sub="Identificados nesta sessão"
          tone="primary"
        />
        <MetricCard
          label="Visíveis agora"
          value={visible != null ? visible : "—"}
          sub="Detectados no enquadramento"
        />
        <MetricCard
          label="Observáveis"
          value={
            observable != null
              ? observable
              : obsPct != null
                ? fmtPct(obsPct)
                : "—"
          }
          sub={
            obsPct != null && observable != null
              ? `${fmtPct(obsPct)} com qualidade adequada`
              : "Com qualidade adequada"
          }
        />
        <MetricCard
          label="Inconclusivos"
          value={inconclusive != null ? inconclusive : "—"}
          sub="Observação pausada ou parcial"
        />
        <MetricCard
          label="Para revisão"
          value={reviewCount}
          sub="Eventos pendentes de verificação"
          tone={reviewCount > 0 ? "warn" : "default"}
        />
      </div>

      <div className="live-split">
        <div className="live-main-col">
          <SectionHeader
            title="Alunos"
            subtitle="Grade compacta — presente ≠ visível ≠ observável"
            actions={
              <button type="button" className="btn" onClick={onOpenReport}>
                Abrir relatório da aula
              </button>
            }
          />
          <FilterBar
            search={liveFilters.search}
            onSearch={liveFilters.setSearch}
            filters={FILTERS}
            activeFilter={liveFilters.filter}
            onFilter={(id) => liveFilters.setFilter(id as any)}
          />
          {liveFilters.total === 0 ? (
            <EmptyState
              title="Nenhuma pessoa correspondente"
              message={
                tracks.length === 0
                  ? "Ainda não há dados nesta sessão. Aguarde detecções da câmera."
                  : "Nenhum aluno corresponde aos filtros."
              }
            />
          ) : (
            <>
              <div className="student-grid compact live-student-grid">
                {liveFilters.pageItems.map((tr) => (
                  <StudentCompactCard
                    key={tr.track_id || tr.person_track_id || tr.student_id}
                    track={tr}
                    compact
                  />
                ))}
              </div>
              <Pagination
                page={liveFilters.page}
                pageSize={liveFilters.pageSize}
                total={liveFilters.total}
                onPage={liveFilters.setPage}
              />
            </>
          )}

          <div className="panel" style={{ marginTop: 16 }}>
            <SectionHeader title="Clima visual aparente" subtitle="Distribuição estimada agora" />
            <ClimateBars distribution={climateDist} dominant={k.apparent_climate ?? k.climate} />
          </div>
        </div>

        <aside className="live-side-col">
          <SectionHeader title="Eventos para revisão" subtitle="Sinais visuais — não são afirmações absolutas" />
          {reviewList.length === 0 ? (
            <EmptyState
              title="Nenhum evento pendente"
              message="Nenhuma ocorrência para revisão no momento."
            />
          ) : (
            <div className="review-list">
              {reviewList.map((ev, i) => (
                <ReviewEventCard key={ev.event_id || i} event={ev} />
              ))}
            </div>
          )}
        </aside>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <SectionHeader title="Linha do tempo" subtitle="Últimos minutos da sessão" />
        <SessionTimeline
          climateTimeline={report?.climate_timeline}
          sessionTimeline={timeline}
        />
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <SectionHeader
          title="Câmera"
          subtitle="Prévia opcional — visão técnica permanece em /debug/vision"
          actions={
            <>
              <button type="button" className="btn" onClick={() => setCamOpen((v) => !v)}>
                {camOpen ? "Ocultar prévia" : "Mostrar prévia"}
              </button>
              <a className="btn" href="/debug/vision" target="_blank" rel="noreferrer">
                Abrir visão técnica
              </a>
            </>
          }
        />
        {camOpen && (
          <img
            className="live-mjpeg"
            src="/debug/mjpeg?camera_id=cam-web&overlay=1&fps=10"
            alt="Prévia da câmera ao vivo"
          />
        )}
      </div>

      {isDemo && (
        <div className="demo-controls">
          <button type="button" onClick={() => demoControl({ playing: true })}>
            Play
          </button>
          <button type="button" onClick={() => demoControl({ playing: false })}>
            Pause
          </button>
          <button type="button" onClick={() => demoControl({ reset: true })}>
            Reset
          </button>
          <button type="button" onClick={() => demoControl({ speed: 1 })}>
            1x
          </button>
          <button type="button" onClick={() => demoControl({ speed: 2 })}>
            2x
          </button>
          <button type="button" onClick={() => demoControl({ speed: 5 })}>
            5x
          </button>
        </div>
      )}
    </section>
  );
}
