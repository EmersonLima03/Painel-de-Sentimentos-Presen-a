import { StudentCard } from "./components/StudentCard";
import { AppShell } from "./components/layout/AppShell";
import { LiveClassView } from "./components/views/LiveClassView";
import { ReportView } from "./components/views/ReportView";
import { SchoolView } from "./components/views/SchoolView";
import { HistoryView } from "./components/views/HistoryView";
import { SettingsView } from "./components/views/SettingsView";
import { AdminShellView } from "./components/views/admin/AdminShellView";
import { LoadingState, ErrorState } from "./components/ui/EmptyState";
import { useDashboardData } from "./hooks/useDashboardData";
import { useAuth } from "./cloud/AuthContext";
import { DEMO_BANNER } from "./labels";
import type { Tab } from "./types";

const QA_QUERY = new URLSearchParams(window.location.search).get("qa") === "1";

export function App() {
  const auth = useAuth();
  const {
    tab,
    setTab,
    loading,
    err,
    status,
    summary,
    tracks,
    timeline,
    students,
    events,
    report,
    perf,
    wsState,
    sessionId,
    isDemo,
    reviewFilter,
    setReviewFilter,
    notes,
    setNotes,
    filteredEvents,
    patchReview,
    demoControl,
    k,
    climateDist,
    obsPct,
    elapsed,
  } = useDashboardData();

  const productItems: { id: Tab; label: string; badge?: number }[] = [
    { id: "live", label: "Ao vivo", badge: tracks.length || undefined },
    { id: "report", label: "Relatórios" },
    { id: "school", label: "Escola" },
    { id: "history", label: "Histórico" },
    { id: "settings", label: "Configurações" },
  ];

  const adminItems: { id: Tab; label: string }[] = auth.email
    ? [{ id: "admin", label: auth.isGestor ? "Administração" : "Minhas turmas" }]
    : [];

  const qaItems: { id: Tab; label: string }[] = QA_QUERY
    ? [
        { id: "students", label: "Alunos (QA)" },
        { id: "review", label: "Eventos (QA)" },
        { id: "system", label: "Sistema (QA)" },
      ]
    : [];

  const effectiveTab: Tab = tab === "overview" ? "live" : tab;

  return (
    <AppShell
      active={effectiveTab}
      onNavigate={setTab}
      productItems={productItems}
      adminItems={adminItems}
      qaItems={qaItems}
      demoBanner={isDemo ? <div className="demo-banner">{DEMO_BANNER}</div> : null}
    >
      {loading && <LoadingState />}
      {err && !loading && <ErrorState message={err} />}

      {!loading && effectiveTab === "live" && (
        <LiveClassView
          k={k}
          tracks={tracks}
          events={events}
          report={report}
          status={status}
          climateDist={climateDist}
          obsPct={obsPct}
          elapsed={elapsed}
          sessionId={sessionId}
          isDemo={isDemo}
          wsState={wsState}
          timeline={timeline}
          demoControl={demoControl}
          onOpenReport={() => setTab("report")}
        />
      )}

      {!loading && effectiveTab === "report" && (
        <ReportView
          report={report}
          summary={summary}
          students={students}
          events={events}
          tracks={tracks}
          status={status}
          timeline={timeline}
        />
      )}

      {effectiveTab === "school" && <SchoolView active={effectiveTab === "school"} />}

      {!loading && effectiveTab === "history" && (
        <HistoryView events={events} tracks={tracks} report={report} />
      )}

      {!loading && effectiveTab === "settings" && (
        <SettingsView status={status} qaEnabled={QA_QUERY} />
      )}

      {!loading && effectiveTab === "admin" && <AdminShellView />}

      {effectiveTab === "students" && QA_QUERY && (
        <section>
          <h1>Alunos ({tracks.length || students.length})</h1>
          <p className="muted">Aba interna QA — sem ranking</p>
          <div className="student-grid">
            {(tracks.length ? tracks : students).map((tr: any) => (
              <StudentCard key={tr.track_id || tr.student_id || tr.full_name} track={tr} />
            ))}
          </div>
        </section>
      )}

      {effectiveTab === "review" && QA_QUERY && (
        <section>
          <div className="qa-banner panel">
            <strong>Aba técnica (QA)</strong>
            <p>
              Esta lista é jargão interno. Para o professor, use{" "}
              <button type="button" className="linkish" onClick={() => setTab("report")}>
                Relatório da aula
              </button>
              .
            </p>
          </div>
          <h1>Eventos e revisão (QA)</h1>
          <div className="filters">
            <label>
              Status{" "}
              <select value={reviewFilter} onChange={(e) => setReviewFilter(e.target.value)}>
                <option value="">todos</option>
                <option value="pending">pendente</option>
                <option value="confirmed">confirmado</option>
                <option value="rejected">rejeitado</option>
                <option value="inconclusive">inconclusivo</option>
              </select>
            </label>
          </div>
          {filteredEvents.length === 0 && <p className="muted">Nenhum evento.</p>}
          {filteredEvents.map((e) => (
            <div className="event" key={e.event_id}>
              <div>
                <strong>{e.event_type}</strong> · {e.student_id || e.candidate_student_id || "track"} · conf=
                {e.confidence}
              </div>
              <div className="muted">sinais: {(e.reasons || []).join(", ")}</div>
              <div>review: {e.review_status || e.attribution_status || e.status}</div>
              <input
                placeholder="notas"
                value={notes[e.event_id] || ""}
                onChange={(ev) => setNotes({ ...notes, [e.event_id]: ev.target.value })}
              />
              <div className="row">
                <button type="button" onClick={() => patchReview(e.event_id, "confirmed")}>
                  Confirmar
                </button>
                <button type="button" onClick={() => patchReview(e.event_id, "rejected")}>
                  Rejeitar
                </button>
                <button type="button" onClick={() => patchReview(e.event_id, "inconclusive")}>
                  Inconclusivo
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      {effectiveTab === "system" && QA_QUERY && (
        <section>
          <h1>Sistema (QA)</h1>
          <pre>{JSON.stringify({ modules: status?.modules, performance: perf }, null, 2)}</pre>
        </section>
      )}
    </AppShell>
  );
}
