import { StudentCard } from "./components/StudentCard";
import { ClimateBars } from "./components/ClimateBars";
import { ReportPanel } from "./components/ReportPanel";
import { OverviewHero } from "./components/OverviewHero";
import { useDashboardData } from "./hooks/useDashboardData";
import { DEMO_BANNER, DISCLAIMER } from "./labels";

type Tab = "overview" | "live" | "students" | "report" | "review" | "system";

const QA_QUERY = new URLSearchParams(window.location.search).get("qa") === "1";

export function App() {
  const {
    tab,
    setTab,
    loading,
    err,
    status,
    summary,
    tracks,
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

  const productTabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Visão geral" },
    { id: "live", label: "Ao vivo" },
    { id: "report", label: "Respostas da aula" },
  ];

  // Abas técnicas só com ?qa=1 — não são o painel pedagógico
  const qaTabs: { id: Tab; label: string }[] = QA_QUERY
    ? [
        { id: "students", label: "Alunos (QA)" },
        { id: "review", label: "Eventos (QA)" },
        { id: "system", label: "Sistema (QA)" },
      ]
    : [];

  const tabs = [...productTabs, ...qaTabs];

  return (
    <div className="app">
      {isDemo && <div className="demo-banner">{DEMO_BANNER}</div>}
      <header className="top">
        <div className="top-row">
          <div>
            <strong className="brand">Presença</strong>
            <span className="muted"> · painel da aula</span>
          </div>
          <div className="live-pill">
            <span className={`dot ${wsState === "connected" ? "on" : ""}`} />
            {wsState === "connected" ? "Ao vivo" : wsState}
          </div>
        </div>
        <p className="disclaimer">{DISCLAIMER}</p>
        <div className="meta">
          <span>modo: {status?.runtime_mode || "…"}</span>
          {sessionId && <span>sessão: {sessionId.slice(0, 8)}…</span>}
          {elapsed != null && <span>tempo: {Math.floor(elapsed / 60)} min</span>}
        </div>
      </header>
      <nav className="tabs">
        {tabs.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
            {t.id === "live" && tracks.length > 0 && <span className="tab-badge">{tracks.length}</span>}
          </button>
        ))}
      </nav>
      <main>
        {loading && <p className="muted">Carregando…</p>}
        {err && <p className="error">Erro: {err}</p>}

        {tab === "overview" && !loading && (
          <section className="overview">
            <OverviewHero k={k} obsPct={obsPct} elapsed={elapsed} />
            <div className="answers-cta panel">
              <h2>Onde estão as respostas claras?</h2>
              <p>
                Na aba <strong>Respostas da aula</strong>: quem esteve presente, por quanto tempo, atenção/clima
                e sinais com duração em português.
              </p>
              <button type="button" className="btn primary" onClick={() => setTab("report")}>
                Abrir respostas da aula
              </button>
              {QA_QUERY && (
                <p className="muted" style={{ marginTop: 8 }}>
                  Você está em modo QA (<code>?qa=1</code>). A aba Eventos é técnica — use só para revisão
                  interna.
                </p>
              )}
            </div>
            <div className="overview-grid">
              <div className="panel">
                <h2>Clima visual aparente</h2>
                <p className="panel-sub">Distribuição estimada das expressões observáveis agora</p>
                <ClimateBars distribution={climateDist} dominant={k.apparent_climate ?? k.climate} />
              </div>
              <div className="panel">
                <h2>Alunos no enquadramento</h2>
                <p className="panel-sub">Visão compacta — detalhes no relatório ao final da aula</p>
                {tracks.length === 0 && <p className="muted empty-hint">Nenhuma pessoa detectada.</p>}
                <div className="student-grid compact">
                  {tracks.map((tr) => (
                    <StudentCard key={tr.track_id || tr.person_track_id} track={tr} compact />
                  ))}
                </div>
              </div>
            </div>
            {isDemo && (
              <div className="demo-controls">
                <button onClick={() => demoControl({ playing: true })}>Play</button>
                <button onClick={() => demoControl({ playing: false })}>Pause</button>
                <button onClick={() => demoControl({ reset: true })}>Reset</button>
                <button onClick={() => demoControl({ speed: 1 })}>1x</button>
                <button onClick={() => demoControl({ speed: 2 })}>2x</button>
                <button onClick={() => demoControl({ speed: 5 })}>5x</button>
              </div>
            )}
          </section>
        )}

        {tab === "live" && (
          <section>
            <div className="live-head">
              <div>
                <h1>Ao vivo</h1>
                <p className="muted">Grade escalável — até dezenas de alunos por câmera</p>
              </div>
              <a className="btn" href="/debug/vision" target="_blank" rel="noreferrer">
                Abrir visão técnica
              </a>
            </div>
            <div className="live-cam-row">
              <img
                className="live-mjpeg"
                src="/debug/mjpeg?camera_id=cam-web&overlay=1&fps=10"
                alt="Câmera ao vivo"
              />
            </div>
            <div className="student-grid">
              {tracks.length === 0 && <p className="muted">Aguardando detecções…</p>}
              {tracks.map((tr) => (
                <StudentCard key={tr.track_id || tr.person_track_id} track={tr} />
              ))}
            </div>
          </section>
        )}

        {tab === "students" && QA_QUERY && (
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

        {tab === "report" && <ReportPanel report={report} summary={summary} students={students} events={events} />}

        {tab === "review" && QA_QUERY && (
          <section>
            <div className="qa-banner panel">
              <strong>Aba técnica (QA)</strong>
              <p>
                Esta lista é jargão interno (`possible_phone_interaction`, `conf=0.55`). Para o professor, use{" "}
                <button type="button" className="linkish" onClick={() => setTab("report")}>
                  Respostas da aula
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
                  <button onClick={() => patchReview(e.event_id, "confirmed")}>Confirmar</button>
                  <button onClick={() => patchReview(e.event_id, "rejected")}>Rejeitar</button>
                  <button onClick={() => patchReview(e.event_id, "inconclusive")}>Inconclusivo</button>
                </div>
              </div>
            ))}
          </section>
        )}

        {tab === "system" && QA_QUERY && (
          <section>
            <h1>Sistema (QA)</h1>
            <pre>{JSON.stringify({ modules: status?.modules, performance: perf }, null, 2)}</pre>
          </section>
        )}
      </main>
    </div>
  );
}
