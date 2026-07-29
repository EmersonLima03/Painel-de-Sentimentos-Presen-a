import { fmtDur, fmtPct } from "../labels";

type Category = {
  category_id: string;
  label_pt: string;
  total_seconds: number;
  occurrence_count?: number;
  disclaimer_pt?: string;
};

export type SessionAnswersFocus =
  | "all"
  | "presence"
  | "signals"
  | "attention"
  | "expression"
  | "quality";

type Props = {
  report: any;
  students: any[];
  /** Filtra blocos sem remover o componente — default: tudo. */
  focus?: SessionAnswersFocus;
  /** Esconde o título interno quando já há SectionHeader na view. */
  hideTitle?: boolean;
};

const CATEGORY_ORDER = ["phone", "eyes", "head_down", "face_covered", "low_attention"];

function sortCategories(cats: Category[]): Category[] {
  const map = new Map(cats.map((c) => [c.category_id, c]));
  return CATEGORY_ORDER.map((id) => map.get(id)).filter(Boolean) as Category[];
}

function show(focus: SessionAnswersFocus, block: SessionAnswersFocus | "all"): boolean {
  return focus === "all" || focus === block;
}

export function SessionAnswers({ report, students, focus = "all", hideTitle }: Props) {
  const list = report?.students?.length ? report.students : students || [];
  const identified = list.filter((s: any) => s.student_id);
  const lowObs = list.filter((s: any) => s.observability_note_pt);
  const classCats = sortCategories(
    report?.time_by_category || report?.class_summary?.time_by_category || []
  );
  const profile = report?.observation_profile || report?.class_summary?.observation_profile || {};

  const who =
    identified.length > 0
      ? identified.map((s: any) => s.full_name).join(", ")
      : list.length > 0
        ? `${list.length} pessoa(s) no enquadramento (ainda sem identificação confirmada)`
        : "Ninguém acumulado nesta sessão ainda — deixe a câmera rodar alguns minutos.";

  const howLong =
    list.length === 0
      ? "Sem dados de presença ainda."
      : list
          .slice(0, focus === "presence" ? 40 : 8)
          .map((s: any) => `${s.full_name}: ${fmtDur(s.presence_seconds)}`)
          .join(" · ") +
        (list.length > (focus === "presence" ? 40 : 8)
          ? ` · … (+${list.length - (focus === "presence" ? 40 : 8)} na aba Por aluno)`
          : "");

  const attention =
    report?.attention_label_pt ||
    "Atenção da turma ainda inconclusiva — precisa de mais tempo observável.";

  const climate =
    report?.climate_label_pt || "Clima aparente ainda sem amostra suficiente.";

  const obsNote =
    lowObs.length > 0
      ? lowObs.map((s: any) => `${s.full_name}: ${s.observability_note_pt}`).join(" ")
      : report?.observable_pct_avg != null
        ? `Média de observabilidade da sessão: ${fmtPct(report.observable_pct_avg)}.`
        : "Sem média de observabilidade ainda.";

  return (
    <div className={`answers-panel ${hideTitle ? "embedded" : "panel"}`}>
      {!hideTitle && (
        <>
          <h2>Respostas da aula</h2>
          <p className="panel-sub">
            Tempos acumulados na sessão — todos os cenários cobertos pelo sistema hoje. Indicadores
            visuais estimados, não avaliação de alunos.
          </p>
        </>
      )}
      <dl className="answers-list">
        {show(focus, "presence") && (
          <div className="answer-item">
            <dt>Quem esteve presente?</dt>
            <dd>{who}</dd>
          </div>
        )}
        {show(focus, "presence") && (
          <div className="answer-item">
            <dt>Por quanto tempo?</dt>
            <dd>{howLong}</dd>
          </div>
        )}

        {show(focus, "signals") && (
          <div className="answer-item highlight">
            <dt>Sinais comportamentais (tempo na sessão)</dt>
            <dd>
              <ul className="category-totals">
                {classCats.length === 0 && (
                  <li className="muted">Aguardando agregação…</li>
                )}
                {classCats.map((c) => (
                  <li key={c.category_id} className={c.total_seconds > 0 ? "" : "zero"}>
                    <strong>{c.label_pt}</strong>
                    <span>{c.total_seconds > 0 ? fmtDur(c.total_seconds) : "0s"}</span>
                    {c.occurrence_count && c.occurrence_count > 1 ? (
                      <span className="muted"> · {c.occurrence_count} episódios</span>
                    ) : null}
                  </li>
                ))}
              </ul>
              <p className="muted answers-hint">
                Inclui: celular possível/provável · olhos parcial/fechados · cabeça baixa/apoiada ·
                rosto coberto · baixa atenção visual persistente.
              </p>
            </dd>
          </div>
        )}

        {show(focus, "attention") && (
          <div className="answer-item">
            <dt>Atenção visual ao longo da sessão</dt>
            <dd>
              <ul className="category-totals compact">
                <li>
                  <strong>Alta</strong>
                  <span>{fmtDur(profile.attention_high_seconds)}</span>
                </li>
                <li>
                  <strong>Moderada</strong>
                  <span>{fmtDur(profile.attention_moderate_seconds)}</span>
                </li>
                <li>
                  <strong>Baixa</strong>
                  <span>{fmtDur(profile.attention_low_seconds)}</span>
                </li>
              </ul>
              <p className="muted answers-hint">{attention}</p>
            </dd>
          </div>
        )}

        {show(focus, "expression") && (
          <div className="answer-item">
            <dt>Expressão aparente ao longo da sessão</dt>
            <dd>
              <ul className="category-totals compact">
                <li>
                  <strong>Positiva</strong>
                  <span>{fmtDur(profile.expression_positive_seconds)}</span>
                </li>
                <li>
                  <strong>Neutra</strong>
                  <span>{fmtDur(profile.expression_neutral_seconds)}</span>
                </li>
                <li>
                  <strong>Negativa</strong>
                  <span>{fmtDur(profile.expression_negative_seconds)}</span>
                </li>
                <li>
                  <strong>Mista / surpresa</strong>
                  <span>{fmtDur(profile.expression_mixed_seconds)}</span>
                </li>
              </ul>
              <p className="muted answers-hint">{climate}</p>
            </dd>
          </div>
        )}

        {show(focus, "quality") && (
          <div className="answer-item">
            <dt>A câmera conseguiu observar bem?</dt>
            <dd>
              <ul className="category-totals compact">
                <li>
                  <strong>Tempo observável</strong>
                  <span>{fmtDur(profile.observable_seconds)}</span>
                </li>
                <li>
                  <strong>Tempo inconclusivo</strong>
                  <span>{fmtDur(profile.inconclusive_seconds)}</span>
                </li>
              </ul>
              <p className="muted answers-hint">{obsNote}</p>
            </dd>
          </div>
        )}
      </dl>
      {focus === "all" && (
        <p className="muted answers-hint">
          Detalhe por aluno: use a aba <strong>Por aluno</strong> (busca, ordenação e ▸ para expandir).
        </p>
      )}
    </div>
  );
}
