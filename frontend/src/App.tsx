import { useEffect, useState } from "react";

const DISCLAIMER =
  "Indicadores estimados a partir de sinais visuais. Não constituem diagnóstico, avaliação psicológica ou comprovação de aprendizagem.";

type Tab = "overview" | "live" | "timeline" | "students" | "review" | "report" | "system";

export function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [status, setStatus] = useState<any>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    const token = localStorage.getItem("api_token") || "";
    fetch("/api/v1/live/status", {
      headers: token ? { "X-API-Token": token } : {},
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setStatus)
      .catch((e) => setErr(String(e)));
  }, []);

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Visão geral" },
    { id: "live", label: "Ao vivo" },
    { id: "timeline", label: "Linha do tempo" },
    { id: "students", label: "Estudantes" },
    { id: "review", label: "Eventos e revisão" },
    { id: "report", label: "Relatório" },
    { id: "system", label: "Sistema" },
  ];

  return (
    <div className="app">
      <header className="top">
        <div>
          <strong>Presença</strong>
          <span className="muted"> · dashboard educacional</span>
        </div>
        <p className="disclaimer">{DISCLAIMER}</p>
      </header>
      <nav className="tabs">
        {tabs.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main>
        {err && <p className="error">Falha ao carregar status: {err}</p>}
        {tab === "overview" && (
          <section>
            <h1>Visão geral</h1>
            <p className="muted">Atenção visual estimada · clima aparente · cobertura (após calibração).</p>
            <pre>{JSON.stringify(status, null, 2)}</pre>
          </section>
        )}
        {tab === "live" && (
          <section>
            <h1>Ao vivo</h1>
            <p>Sem rótulos de emoção por rosto. Preview via stream existente do edge.</p>
            <img src="/debug/mjpeg" alt="live" className="live" />
          </section>
        )}
        {tab === "system" && (
          <section>
            <h1>Sistema</h1>
            <pre>{JSON.stringify(status?.modules, null, 2)}</pre>
          </section>
        )}
        {!["overview", "live", "system"].includes(tab) && (
          <section>
            <h1>{tabs.find((t) => t.id === tab)?.label}</h1>
            <p className="muted">Conteúdo alimentado após módulos em shadow/production calibrados.</p>
          </section>
        )}
      </main>
    </div>
  );
}
