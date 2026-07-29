type Props = {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "default" | "primary" | "warn" | "good";
  unavailable?: boolean;
};

export function MetricCard({ label, value, sub, tone = "default", unavailable }: Props) {
  if (unavailable) {
    return (
      <div className="metric-card unavailable" aria-label={`${label}: ainda não disponível`}>
        <div className="metric-label">{label}</div>
        <div className="metric-value muted">—</div>
        <div className="metric-sub">Ainda não disponível</div>
      </div>
    );
  }
  return (
    <div className={`metric-card ${tone}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {sub != null && <div className="metric-sub">{sub}</div>}
    </div>
  );
}
