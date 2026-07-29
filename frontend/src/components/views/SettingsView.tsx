import { useState } from "react";
import { PageHeader } from "../layout/PageHeader";
import { Disclaimer } from "../ui/Disclaimer";
import { SectionHeader } from "../ui/SectionHeader";

type Props = {
  status: any;
  qaEnabled: boolean;
};

export function SettingsView({ status, qaEnabled }: Props) {
  const [token, setToken] = useState(() => localStorage.getItem("api_token") || "");
  const [saved, setSaved] = useState(false);

  const save = () => {
    localStorage.setItem("api_token", token.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <section className="settings-view">
      <PageHeader title="Configurações" subtitle="Preferências locais deste navegador" />

      <div className="panel">
        <SectionHeader title="Aviso ético" />
        <Disclaimer />
      </div>

      <div className="panel">
        <SectionHeader title="Token da API" subtitle="Armazenado apenas neste navegador (localStorage)" />
        <label className="settings-field">
          <span>X-API-Token</span>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Opcional"
            autoComplete="off"
          />
        </label>
        <button type="button" className="btn primary" onClick={save}>
          Salvar token
        </button>
        {saved && <span className="muted"> Salvo.</span>}
      </div>

      <div className="panel">
        <SectionHeader title="Sessão / runtime" />
        <p>
          Modo: <strong>{status?.runtime_mode || "—"}</strong>
        </p>
        <p className="muted">
          Controles de demonstração aparecem na tela Ao vivo quando o runtime é demo.
        </p>
      </div>

      <div className="panel">
        <SectionHeader title="Links" />
        <ul className="settings-links">
          <li>
            <a href="/dashboard-legacy">Painel legado (operacional)</a>
          </li>
          <li>
            <a href="/debug/vision" target="_blank" rel="noreferrer">
              Visão técnica (/debug/vision)
            </a>
            <span className="muted"> — ambiente separado do dashboard educacional</span>
          </li>
          <li>
            {qaEnabled ? (
              <span>Modo QA ativo (?qa=1) — abas internas na barra lateral</span>
            ) : (
              <a href="?qa=1">Ativar ferramentas internas (?qa=1)</a>
            )}
          </li>
        </ul>
      </div>
    </section>
  );
}
