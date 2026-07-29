import { exprLabel } from "../labels";

type Props = {
  distribution: Record<string, number>;
  dominant?: string;
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

export function ClimateBars({ distribution, dominant }: Props) {
  const entries = Object.entries(distribution || {}).filter(([, v]) => v > 0);
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1;
  const sorted = [...entries].sort(
    (a, b) => (ORDER.indexOf(a[0]) === -1 ? 99 : ORDER.indexOf(a[0])) - (ORDER.indexOf(b[0]) === -1 ? 99 : ORDER.indexOf(b[0]))
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
