import { fmtDur } from "../labels";

type Category = {
  category_id: string;
  label_pt: string;
  total_seconds: number;
  occurrence_count?: number;
  disclaimer_pt?: string;
};

type Signal = {
  signal_key: string;
  label_pt: string;
  total_seconds: number;
  occurrence_count: number;
  disclaimer_pt: string;
};

type Student = {
  person_key?: string;
  student_id?: string;
  full_name?: string;
  presence_seconds?: number;
  observable_pct?: number;
  observability_note_pt?: string;
  attention_label_pt?: string;
  expression_label_pt?: string;
  insufficient_data?: boolean;
  time_by_category?: Category[];
  observation_profile?: Record<string, number>;
  signals?: Signal[];
};

type Props = {
  student: Student;
};

const CATEGORY_ORDER = ["phone", "eyes", "head_down", "face_covered", "low_attention"];

export function StudentRowExpand({ student }: Props) {
  const catMap = new Map((student.time_by_category || []).map((c) => [c.category_id, c]));
  const categories = CATEGORY_ORDER.map((id) => catMap.get(id)).filter(Boolean) as Category[];
  const signals = student.signals || [];
  const profile = student.observation_profile || {};

  return (
    <div className="student-expand">
      <div className="expand-summary">
        <div>
          <span className="expand-label">Atenção</span>
          <strong>{student.attention_label_pt || "—"}</strong>
        </div>
        <div>
          <span className="expand-label">Expressão aparente</span>
          <strong>{student.expression_label_pt || "—"}</strong>
        </div>
        <div>
          <span className="expand-label">Tempo presente</span>
          <strong>{fmtDur(student.presence_seconds)}</strong>
        </div>
      </div>

      <div>
        <h3 className="expand-h3">Sinais comportamentais (tempo na sessão)</h3>
        <ul className="category-totals">
          {categories.map((c) => (
            <li key={c.category_id} className={c.total_seconds > 0 ? "" : "zero"}>
              <strong>{c.label_pt}</strong>
              <span>{c.total_seconds > 0 ? fmtDur(c.total_seconds) : "0s"}</span>
              {c.occurrence_count && c.occurrence_count > 1 ? (
                <span className="muted"> · {c.occurrence_count} episódios</span>
              ) : null}
            </li>
          ))}
          {categories.length === 0 && (
            <li className="muted">Sem categorias agregadas ainda.</li>
          )}
        </ul>
      </div>

      <div>
        <h3 className="expand-h3">Atenção / expressão / observabilidade</h3>
        <ul className="category-totals compact">
          <li>
            <strong>Atenção alta</strong>
            <span>{fmtDur(profile.attention_high_seconds)}</span>
          </li>
          <li>
            <strong>Atenção moderada</strong>
            <span>{fmtDur(profile.attention_moderate_seconds)}</span>
          </li>
          <li>
            <strong>Atenção baixa</strong>
            <span>{fmtDur(profile.attention_low_seconds)}</span>
          </li>
          <li>
            <strong>Expressão positiva</strong>
            <span>{fmtDur(profile.expression_positive_seconds)}</span>
          </li>
          <li>
            <strong>Expressão neutra</strong>
            <span>{fmtDur(profile.expression_neutral_seconds)}</span>
          </li>
          <li>
            <strong>Expressão negativa</strong>
            <span>{fmtDur(profile.expression_negative_seconds)}</span>
          </li>
          <li>
            <strong>Observável</strong>
            <span>{fmtDur(profile.observable_seconds)}</span>
          </li>
          <li>
            <strong>Inconclusivo</strong>
            <span>{fmtDur(profile.inconclusive_seconds)}</span>
          </li>
        </ul>
      </div>

      {signals.length > 0 && (
        <div>
          <h3 className="expand-h3">Detalhe dos episódios</h3>
          <ul className="signal-list">
            {signals.map((sig) => (
              <li key={sig.signal_key} className="signal-item">
                <div className="signal-head">
                  <strong>{sig.label_pt}</strong>
                  <span>
                    {fmtDur(sig.total_seconds)}
                    {sig.occurrence_count > 1 ? ` · ${sig.occurrence_count} ocorrências` : ""}
                  </span>
                </div>
                <p className="signal-disclaimer" title={sig.disclaimer_pt}>
                  {sig.disclaimer_pt}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export type { Student };
