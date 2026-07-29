import { fmtDur, fmtPct } from "../labels";

type Props = {
  k: any;
  obsPct: number | null;
  elapsed?: number;
};

export function OverviewHero({ k, obsPct, elapsed }: Props) {
  const visible = k.visible_people ?? k.visible ?? "—";
  const present = k.recognized_people ?? k.present ?? "—";
  const attnLabel = k.attention_label_pt;
  const climateLabel = k.climate_label_pt;
  const classSummary = k.class_summary || {};

  const activeSignals: { label_pt: string; severity?: string }[] =
    classSummary.active_signals_summary || [];

  return (
    <div className="hero-grid">
      <div className="hero-card primary">
        <div className="hero-label">Pessoas visíveis</div>
        <div className="hero-value">{visible}</div>
        <div className="hero-sub">{present} identificadas</div>
      </div>
      <div className="hero-card">
        <div className="hero-label">Observáveis agora</div>
        <div className="hero-value">{obsPct != null ? fmtPct(obsPct) : "—"}</div>
        <div className="hero-sub">
          {k.observable_people ?? k.observable ?? 0} de {visible} com qualidade adequada
        </div>
      </div>
      <div className="hero-card">
        <div className="hero-label">Atenção da turma</div>
        <div className="hero-value hero-value-text">{attnLabel || "Sem dado suficiente"}</div>
        <div className="hero-sub">{climateLabel || "Clima aparente indisponível"}</div>
      </div>
      <div className="hero-card">
        <div className="hero-label">Sessão</div>
        <div className="hero-value">{elapsed != null ? fmtDur(elapsed) : "—"}</div>
        <div className="hero-sub">
          {activeSignals.length > 0
            ? activeSignals.map((a) => a.label_pt).join(" · ")
            : "Nenhum alerta persistente no momento"}
        </div>
      </div>
    </div>
  );
}
