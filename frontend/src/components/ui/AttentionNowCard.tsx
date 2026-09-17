import { eventTypePt, fmtDur } from "../../labels";

type Props = {
  item: any;
  onFocusStudent?: (studentKey: string) => void;
};

export function AttentionNowCard({ item, onFocusStudent }: Props) {
  const name =
    item.full_name ||
    item.student_id ||
    item.person_track_id ||
    "Pessoa";
  const typeLabel = eventTypePt(item.event_type || item.alert_type);
  const dur = item.duration_seconds;
  const key = String(item.student_id || item.person_track_id || "");

  return (
    <article className="attention-now-card">
      <div className="anc-head">
        <strong className="anc-name">{name}</strong>
        <span className="anc-dur">{fmtDur(dur)}</span>
      </div>
      <p className="anc-signal">{typeLabel}</p>
      {onFocusStudent && key && (
        <button type="button" className="btn ghost anc-btn" onClick={() => onFocusStudent(key)}>
          Ver aluno
        </button>
      )}
    </article>
  );
}
