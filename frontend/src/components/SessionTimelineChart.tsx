import { fmtPct } from "../labels";

type Sample = {
  t?: number;
  t_minutes?: number;
  observable_pct?: number | null;
  apparent_climate?: string;
};

type Props = {
  timeline: Sample[];
  title?: string;
};

export function SessionTimelineChart({ timeline, title = "Observabilidade ao longo do tempo" }: Props) {
  if (!timeline.length) {
    return <p className="muted">Ainda coletando amostras (a cada ~15s)…</p>;
  }

  const maxT = Math.max(...timeline.map((s) => s.t ?? 0), 1);
  const maxMin = Math.ceil(maxT / 60);

  return (
    <div className="timeline-chart">
      <div className="timeline-chart-head">
        <span>{title}</span>
        <span className="muted">Eixo X: minutos · Eixo Y: % observável</span>
      </div>
      <div className="timeline-chart-body">
        <div className="timeline-y-axis">
          <span>100%</span>
          <span>50%</span>
          <span>0%</span>
        </div>
        <div className="timeline-plot">
          {timeline.map((s, i) => {
            const pct = Math.max(0, Math.min(100, Number(s.observable_pct) || 0));
            const left = maxT > 0 ? ((s.t ?? 0) / maxT) * 100 : (i / Math.max(timeline.length - 1, 1)) * 100;
            return (
              <div
                key={i}
                className="timeline-bar"
                style={{ left: `${left}%`, height: `${Math.max(6, pct)}%` }}
                title={`${((s.t ?? 0) / 60).toFixed(1)} min · ${fmtPct(pct)}`}
              />
            );
          })}
        </div>
      </div>
      <div className="timeline-x-axis">
        <span>0 min</span>
        <span>{Math.floor(maxMin / 2)} min</span>
        <span>{maxMin} min</span>
      </div>
    </div>
  );
}
