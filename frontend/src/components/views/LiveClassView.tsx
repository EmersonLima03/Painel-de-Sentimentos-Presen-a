import { useEffect, useMemo, useState } from "react";
import { ClimateBars } from "../ClimateBars";
import { MetricCard } from "../ui/MetricCard";
import { FilterBar } from "../ui/FilterBar";
import { Pagination } from "../ui/Pagination";
import { StudentCompactCard } from "../ui/StudentCompactCard";
import { AttentionNowCard } from "../ui/AttentionNowCard";
import { LessonHeader } from "../ui/LessonHeader";
import { SessionTimeline } from "../ui/SessionTimeline";
import { SectionHeader } from "../ui/SectionHeader";
import { EmptyState } from "../ui/EmptyState";
import { useLiveFilters } from "../../hooks/useLiveFilters";
import {
  collectAttentionNow,
  countAttentionNow,
  countReviewEvents,
} from "../../utils/events";
import { loadAulaMeta, type AulaMeta } from "../../utils/aulaMeta";
import { fmtPct } from "../../labels";
import type { WsState } from "../../types";
import type { EdgeConnectivity } from "../../utils/friendlyError";

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
  edgeState?: EdgeConnectivity;
  timeline: any[];
  demoControl: (body: Record<string, unknown>) => Promise<void>;
  onOpenReport: () => void;
};

