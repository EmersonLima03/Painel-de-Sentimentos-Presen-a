import { useState } from "react";
import { PageHeader } from "../layout/PageHeader";
import { Disclaimer } from "../ui/Disclaimer";
import { SectionHeader } from "../ui/SectionHeader";
import { loadAulaMeta, saveAulaMeta, type AulaMeta } from "../../utils/aulaMeta";
import { CloudAuthPanel } from "../../cloud/CloudAuthPanel";

type Props = {
  status: any;
  qaEnabled: boolean;
};

export function SettingsView({ status, qaEnabled }: Props) {
  const [token, setToken] = useState(() => localStorage.getItem("api_token") || "");
  const [saved, setSaved] = useState(false);
  const [aula, setAula] = useState<AulaMeta>(() => loadAulaMeta());
  const [aulaSaved, setAulaSaved] = useState(false);
  const [durationMode, setDurationMode] = useState<"50" | "100" | "custom">(() => {
    const m = loadAulaMeta().durationMinutes;
    if (m === 50) return "50";
    if (m === 100) return "100";
    return "custom";
  });

  const save = () => {
    localStorage.setItem("api_token", token.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const saveAula = () => {
    const minutes =
      durationMode === "50" ? 50 : durationMode === "100" ? 100 : aula.durationMinutes || 50;
    const next = { ...aula, durationMinutes: minutes };
    saveAulaMeta(next);
    setAula(next);
    window.dispatchEvent(new Event("presenca-aula-meta"));
    setAulaSaved(true);
    setTimeout(() => setAulaSaved(false), 2000);
  };

  return (
    <section className="settings-view">
      <PageHeader title="Configurações" subtitle="Preferências locais deste navegador" />

      <div className="panel">
        <SectionHeader
          title="Conta Sentimentos (cloud)"
          subtitle="Login com JWT — nunca service_role no browser"
        />
        <CloudAuthPanel />
      </div>

      <div className="panel">
        <SectionHeader title="Aviso ético" />
        <Disclaimer />
      </div>

      <div className="panel">
        <SectionHeader
          title="Contexto da aula (local)"
          subtitle="Temporário até integração LXP — não altera o pipeline de visão"
        />
        <label className="settings-field">
          <span>Turma</span>
          <input
            type="text"
            value={aula.turma}
            onChange={(e) => setAula({ ...aula, turma: e.target.value })}
            placeholder="Ex.: 8º Ano B"
            autoComplete="off"
          />
        </label>
        <label className="settings-field">
          <span>Disciplina</span>
          <input
            type="text"
            value={aula.disciplina}
            onChange={(e) => setAula({ ...aula, disciplina: e.target.value })}
            placeholder="Ex.: Matemática"
            autoComplete="off"
          />
        </label>
        <label className="settings-field">
          <span>Aula externa (LXP / simulador)</span>
          <input
            type="text"
            value={aula.externalLessonId}
            onChange={(e) => setAula({ ...aula, externalLessonId: e.target.value })}
            placeholder="Ex.: lesson-8b-math-50 (vazio = não configurada)"
            autoComplete="off"
          />
        </label>
        <label className="settings-field">
          <span>Professor</span>
          <input
            type="text"
            value={aula.professor}
            onChange={(e) => setAula({ ...aula, professor: e.target.value })}
            placeholder="Ex.: Marcos Silva"
            autoComplete="off"
          />
        </label>
        <fieldset className="settings-fieldset">
          <legend>Duração prevista</legend>
          <label className="settings-radio">
            <input
              type="radio"
              name="dur"
              checked={durationMode === "50"}
              onChange={() => setDurationMode("50")}
            />
            50 min
          </label>
          <label className="settings-radio">
            <input
              type="radio"
              name="dur"
              checked={durationMode === "100"}
              onChange={() => setDurationMode("100")}
            />
            100 min (duas aulas)
          </label>
          <label className="settings-radio">
            <input
              type="radio"
              name="dur"
              checked={durationMode === "custom"}
              onChange={() => setDurationMode("custom")}
            />
            Personalizada
          </label>
          {durationMode === "custom" && (
            <label className="settings-field">
              <span>Minutos</span>
              <input
                type="number"
                min={1}
                max={300}
                value={aula.durationMinutes ?? 50}
                onChange={(e) =>
                  setAula({ ...aula, durationMinutes: Math.max(1, Number(e.target.value) || 50) })
                }
              />
            </label>
          )}
        </fieldset>
        <button type="button" className="btn primary" onClick={saveAula}>
          Salvar contexto da aula
        </button>
        {aulaSaved && <span className="muted"> Salvo.</span>}
        <p className="muted settings-note">
          Horário agendado vs início efetivo e “atraso” automático ficam para a integração LXP (Fase
          3). Aqui só há rótulos locais para o cabeçalho.
        </p>
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
        <SectionHeader title="Links técnicos" subtitle="Separados do acompanhamento pedagógico" />
        <ul className="settings-links">
          <li>
            <a href="/dashboard-legacy">Painel legado (operacional)</a>
          </li>
          <li>
            <a href="/debug/vision" target="_blank" rel="noreferrer">
              Visão técnica (/debug/vision)
            </a>
            <span className="muted"> — validação TRI; não é tela de professor</span>
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
