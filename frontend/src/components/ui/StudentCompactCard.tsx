import { useState } from "react";
import { attnLabel, eventTypePt, exprLabel, fmtPct, qualityLabel } from "../../labels";

export type StudentVisualStatus =
  | "present"
  | "adequate"
  | "inconclusive"
  | "not_visible"
  | "for_review"
  | "identity_uncertain";

export function deriveStudentStatus(track: any): StudentVisualStatus {
  const alerts = track.active_events || track.alert_events || [];
  if (track.alert_type || (Array.isArray(alerts) && alerts.length > 0)) return "for_review";
  const idSt = String(track.identity_state || "").toLowerCase();
  if (idSt === "uncertain" || idSt === "unknown") return "identity_uncertain";
  const q = track.observation_quality || track.last_quality;
  const qStatus = typeof q === "object" ? q?.status : q;
  if (qStatus === "not_visible" || track.present === false) return "not_visible";
  if (qStatus === "inconclusive" || qStatus === "low_quality" || qStatus === "partially_observable") {
    return "inconclusive";
  }
  if (qStatus === "observable" || track.present !== false) {
    if (track.student_id || track.full_name) return "adequate";
    return "present";
  }
  return "present";
}

const STATUS_PT: Record<StudentVisualStatus, string> = {
  present: "Presente",
  adequate: "Imagem adequada",
  inconclusive: "Inconclusivo",
  not_visible: "Não visível",
  for_review: "Para revisão",
  identity_uncertain: "Identidade incerta",
};

const STATUS_CLASS: Record<StudentVisualStatus, string> = {
  present: "good",
  adequate: "good",
  inconclusive: "warn",
  not_visible: "muted",
  for_review: "warn",
  identity_uncertain: "mid",
};

function shortExprLabel(raw: string | undefined): string {
  const full = exprLabel(raw);
  if (!raw || raw === "inconclusive") return "inconclusiva";
  if (raw.includes("positive") || raw === "positive") return "positiva";
  if (raw.includes("neutral") || raw === "neutral") return "neutra";
  if (raw.includes("negative") || raw === "negative") return "negativa";
  if (raw === "surprise" || raw === "mixed") return full.replace(/^Expressão (de |aparente )?/, "").toLowerCase() || "mista";
  return full.toLowerCase();
}

function qualityReasonPt(qStatus: string | undefined, track: any): string | null {
  if (track.expression_reason) return String(track.expression_reason);
  switch (qStatus) {
    case "partially_observable":
      return "rosto parcialmente observável";
    case "low_quality":
      return "qualidade de imagem insuficiente";
    case "inconclusive":
      return "observação inconclusiva";
    case "not_visible":
      return "rosto não visível";
    default:
      return null;
  }
}

export function StudentStatusBadge({ status }: { status: StudentVisualStatus }) {
  return (
    <span className={`status-badge ${STATUS_CLASS[status]}`}>
      {STATUS_PT[status]}
    </span>
  );
}

type CardProps = {
  track: any;
  compact?: boolean;
};

export function StudentCompactCard({ track, compact }: CardProps) {
  const [open, setOpen] = useState(false);
  const name = track.full_name || track.student_id || "Pessoa";
  const status = deriveStudentStatus(track);
  const alert = track.alert_type || (track.alert_events || [])[0];
  const q = track.observation_quality || track.last_quality;
  const qStatus = typeof q === "object" ? q?.status : q;
  const expr = track.expression_window || track.dominant_expression;
  const exprShort = shortExprLabel(expr);
  const inconclusiveExpr = !expr || expr === "inconclusive";
  const reason = inconclusiveExpr ? qualityReasonPt(String(qStatus || ""), track) : null;
  const initials = String(name)
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p: string) => p[0]?.toUpperCase() || "")
    .join("");

  const conf = track.expression_confidence;
  const samples = track.expression_sample_count;
  const obsScore = track.observation_score;
  const attn = track.attention_state || track.dominant_attention;

  return (
    <article
      className={`student-compact ${compact ? "compact" : ""} ${status === "for_review" ? "has-alert" : ""} ${open ? "expanded" : ""}`}
    >
      <button
        type="button"
        className="sc-main-btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${open ? "Recolher" : "Expandir"} detalhes de ${name}`}
      >
        <div className="sc-avatar" aria-hidden>
          {initials || "?"}
        </div>
        <div className="sc-body">
          <div className="sc-head">
            <strong className="sc-name">{name}</strong>
            <StudentStatusBadge status={status} />
          </div>
          <div className="sc-meta muted">
            {track.student_id ? "Presente" : "Detectado"}
            {qStatus ? ` · ${qualityLabel(String(qStatus))}` : ""}
          </div>
          <div className="sc-expr-line">
            {inconclusiveExpr ? (
              <>
                Expressão: inconclusiva
                {reason ? <span className="muted"> · Motivo: {reason}</span> : null}
              </>
            ) : (
              <>Expressão aparente: {exprShort}</>
            )}
          </div>
          {alert && (
            <div className="sc-alert-line" title={eventTypePt(typeof alert === "string" ? alert : alert?.event_type)}>
              {eventTypePt(typeof alert === "string" ? alert : alert?.event_type)}
            </div>
          )}
        </div>
        <span className="sc-chevron muted" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="sc-detail">
          <p>
            <span className="muted">Atenção visual estimada:</span> {attnLabel(attn)}
          </p>
          <p>
            <span className="muted">Expressão aparente:</span>{" "}
            {inconclusiveExpr ? "inconclusiva" : exprLabel(expr)}
          </p>
          <p>
            <span className="muted">Confiança:</span>{" "}
            {conf != null && Number(conf) > 0 ? fmtPct(Number(conf) <= 1 ? Number(conf) * 100 : Number(conf)) : "—"}
          </p>
          <p>
            <span className="muted">Amostras:</span> {samples != null ? samples : "—"}
          </p>
          <p>
            <span className="muted">Observabilidade:</span>{" "}
            {obsScore != null
              ? fmtPct(Number(obsScore) <= 1 ? Number(obsScore) * 100 : Number(obsScore))
              : qStatus
                ? qualityLabel(String(qStatus))
                : "—"}
          </p>
          {inconclusiveExpr && reason && (
            <p className="muted">Motivo: {reason}</p>
          )}
          <p className="muted sc-detail-hint">Estimativa visual — não é diagnóstico.</p>
        </div>
      )}
    </article>
  );
}