const FILTERS = [
  { id: "all", label: "Todos" },
  { id: "present", label: "Em sala" },
  { id: "attention", label: "Atenção" },
  { id: "for_review", label: "Para revisão" },
  { id: "inconclusive", label: "Inconclusivos" },
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
  edgeState,
  timeline,
  demoControl,
  onOpenReport,
}: Props) {
  const [camOpen, setCamOpen] = useState(false);
  const [aulaMeta, setAulaMeta] = useState<AulaMeta>(() => loadAulaMeta());
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const liveFilters = useLiveFilters(tracks);

  useEffect(() => {
    const onStorage = () => setAulaMeta(loadAulaMeta());
    window.addEventListener("storage", onStorage);
    window.addEventListener("presenca-aula-meta", onStorage);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("presenca-aula-meta", onStorage);
    };
  }, []);

  const present = k.recognized_people ?? k.present;
  const visible = k.visible_people ?? k.visible ?? tracks.length;
  const observable = k.observable_people ?? k.observable;
  const inconclusive = k.inconclusive_people ?? k.inconclusive;

  const attentionNowCount = countAttentionNow(tracks);
  const attentionList = useMemo(() => collectAttentionNow(tracks).slice(0, 12), [tracks]);

  const reviewCount = countReviewEvents({
    tracks,
    events,
    reportEventsOpen: report?.events_open,
    kpiActiveEvents: status?.kpis?.active_events ?? k.active_behavioral_signals,
  });

  const startedAt = status?.session?.started_at;
  const coverage =
    present != null && present > 0 && observable != null
      ? Math.round((100 * Number(observable)) / Number(present))
      : obsPct != null
        ? Math.round(obsPct)
        : null;

  const onFocusStudent = (key: string) => {
    setFocusKey(key);
    liveFilters.setSearch("");
    liveFilters.setFilter("all");
    requestAnimationFrame(() => {
      const el = document.getElementById(`student-${key}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  return (
    <section className="live-class-view live-class-v2">
      <LessonHeader
        meta={aulaMeta}
        startedAt={startedAt}
        elapsedSec={elapsed}
        wsState={wsState}
        edgeState={edgeState}
        runtimeMode={status?.runtime_mode}
        sessionId={sessionId}
      />

      <div className="metric-row metric-row-primary">
        <MetricCard
          label="Presentes"
          value={present != null ? present : "—"}
          sub="Identificados nesta sessão"
          tone="primary"
        />
        <MetricCard
          label="Fora agora"
          value="—"
          unavailable
        />
        <MetricCard
          label="Atenção agora"
          value={attentionNowCount}
          sub="Alunos com sinais ativos neste momento"
          tone={attentionNowCount > 0 ? "warn" : "default"}
        />
        <MetricCard
          label="Para revisão"
          value={reviewCount}
          sub="Ocorrências para conferência posterior"
          tone={reviewCount > 0 ? "warn" : "default"}
        />
      </div>

      <div className="obs-quality-strip" aria-label="Qualidade da observação">
        <strong>Qualidade da observação</strong>
        <span>
          {observable != null && present != null
            ? `${observable} de ${present} com leitura adequada`
            : observable != null
              ? `${observable} com leitura adequada`
              : "Aguardando leituras adequadas"}
          {inconclusive != null ? ` · ${inconclusive} leitura(s) inconclusiva(s)` : ""}
          {coverage != null ? ` · Cobertura estimada: ${fmtPct(coverage)}` : ""}
        </span>
        {visible != null && (
          <span className="muted obs-quality-extra">Visíveis no enquadramento agora: {visible}</span>
        )}
      </div>

      <div className="live-split">
        <div className="live-main-col">
          <SectionHeader
            title="Alunos"
            subtitle="Quem está na sessão e quem merece atenção agora"
            actions={
              <button type="button" className="btn" onClick={onOpenReport}>
                Relatório da sessão atual
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
              title={
                tracks.length === 0
                  ? "Nenhum aluno identificado ainda"
                  : "Nenhum aluno corresponde aos filtros"
              }
              message={
                tracks.length === 0
                  ? "Os alunos aparecerão aqui assim que forem identificados. Aguardando leitura da sala…"
                  : "Ajuste a busca ou o filtro para ver outros alunos."
              }
            />
          ) : (
            <>
              <div className="student-grid compact live-student-grid">
                {liveFilters.pageItems.map((tr) => {
                  const key = String(tr.student_id || tr.person_track_id || tr.track_id || "");
                  return (
                    <StudentCompactCard
                      key={key || tr.track_id}
                      track={tr}
                      compact
                      highlight={focusKey != null && key === focusKey}
                    />
                  );
                })}
              </div>
              <Pagination
                page={liveFilters.page}
                pageSize={liveFilters.pageSize}
                total={liveFilters.total}
                onPage={liveFilters.setPage}
              />
            </>
          )}

          <div className="panel panel-soft" style={{ marginTop: 16 }}>
            <SectionHeader
              title="Expressões aparentes da turma"
              subtitle="Distribuição estimada entre alunos com leitura válida — não é estado psicológico"
            />
            <ClimateBars
              distribution={climateDist}
              dominant={k.apparent_climate ?? k.climate}
              pedagogical
            />
          </div>
        </div>

        <aside className="live-side-col">
          <SectionHeader
            title="Atenção agora"
            subtitle="Sinais acontecendo neste momento"
          />
          {attentionList.length === 0 ? (
            <EmptyState
              title="Nenhum sinal que demande atenção agora"
              message="Quando houver uso aparente de celular, atenção baixa ou olhos fechados, a ocorrência aparece aqui."
            />
          ) : (
            <div className="attention-now-list">
              {attentionList.map((ev, i) => (
                <AttentionNowCard
                  key={ev.event_id || i}
                  item={ev}
                  onFocusStudent={onFocusStudent}
                />
              ))}
            </div>
          )}
          <p className="side-review-hint muted">
            Para revisão (conferência posterior): <strong>{reviewCount}</strong>
            {reviewCount > 0 ? " — veja também o relatório da sessão." : ""}
          </p>
        </aside>
      </div>

      <div className="panel panel-soft" style={{ marginTop: 16 }}>
        <SectionHeader
          title="O que aconteceu nesta aula"
          subtitle="Ocorrências registradas na sessão atual"
        />
        <SessionTimeline
          climateTimeline={report?.climate_timeline}
          sessionTimeline={timeline}
          events={events}
          preferEvents
        />
      </div>

      <div className="panel panel-soft" style={{ marginTop: 16 }}>
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
