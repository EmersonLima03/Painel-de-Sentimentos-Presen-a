import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const DISCLAIMER =
  "Indicadores estimados a partir de sinais visuais. Não constituem diagnóstico, avaliação psicológica ou comprovação de aprendizagem.";

const DEMO_BANNER = "Modo demonstração — todos os indicadores apresentados nesta sessão são simulados.";

type Tab = "overview" | "live" | "timeline" | "students" | "review" | "report" | "system";

function apiHeaders(): HeadersInit {
  const token = localStorage.getItem("api_token") || "";
  return token ? { "X-API-Token": token } : {};
}

async function apiGet(path: string) {
  const r = await fetch(path, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function exprLabel(raw: string | undefined): string {
  switch (raw) {
    case "predominantly_positive":
    case "positive":
      return "expressão predominantemente positiva";
    case "predominantly_neutral":
    case "neutral":
      return "expressão predominantemente neutra";
    case "predominantly_negative":
    case "negative":
      return "expressão predominantemente negativa";
    case "mixed":
      return "expressão mista";
    default:
      return "inconclusivo";
  }
}

function Kpi({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value ?? "—"}</div>
    </div>
  );
}

export function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [status, setStatus] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [tracks, setTracks] = useState<any[]>([]);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [students, setStudents] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [report, setReport] = useState<any>(null);
  const [perf, setPerf] = useState<any>(null);
  const [err, setErr] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [wsState, setWsState] = useState<"connecting" | "connected" | "disconnected">("connecting");
  const [reviewFilter, setReviewFilter] = useState<string>("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const sessionId = status?.session?.session_id as string | undefined;
  const isDemo = Boolean(status?.is_simulated || status?.runtime_mode === "demo");
  const wsRef = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    try {
      setErr("");
      const st = await apiGet("/api/v1/live/status");
      setStatus(st);
      const sm = await apiGet("/api/v1/live/classroom-summary");
      setSummary(sm);
      const tr = await apiGet("/api/v1/live/tracks");
      setTracks(tr.tracks || []);
      if (st?.session?.session_id) {
        const sid = st.session.session_id;
        const [tl, stu, ev, rp, pf] = await Promise.all([
          apiGet(`/api/v1/sessions/${sid}/timeline`),
          apiGet(`/api/v1/sessions/${sid}/students`),
          apiGet(`/api/v1/sessions/${sid}/behavioral-events`),
          apiGet(`/api/v1/sessions/${sid}/summary`),
          apiGet("/api/v1/system/performance"),
        ]);
        setTimeline(tl.timeline || []);
        setStudents(stu.students || []);
        setEvents(ev.events || []);
        setReport(rp);
        setPerf(pf);
      }
      setLoading(false);
    } catch (e) {
      setErr(String(e));
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    let closed = false;
    let retry = 0;
    const connect = () => {
      if (closed) return;
      setWsState("connecting");
      const token = localStorage.getItem("api_token") || "";
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const q = token ? `?api_token=${encodeURIComponent(token)}` : "";
      const ws = new WebSocket(`${proto}://${location.host}/api/v1/ws/live${q}`);
      wsRef.current = ws;
      ws.onopen = () => {
        setWsState("connected");
        retry = 0;
      };
      ws.onclose = () => {
        setWsState("disconnected");
        const delay = Math.min(10000, 1000 * Math.pow(2, retry++));
        setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = () => {
        /* payloads compactos — refresh periódico já atualiza UI */
      };
    };
    connect();
    return () => {
      closed = true;
      wsRef.current?.close();
    };
  }, []);

  const demoControl = async (body: Record<string, unknown>) => {
    await fetch("/api/v1/demo/control", {
      method: "POST",
      headers: { ...apiHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    await refresh();
  };

  const patchReview = async (eventId: string, statusValue: string) => {
    await fetch(`/api/v1/review/events/${eventId}`, {
      method: "PATCH",
      headers: { ...apiHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ status: statusValue, notes: notes[eventId] || "" }),
    });
    await refresh();
  };

  const filteredEvents = useMemo(() => {
    if (!reviewFilter) return events;
    return events.filter((e) => e.review_status === reviewFilter);
  }, [events, reviewFilter]);

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Visão geral" },
    { id: "live", label: "Ao vivo" },
    { id: "timeline", label: "Linha do tempo" },
    { id: "students", label: "Estudantes" },
    { id: "review", label: "Eventos e revisão" },
    { id: "report", label: "Relatório da aula" },
    { id: "system", label: "Sistema" },
  ];

  const k = summary || status?.kpis || {};

  return (
    <div className="app">
      {isDemo && <div className="demo-banner">{DEMO_BANNER}</div>}
      <header className="top">
        <div>
          <strong className="brand">Presença</strong>
          <span className="muted"> · dashboard educacional</span>
        </div>
        <p className="disclaimer">{DISCLAIMER}</p>
        <div className="meta">
          <span>WS: {wsState}</span>
          <span>modo: {status?.runtime_mode || "…"}</span>
          {sessionId && <span>sessão: {sessionId.slice(0, 8)}…</span>}
        </div>
      </header>
      <nav className="tabs">
        {tabs.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main>
        {loading && <p className="muted">Carregando…</p>}
        {err && <p className="error">Erro: {err}</p>}
        {!loading && !err && !status && <p className="muted">Sem dados.</p>}

        {tab === "overview" && (
          <section>
            <h1>Visão geral</h1>
            <div className="kpi-grid">
              <Kpi label="Presentes" value={k.recognized_people ?? k.present ?? "—"} />
              <Kpi label="Visíveis" value={k.visible_people ?? k.visible ?? "—"} />
              <Kpi
                label="Observáveis"
                value={
                  k.observable_people === null || k.observable_people === undefined
                    ? "sem dado"
                    : k.observable_people
                }
              />
              <Kpi
                label="Inconclusivos"
                value={
                  k.inconclusive_people === null || k.inconclusive_people === undefined
                    ? "sem dado"
                    : k.inconclusive_people
                }
              />
              <Kpi
                label="Atenção visual estimada"
                value={
                  k.attention_index === null || k.attention_index === undefined
                    ? "sem dado"
                    : k.attention_index
                }
              />
              <Kpi
                label="Clima visual aparente"
                value={
                  k.apparent_climate || k.climate
                    ? exprLabel(k.apparent_climate ?? k.climate)
                    : "sem dado"
                }
              />
              <Kpi
                label="Eventos ativos"
                value={
                  k.active_behavioral_signals === null || k.active_behavioral_signals === undefined
                    ? k.active_events ?? "sem dado"
                    : k.active_behavioral_signals
                }
              />
              <Kpi label="Câmera" value={k.camera_status || status?.camera_status || "—"} />
              <Kpi label="LXP" value={status?.kpis?.lxp_status || status?.modules?.lxp || "—"} />
            </div>
            {isDemo && (
              <div className="demo-controls">
                <button onClick={() => demoControl({ playing: true })}>Play</button>
                <button onClick={() => demoControl({ playing: false })}>Pause</button>
                <button onClick={() => demoControl({ reset: true })}>Reset</button>
                <button onClick={() => demoControl({ speed: 1 })}>1x</button>
                <button onClick={() => demoControl({ speed: 2 })}>2x</button>
                <button onClick={() => demoControl({ speed: 5 })}>5x</button>
                <span className="muted">
                  t={status?.session?.t_seconds ?? 0}s / {status?.session?.duration_target ?? 900}s
                </span>
              </div>
            )}
          </section>
        )}

        {tab === "live" && (
          <section className="live-layout">
            <div>
              <h1>Ao vivo</h1>
              <p className="muted">Sem rótulos de emoção sobre cada rosto. Overlay técnico apenas.</p>
              <div className="stage">
                {tracks.length === 0 && <p className="muted">Aguardando tracks…</p>}
                {tracks.map((tr) => (
                  <div
                    key={tr.track_id}
                    className="avatar"
                    style={{
                      left: `${(tr.bbox?.[0] || 0) / 10}%`,
                      top: `${(tr.bbox?.[1] || 0) / 6}%`,
                    }}
                    title={tr.full_name}
                  >
                    <span>{(tr.full_name || "?").split(" ")[0]}</span>
                    <small>{tr.attention_state}</small>
                  </div>
                ))}
              </div>
            </div>
            <aside>
              <h2>Painel</h2>
              <ul className="side-list">
                {tracks.map((tr) => (
                  <li key={tr.track_id}>
                    <strong>{tr.full_name}</strong>
                    <div>atenção: {tr.attention_state}</div>
                    <div>{exprLabel(tr.expression_window)}</div>
                    <div>qualidade: {tr.observation_quality}</div>
                    {tr.phone?.level !== "none" && <div>celular: {tr.phone.label}</div>}
                  </li>
                ))}
              </ul>
            </aside>
          </section>
        )}

        {tab === "timeline" && (
          <section>
            <h1>Linha do tempo</h1>
            {timeline.length === 0 && <p className="muted">Vazia.</p>}
            <ol className="timeline">
              {timeline.map((item, i) => (
                <li key={i}>
                  <span className="t">t={Math.round(item.t)}s</span> {item.label || item.type}{" "}
                  <span className="muted">{item.student_id}</span>
                </li>
              ))}
            </ol>
          </section>
        )}

        {tab === "students" && (
          <section>
            <h1>Estudantes</h1>
            <p className="muted">Sem ranking melhor/pior.</p>
            <table>
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Presente</th>
                  <th>Track</th>
                </tr>
              </thead>
              <tbody>
                {students.map((s) => (
                  <tr key={s.student_id}>
                    <td>{s.full_name}</td>
                    <td>{s.present ? "sim" : "não"}</td>
                    <td>{s.track_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {tab === "review" && (
          <section>
            <h1>Eventos e revisão</h1>
            <div className="filters">
              <label>
                Status{" "}
                <select value={reviewFilter} onChange={(e) => setReviewFilter(e.target.value)}>
                  <option value="">todos</option>
                  <option value="pending">pending</option>
                  <option value="confirmed">confirmed</option>
                  <option value="rejected">rejected</option>
                  <option value="inconclusive">inconclusive</option>
                </select>
              </label>
            </div>
            {filteredEvents.length === 0 && <p className="muted">Nenhum evento.</p>}
            {filteredEvents.map((e) => (
              <div className="event" key={e.event_id}>
                <div>
                  <strong>{e.event_type}</strong> · {e.student_id} · conf={e.confidence} · q={e.observation_quality}
                </div>
                <div className="muted">sinais: {(e.reasons || []).join(", ")}</div>
                <div>review: {e.review_status}</div>
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

        {tab === "report" && (
          <section>
            <h1>Relatório da aula</h1>
            <pre>{JSON.stringify(report, null, 2)}</pre>
            <div className="row">
              <a className="btn" href="/api/v1/demo/report.csv">
                Export CSV
              </a>
              <a className="btn" href="/api/v1/demo/report">
                Export JSON
              </a>
            </div>
            {report?.limitations && (
              <ul>
                {report.limitations.map((l: string, i: number) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            )}
          </section>
        )}

        {tab === "system" && (
          <section>
            <h1>Sistema</h1>
            <pre>{JSON.stringify({ modules: status?.modules, performance: perf, provenance: report?.provenance }, null, 2)}</pre>
          </section>
        )}
      </main>
    </div>
  );
}
