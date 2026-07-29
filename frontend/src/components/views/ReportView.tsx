import { Fragment, useMemo, useState } from "react";
import { ClimateBars } from "../ClimateBars";
import { SessionAnswers } from "../SessionAnswers";
import { StudentRowExpand } from "../StudentRowExpand";
import { MetricCard } from "../ui/MetricCard";
import { FilterBar } from "../ui/FilterBar";
import { Pagination } from "../ui/Pagination";
import { SectionHeader } from "../ui/SectionHeader";
import { EmptyState } from "../ui/EmptyState";
import { PageHeader } from "../layout/PageHeader";
import { SessionTimeline } from "../ui/SessionTimeline";
import { countReviewEvents } from "../../utils/events";
import { exprLabel, fmtDur, fmtPct } from "../../labels";

type Props = {
  report: any;
  summary: any;
  students: any[];
  events: any[];
  tracks: any[];
  status: any;
  timeline: any[];
};

type SectionId = "summary" | "presence" | "signals" | "quality" | "climate" | "students";

const SECTIONS: { id: SectionId; label: string; hint: string }[] = [
  { id: "summary", label: "Resumo", hint: "Visão geral da aula" },
  { id: "presence", label: "Presença", hint: "Quem e por quanto tempo" },
  { id: "signals", label: "Sinais visuais", hint: "Celular, olhos, atenção…" },
  { id: "quality", label: "Qualidade", hint: "O que a câmera observou" },
  { id: "climate", label: "Clima aparente", hint: "Expressão agregada" },
  { id: "students", label: "Por aluno", hint: "Tabela escalável (~30)" },
];

const PAGE_SIZE = 12;

