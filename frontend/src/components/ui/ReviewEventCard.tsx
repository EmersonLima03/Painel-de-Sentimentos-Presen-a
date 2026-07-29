import { eventTypePt, fmtDur } from "../../labels";

type Props = {
  event: any;
  onDetail?: (ev: any) => void;
};

export function ReviewEventCard({ event, onDetail }: Props) {
  const name =
    event.full_name ||
    event.student_id ||
    event.candidate_student_id ||
    event.person_track_id ||
    "Pessoa";
  const typeLabel = eventTypePt(event.event_type || event.alert_type);
  const dur = event.duration_seconds;
  const attr = event.attribution_status || event.review_status || event.status || "pendente";

  return (
    <article className="review-event-card">
      <div className="rec-head">
        <strong>{typeLabel}</strong>
        <span className="muted">{fmtDur(dur)}</span>
      </div>
      <div className="rec-body">
        <span>{name}</span>
        <span className="muted"> · {attr}</span>
      </div>
      {onDetail && (
        <button type="button" className="btn ghost" onClick={() => onDetail(event)}>
          Ver detalhes
        </button>
      )}
    </article>
  );
}
