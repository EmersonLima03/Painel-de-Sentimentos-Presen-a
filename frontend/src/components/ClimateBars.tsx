import { exprLabel } from "../labels";

type Props = {
  distribution: Record<string, number>;
  dominant?: string;
  pedagogical?: boolean;
};

const ORDER = [
  "predominantly_positive",
  "positive",
  "predominantly_neutral",
  "neutral",
  "mixed",
  "predominantly_negative",
  "negative",
  "surprise",
];

function shortBucket(key: string): string {
  if (key.includes("positive") || key === "positive") return "Positiva";
  if (key.includes("negative") || key === "negative") return "Negativa";
  if (key.includes("neutral") || key === "neutral" || key === "mixed" || key === "surprise") {
    return "Neutra";
  }
  return exprLabel(key);
}

export function ClimateBars({ distribution, dominant, pedagogical }: Props) {
  const entries = Object.entries(distribution || {}).filter(([, v]) => v > 0);
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1;

  if (pedagogical) {
    const buckets: Record<string, number> = { Positiva: 0, Neutra: 0, Negativa: 0 };
    for (const [key, count] of entries) {
      buckets[shortBucket(key)] = (buckets[shortBucket(key)] || 0) + count;
    }
    const rows = (["Positiva", "Neutra", "Negativa"] as const).filter((k) => buckets[k] > 0);
    if (!rows.length) {
      return (
        <div className="climate-empty">
          <p className="muted">
            Sem expressões aparentes conclusivas no momento — aguardando leituras válidas.
          </p>
        </div>
      );
    }
    return (
      <div className="climate-bars climate-bars-ped">
        {rows.map((label) => {
          const count = buckets[label];
          const pct = Math.round((100 * count) / total);
          return (
            <div className="climate-row" key={label}>
              <span className="climate-label">{label}</span>
              <div className="climate-track">
                <div className="climate-fill" style={{ width: `${(100 * count) / total}%` }} />
              </div>
              <span className="climate-count">
                {pct}% <span className="muted">({count})</span>
              </span>
            </div>
          );
        })}
        <p className="climate-note muted">
          Distribuição estimada entre alunos com leitura válida. Não interpreta estado emocional ou
          psicológico.
        </p>
      </div>
    );
  }

  const sorted = [...entries].sort(
    (a, b) =>
      (ORDER.indexOf(a[0]) === -1 ? 99 : ORDER.indexOf(a[0])) -
      (ORDER.indexOf(b[0]) === -1 ? 99 : ORDER.indexOf(b[0]))
  );

  if (!sorted.length) {
    return (
      <div className="climate-empty">
        <p className="muted">Sem expressões conclusivas no momento — aguardando observação adequada.</p>
      </div>
    );
  }

  return (
    <div className="climate-bars">
      {dominant && (
        <p className="climate-dominant">
          Predominante agora: <strong>{exprLabel(dominant)}</strong>
        </p>
      )}
      {sorted.map(([key, count]) => (
        <div className="climate-row" key={key}>
          <span className="climate-label">{exprLabel(key)}</span>
          <div className="climate-track">
            <div className="climate-fill" style={{ width: `${(100 * count) / total}%` }} />
          </div>
          <span className="climate-count">{count}</span>
        </div>
      ))}
      <p className="climate-note muted">Baseado em rostos observáveis — inconclusivos não entram na barra.</p>
    </div>
  );
}
