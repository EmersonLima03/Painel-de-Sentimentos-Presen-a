import { useState } from "react";
import {
  attnStatePt,
  eventTypePt,
  exprLabel,
  fmtDur,
  phoneStatePt,
  qualityReadingPt,
} from "../../labels";
import { trackHasAttentionNow } from "../../utils/events";

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
  adequate: "Presente",
  inconclusive: "Leitura inconclusiva",
  not_visible: "Não localizado",
  for_review: "Atenção",
  identity_uncertain: "Identidade em confirmação",
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
  if (!raw || raw === "inconclusive") return "inconclusiva";
  if (raw.includes("positive") || raw === "positive") return "positiva";
  if (raw.includes("neutral") || raw === "neutral") return "neutra";
  if (raw.includes("negative") || raw === "negative") return "negativa";
  return "aparente";
}

function phoneRaw(track: any): string | undefined {
  const p = track.phone;
  if (!p) return undefined;
  if (typeof p === "string") return p;
  return p.state || p.label;
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
  highlight?: boolean;
};

export function StudentCompactCard({ track, compact, highlight }: CardProps) {
  const [open, setOpen] = useState(false);
  const name = track.full_name || track.student_id || "Pessoa";
  const status = deriveStudentStatus(track);
  const hasAttention = trackHasAttentionNow(track);
  const q = track.observation_quality || track.last_quality;
  const qStatus = typeof q === "object" ? q?.status : q;
  const expr = track.expression_window || track.dominant_expression || track.expression_display_pt;
  const exprKey =
    typeof expr === "string" && expr.includes(" ")
      ? track.expression_window || track.dominant_expression
      : expr;
  const attn = track.attention_state || track.dominant_attention;
  const phone = phoneRaw(track);
  const active = (track.active_events || track.alert_events || []) as any[];
  const initials = String(name)
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p: string) => p[0]?.toUpperCase() || "")
    .join("");

  return (
    <article
      className={`student-compact ${compact ? "compact" : ""} ${hasAttention ? "has-alert" : ""} ${open ? "expanded" : ""} ${highlight ? "sc-highlight" : ""}`}
      id={`student-${track.student_id || track.person_track_id || track.track_id || ""}`}
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
          {!hasAttention && (
            <>
              <div className="sc-line">{attnStatePt(attn)}</div>
              <div className="sc-line muted">
                Expressão aparente: {shortExprLabel(String(exprKey || ""))}
              </div>
              <div className="sc-line muted">{phoneStatePt(phone)}</div>
              <div className="sc-line muted">{qualityReadingPt(String(qStatus || ""))}</div>
            </>
          )}
          {hasAttention &&
            (active.length > 0 ? (
              active.slice(0, 3).map((ev, i) => (
                <div className="sc-alert-line" key={ev.event_id || i}>
                  <span className="sc-alert-kind">{eventTypePt(ev.event_type)}</span>
                  {ev.duration_seconds != null && (
                    <span className="sc-alert-dur"> · {fmtDur(ev.duration_seconds)}</span>
                  )}
                </div>
              ))
            ) : (
              <div className="sc-alert-line">{eventTypePt(track.alert_type)}</div>
            ))}
        </div>
        <span className="sc-chevron muted" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="sc-detail">
          <p>
            <span className="muted">Situação:</span> {STATUS_PT[status]}
          </p>
          <p>{attnStatePt(attn)}</p>
          <p>
            <span className="muted">Expressão aparente:</span>{" "}
            {exprLabel(String(exprKey || ""))}
          </p>
          <p>{phoneStatePt(phone)}</p>
          <p>{qualityReadingPt(String(qStatus || ""))}</p>
          <p className="muted sc-detail-hint">
            Sinais estimados a partir de imagem — não são diagnóstico nem avaliação de aprendizagem.
          </p>
        </div>
      )}
    </article>
  );
}
