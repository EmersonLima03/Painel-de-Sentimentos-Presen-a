import { formatClockFromUnix, formatExternalLessonLabel, type AulaMeta } from "../../utils/aulaMeta";
import { fmtDur } from "../../labels";
import { LiveStatusBadge } from "./LiveStatusBadge";
import type { WsState } from "../../types";
import type { EdgeConnectivity } from "../../utils/friendlyError";

type Props = {
  meta: AulaMeta;
  startedAt?: number | null;
  elapsedSec?: number | null;
  wsState: WsState;
  edgeState?: EdgeConnectivity;
  runtimeMode?: string;
  sessionId?: string;
};

export function LessonHeader({
  meta,
  startedAt,
  elapsedSec,
  wsState,
  edgeState,
  runtimeMode,
  sessionId,
}: Props) {
  const turma = meta.turma || "Turma não configurada";
  const disciplina = meta.disciplina || "";
  const title = disciplina ? `${turma} · ${disciplina}` : turma;
  const planned =
    meta.durationMinutes != null && meta.durationMinutes > 0
      ? `${meta.durationMinutes} min`
      : "—";
  const externalLabel = formatExternalLessonLabel(meta);

  return (
    <header className="lesson-header">
      <div className="lesson-header-main">
        <div className="lesson-title-row">
          <h1 className="lesson-title">{title}</h1>
          <LiveStatusBadge wsState={wsState} edgeState={edgeState} />
        </div>
        <p className="lesson-professor">
          {meta.professor ? (
            <>
              Professor: <strong>{meta.professor}</strong>
            </>
          ) : (
            <span className="muted">Professor: — (configure em Configurações)</span>
          )}
        </p>
        <p className={`lesson-external ${meta.externalLessonId ? "" : "muted"}`}>{externalLabel}</p>
        <div className="lesson-meta-row">
          <span>Sessão iniciada às {formatClockFromUnix(startedAt ?? null)}</span>
          <span className="lesson-dot" aria-hidden>
            ·
          </span>
          <span>Duração prevista: {planned}</span>
          <span className="lesson-dot" aria-hidden>
            ·
          </span>
          <span>Tempo decorrido: {fmtDur(elapsedSec ?? null)}</span>
        </div>
        <details className="lesson-tech">
          <summary>Detalhes técnicos</summary>
          <p className="muted">
            Modo: {runtimeMode || "—"}
            {sessionId ? ` · Sessão: ${sessionId.slice(0, 8)}…` : ""}
            {" · "}
            Atualização a cada ~2 s
          </p>
        </details>
      </div>
    </header>
  );
}