export function ReportView({ report, summary: _summary, students, events, tracks, status, timeline }: Props) {
  const [section, setSection] = useState<SectionId>("summary");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [sortKey, setSortKey] = useState<"name" | "presence" | "observable">("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const reportStudents = report?.students?.length ? report.students : students || [];
  const climateHist = report?.climate_history || {};
  const identified = reportStudents.filter((s: any) => s.student_id);

  const reviewCount = countReviewEvents({
    tracks,
    events,
    reportEventsOpen: report?.events_open,
    kpiActiveEvents: status?.kpis?.active_events,
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = [...reportStudents];
    if (q) {
      list = list.filter((s) => String(s.full_name || s.student_id || "").toLowerCase().includes(q));
    }
    list.sort((a, b) => {
      if (sortKey === "name") {
        const av = String(a.full_name || "");
        const bv = String(b.full_name || "");
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const av = sortKey === "presence" ? Number(a.presence_seconds) || 0 : Number(a.observable_pct) || 0;
      const bv = sortKey === "presence" ? Number(b.presence_seconds) || 0 : Number(b.observable_pct) || 0;
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return list;
  }, [reportStudents, search, sortKey, sortDir]);

  const total = filtered.length;
  const pageSafe = Math.min(page, Math.max(1, Math.ceil(total / PAGE_SIZE) || 1));
  const pageItems = filtered.slice((pageSafe - 1) * PAGE_SIZE, pageSafe * PAGE_SIZE);

  const toggle = (key: string) => setExpanded((prev) => (prev === key ? null : key));
  const toggleSort = (key: typeof sortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  if (!report) {
    return (
      <section>
        <PageHeader title="Relatório da aula" subtitle="Respostas acumuladas da sessão" />
        <EmptyState
          title="Aguardando dados da sessão"
          message="Ainda não há dados nesta sessão. Deixe a câmera rodar alguns minutos."
          hint="O relatório é montado a partir da sessão ativa — sem inventar valores."
        />
      </section>
    );
  }

  const obsProfile = report.observation_profile || {};
  const inconclusiveHint =
    obsProfile.inconclusive_pct != null
      ? fmtPct(obsProfile.inconclusive_pct)
      : obsProfile.inconclusive_periods != null
        ? String(obsProfile.inconclusive_periods)
        : null;

  const activeHint = SECTIONS.find((s) => s.id === section)?.hint;

  return (
    <section className="report-view">
      <PageHeader
        title="Relatório da aula"
        subtitle="Resumo pedagógico da sessão — sem diagnóstico nem ranking"
        runtimeMode={status?.runtime_mode}
        sessionId={report.session_id}
        elapsed={report.duration_seconds}
      />

      <div className="metric-row">
        <MetricCard label="Duração da aula" value={fmtDur(report.duration_seconds)} />
        <MetricCard
          label="Presentes"
          value={report.students_count ?? identified.length}
          sub="Com registro acumulado"
        />
        <MetricCard
          label="Observabilidade média"
          value={report.observable_pct_avg != null ? fmtPct(report.observable_pct_avg) : "—"}
        />
        <MetricCard
          label="Períodos inconclusivos"
          value={inconclusiveHint ?? "—"}
          unavailable={inconclusiveHint == null}
        />
        <MetricCard
          label="Eventos para revisão"
          value={reviewCount}
          tone={reviewCount > 0 ? "warn" : "default"}
        />
      </div>

      <div className="section-tabs report-tabs" role="tablist" aria-label="Seções do relatório">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={section === s.id}
            title={s.hint}
            className={`section-tab ${section === s.id ? "active" : ""}`}
            onClick={() => setSection(s.id)}
          >
            <span className="section-tab-label">{s.label}</span>
            {s.id === "students" && reportStudents.length > 0 && (
              <span className="tab-badge">{reportStudents.length}</span>
            )}
          </button>
        ))}
      </div>
      {activeHint && <p className="report-tab-hint muted">{activeHint}</p>}

      {section === "summary" && (
        <div className="report-tab-panel">
          <div className="panel">
            <SectionHeader
              title="Linha do tempo da aula"
              subtitle="Observabilidade ao longo da sessão"
            />
            <SessionTimeline climateTimeline={report.climate_timeline} sessionTimeline={timeline} />
          </div>
          <div className="panel" style={{ marginTop: 12 }}>
            <SectionHeader
              title="Respostas da aula"
              subtitle="Todas as respostas em um só lugar — use as outras abas para focar"
              actions={
                <button type="button" className="btn" onClick={() => setSection("students")}>
                  Ver por aluno ({reportStudents.length})
                </button>
              }
            />
            <SessionAnswers report={report} students={reportStudents} focus="all" hideTitle />
          </div>
        </div>
      )}

      {section === "presence" && (
        <div className="panel report-tab-panel">
          <SectionHeader
            title="Presença na aula"
            subtitle="Presente ≠ visível no momento. Lista completa na aba Por aluno."
            actions={
              <button type="button" className="btn" onClick={() => setSection("students")}>
                Abrir tabela de alunos
              </button>
            }
          />
          <SessionAnswers report={report} students={reportStudents} focus="presence" hideTitle />
        </div>
      )}

      {section === "signals" && (
        <div className="panel report-tab-panel">
          <SectionHeader
            title="Sinais visuais observados"
            subtitle="Possível interação ≠ uso confirmado. Evento automático ≠ revisado."
          />
          <SessionAnswers report={report} students={reportStudents} focus="signals" hideTitle />
          <div style={{ marginTop: 16 }}>
            <SessionAnswers report={report} students={reportStudents} focus="attention" hideTitle />
          </div>
        </div>
      )}

      {section === "quality" && (
        <div className="panel report-tab-panel">
          <SectionHeader
            title="Qualidade dos dados"
            subtitle="Observável ≠ presente. Inconclusivo ≠ baixa atenção."
          />
          <div className="report-quality-kpis">
            <p>
              Pico visível: <strong>{report.peak_visible ?? "—"}</strong>
            </p>
            <p>
              % observável (média):{" "}
              <strong>
                {report.observable_pct_avg != null ? fmtPct(report.observable_pct_avg) : "—"}
              </strong>
            </p>
          </div>
          <SessionAnswers report={report} students={reportStudents} focus="quality" hideTitle />
          {report.limitations?.length > 0 && (
            <ul className="limitations">
              {report.limitations.map((l: string, i: number) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {section === "climate" && (
        <div className="panel report-tab-panel">
          <SectionHeader
            title="Clima visual aparente"
            subtitle="Estimativa agregada — não é diagnóstico emocional"
          />
          <p>
            Final da sessão:{" "}
            <strong>{report.climate_label_pt || exprLabel(report.climate)}</strong>
          </p>
          {Object.keys(climateHist).length > 0 ? (
            <ClimateBars distribution={climateHist} dominant={report.climate} />
          ) : (
            <EmptyState
              title="Sem amostras de clima"
              message="Ainda não há amostras suficientes de clima visual nesta sessão."
            />
          )}
          <div style={{ marginTop: 16 }}>
            <SessionAnswers report={report} students={reportStudents} focus="expression" hideTitle />
          </div>
        </div>
      )}

      {section === "students" && (
        <div className="panel report-tab-panel">
          <SectionHeader
            title="Detalhe por aluno"
            subtitle="Pensado para turmas (~30): busca, ordenação, paginação e expansão sob demanda"
          />
          <FilterBar
            search={search}
            onSearch={(v) => {
              setSearch(v);
              setPage(1);
            }}
            filters={[]}
            activeFilter=""
            onFilter={() => {}}
            searchPlaceholder="Buscar aluno por nome…"
          />
          <div className="sort-row muted">
            Ordenar:
            <button type="button" className="btn ghost" onClick={() => toggleSort("name")}>
              Nome {sortKey === "name" ? (sortDir === "asc" ? "↑" : "↓") : ""}
            </button>
            <button type="button" className="btn ghost" onClick={() => toggleSort("presence")}>
              Tempo presente {sortKey === "presence" ? (sortDir === "asc" ? "↑" : "↓") : ""}
            </button>
            <button type="button" className="btn ghost" onClick={() => toggleSort("observable")}>
              % observável {sortKey === "observable" ? (sortDir === "asc" ? "↑" : "↓") : ""}
            </button>
          </div>
          {pageItems.length === 0 ? (
            <EmptyState
              title="Nenhum aluno"
              message="Nenhum aluno corresponde aos filtros ou ainda não há acumulado."
            />
          ) : (
            <div className="report-table-wrap">
              <table className="report-table compact">
                <thead>
                  <tr>
                    <th aria-label="Expandir" />
                    <th>Nome</th>
                    <th>Presença</th>
                    <th>Tempo presente</th>
                    <th>% observável</th>
                    <th>Observabilidade</th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((s: any) => {
                    const rowKey = s.person_key || s.student_id || s.track_id || s.full_name;
                    const isOpen = expanded === rowKey;
                    return (
                      <Fragment key={rowKey}>
                        <tr
                          className={`report-row ${isOpen ? "expanded" : ""}`}
                          onClick={() => toggle(rowKey)}
                        >
                          <td className="expand-cell">{isOpen ? "▾" : "▸"}</td>
                          <td>{s.full_name}</td>
                          <td>{s.student_id ? "Presente" : "Detectado"}</td>
                          <td>{fmtDur(s.presence_seconds)}</td>
                          <td>{s.observable_pct != null ? fmtPct(s.observable_pct) : "—"}</td>
                          <td className="muted">{s.observability_note_pt || "—"}</td>
                        </tr>
                        {isOpen && (
                          <tr className="report-row-detail">
                            <td colSpan={6}>
                              <StudentRowExpand student={s} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={pageSafe} pageSize={PAGE_SIZE} total={total} onPage={setPage} />
          <p className="muted answers-hint">
            Mostrando {pageItems.length} de {total} · clique em ▸ para sinais e tempos daquele aluno.
          </p>
        </div>
      )}

      <p className="muted export-hint">
        Exportação CSV disponível apenas no modo demonstração.
        <button
          type="button"
          className="btn"
          disabled={status?.runtime_mode !== "demo"}
          title={
            status?.runtime_mode === "demo"
              ? "Abrir exportação demo"
              : "Disponível no modo demonstração"
          }
          onClick={() => {
            if (status?.runtime_mode === "demo") {
              window.open("/api/v1/demo/report.csv", "_blank");
            }
          }}
        >
          Exportar CSV
        </button>
      </p>
    </section>
  );
}
