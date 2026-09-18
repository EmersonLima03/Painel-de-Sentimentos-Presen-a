import { formatClockFromUnix, type AulaMeta } from "../../utils/aulaMeta";
import { fmtDur } from "../../labels";
import { LiveStatusBadge } from "./LiveStatusBadge";
import type { WsState } from "../../types";
import type { EdgeConnectivity } from "../../utils/friendlyError";

export type LessonContextView = {
  class_group_name?: string | null;
  subject_name?: string | null;
  teacher_name?: string | null;
  room_name?: string | null;
  scheduled_start_at?: string | null;
  scheduled_duration_minutes?: number | null;
  external_lesson_id?: string | null;
  lesson_occurrence_id?: string | null;
};

type Props = {
  /** Fallback legado (localStorage) — NÃO é fonte de verdade. */
  meta?: AulaMeta;
  context?: LessonContextView | null;
  startedAt?: number | null;
  elapsedSec?: number | null;
  wsState: WsState;
  edgeState?: EdgeConnectivity;
  runtimeMode?: string;
  sessionId?: string;
};

function scheduledWindow(ctx: LessonContextView | null | undefined): string {
  if (!ctx?.scheduled_start_at || !ctx.scheduled_duration_minutes) return "";
  try {
    const start = new Date(ctx.scheduled_start_at);
    const end = new Date(start.getTime() + Number(ctx.scheduled_duration_minutes) * 60_000);
    const fmt = (d: Date) =>
      d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    return `${fmt(start)}–${fmt(end)}`;
  } catch {
    return "";
  }
}

export function LessonHeader({
  meta,
  context,
  startedAt,
  elapsedSec,
  wsState,
  edgeState,
  runtimeMode,
  sessionId,
}: Props) {
  const turma = context?.class_group_name || meta?.turma || "Turma não configurada";
  const disciplina = context?.subject_name || meta?.disciplina || "";
  const professor = context?.teacher_name || meta?.professor || "";
  const sala = context?.room_name || "";
  const title = disciplina ? `${turma} · ${disciplina}` : turma;
  const duration =
    context?.scheduled_duration_minutes ?? meta?.durationMinutes ?? null;
  const planned = duration != null && duration > 0 ? `${duration} min` : "—";
  const windowLabel = scheduledWindow(context);
  const hasContext = Boolean(context?.lesson_occurrence_id || context?.class_group_name);

  return (
    <header className="lesson-header">
      <div className="lesson-header-main">
        <div className="lesson-title-row">
          <h1 className="lesson-title">{title}</h1>
          <LiveStatusBadge wsState={wsState} edgeState={edgeState} />
        </div>
        <p className="lesson-professor">
          {professor ? (
            <>
              Professor: <strong>{professor}</strong>
              {sala ? (
                <>
                  {" "}
                  · Sala <strong>{sala}</strong>
                </>
              ) : null}
            </>
          ) : (
            <span className="muted">
              {hasContext
                ? "Professor: —"
                : "Nenhuma aula iniciada — use Administração → Minhas aulas de hoje"}
            </span>
          )}
        </p>
        {windowLabel ? (
          <p className="lesson-external">Horário previsto: {windowLabel}</p>
        ) : null}
        <div className="lesson-meta-row">
          <span>
            Sessão iniciada às {formatClockFromUnix(startedAt ?? null)}
            {startedAt ? " · AO VIVO" : ""}
          </span>
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
            {context?.external_lesson_id
              ? ` · Lesson: ${context.external_lesson_id}`
              : ""}
            {" · "}
            Atualização a cada ~2 s
          </p>
        </details>
      </div>
    </header>
  );
}
