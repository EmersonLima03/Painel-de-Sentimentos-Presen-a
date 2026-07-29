import { attnClass, attnLabel, exprClass, exprLabel, eventTypePt, qualityLabel } from "../labels";

type Props = {
  track: any;
  compact?: boolean;
};

export function StudentCard({ track, compact }: Props) {
  const name = track.full_name || track.student_id || "Pessoa";
  const attn = track.attention_state || track.dominant_attention;
  const expr = track.expression_window || track.dominant_expression;
  const exprPt = track.expression_display_pt;
  const quality = track.observation_quality || track.last_quality;
  const alert = track.alert_type || (track.alert_events || [])[0];

  return (
    <article className={`student-card ${compact ? "compact" : ""} ${alert ? "has-alert" : ""}`}>
      <header className="sc-head">
        <strong className="sc-name">{name}</strong>
        {alert && <span className="sc-alert">{eventTypePt(alert)}</span>}
      </header>
      <div className="sc-chips">
        <span className={`chip ${attnClass(attn)}`}>Atenção: {attnLabel(attn)}</span>
        <span className={`chip ${exprClass(expr)}`}>
          {exprPt || exprLabel(expr)}
        </span>
        {!compact && <span className="chip muted">Qualidade: {qualityLabel(quality)}</span>}
      </div>
      {!compact && track.observable_pct != null && (
        <div className="sc-foot muted">Observável ~{Math.round(track.observable_pct)}% da sessão</div>
      )}
    </article>
  );
}
