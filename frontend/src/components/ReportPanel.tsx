import { Fragment, useState } from "react";
import { ClimateBars } from "./ClimateBars";
import { SessionAnswers } from "./SessionAnswers";
import { SessionTimelineChart } from "./SessionTimelineChart";
import { StudentRowExpand } from "./StudentRowExpand";
import { exprLabel, fmtDur, fmtPct } from "../labels";

type Props = {
  report: any;
  summary: any;
  students: any[];
  events: any[];
};

export function ReportPanel({ report, summary, students, events }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!report) {
    return (
      <section>
        <h1>Respostas da aula</h1>
        <p className="muted">Aguardando dados da sessão… deixe a câmera rodar alguns minutos.</p>
      </section>
    );
  }

  const climateHist = report.climate_history || {};
  const timeline = report.climate_timeline || [];
  const reportStudents = report.students?.length ? report.students : students;
  const identified = reportStudents.filter((s: any) => s.student_id);

  const toggle = (key: string) => {
    setExpanded((prev) => (prev === key ? null : key));
  };

  return (
    <section className="report">
      <h1>Respostas da aula</h1>
      <p className="muted">
        Aqui estão as respostas em português. A aba Eventos (QA) é só para equipe técnica — ignore-a no uso
        pedagógico.
      </p>

      <SessionAnswers report={report} students={reportStudents} />

      <div className="report-kpi-grid">
        <div className="report-kpi">
          <span>Duração</span>
          <strong>{fmtDur(report.duration_seconds)}</strong>
        </div>
        <div className="report-kpi">
          <span>Pico visível</span>
          <strong>{report.peak_visible ?? "—"}</strong>
        </div>
        <div className="report-kpi">
          <span>% observável (média)</span>
          <strong>{report.observable_pct_avg != null ? fmtPct(report.observable_pct_avg) : "—"}</strong>
        </div>
        <div className="report-kpi">
          <span>Clima aparente final</span>
          <strong>{report.climate_label_pt || exprLabel(report.climate)}</strong>
        </div>
        <div className="report-kpi">
          <span>Alunos no relatório</span>
          <strong>{report.students_count ?? identified.length}</strong>
        </div>
      </div>

      <div className="panel">
        <SessionTimelineChart timeline={timeline} />
        {Object.keys(climateHist).length > 0 && (
          <ClimateBars distribution={climateHist} dominant={report.climate} />
        )}
      </div>

      <div className="panel">
        <h2>Detalhe por aluno</h2>
        <p className="panel-sub">Clique na linha (▸) para ver sinais em português com duração e ressalva</p>
        {reportStudents.length === 0 && <p className="muted">Nenhum aluno acumulado ainda.</p>}
        <table className="report-table compact">
          <thead>
            <tr>
              <th aria-label="Expandir" />
              <th>Nome</th>
              <th>Tempo presente</th>
              <th>% observável</th>
              <th>Observabilidade</th>
            </tr>
          </thead>
          <tbody>
            {reportStudents.map((s: any) => {
              const rowKey = s.person_key || s.student_id || s.track_id || s.full_name;
              const isOpen = expanded === rowKey;
              return (
                <Fragment key={rowKey}>
                  <tr
                    className={`report-row ${isOpen ? "expanded" : ""}`}
                    onClick={() => toggle(rowKey)}
                  >
                    <td className="expand-cell">{isOpen ? "▾" : "▸"}</td>
                    <td>{s.full_name}</td>
                    <td>{fmtDur(s.presence_seconds)}</td>
                    <td>{s.observable_pct != null ? fmtPct(s.observable_pct) : "—"}</td>
                    <td className="muted">{s.observability_note_pt || "—"}</td>
                  </tr>
                  {isOpen && (
                    <tr className="report-row-detail">
                      <td colSpan={5}>
                        <StudentRowExpand student={s} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {report.limitations && (
        <ul className="limitations">
          {report.limitations.map((l: string, i: number) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
