import { eventTypePt, fmtDur } from "../../labels";
import { SessionTimelineChart } from "../SessionTimelineChart";

type Props = {
  climateTimeline?: any[];
  sessionTimeline?: any[];
  events?: any[];
  /** Fase 1: prioriza lista pedagógica de eventos, não o gráfico de % observável. */
  preferEvents?: boolean;
};

function formatEventWhen(ev: any): string {
  const ts = ev.opened_at ?? ev.started_at ?? ev.t ?? ev.updated_at;
  if (ts == null) return "";
  if (typeof ts === "number" && ts < 1e12 && ts < 86400 * 7) {
    return `t=${Math.round(ts)}s`;
  }
  const n = Number(ts);
  if (!Number.isFinite(n)) return "";
  const ms = n > 1e12 ? n : n * 1000;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function collectLessonEvents(
  sessionTimeline: any[] | undefined,
  events: any[] | undefined
): any[] {
  const fromSession = (sessionTimeline || []).filter(
    (e) => e?.type === "event_opened" || e?.event_type || e?.lifecycle === "opened"
  );
  const fromEvents = events || [];
  const merged = [...fromEvents, ...fromSession];
  const seen = new Set<string>();
  const out: any[] = [];
  for (const e of merged) {
    const id = String(e.event_id || e.id || `${e.event_type}:${e.opened_at || e.t}:${e.student_id || ""}`);
    if (seen.has(id)) continue;
    seen.add(id);
    out.push(e);
  }
  out.sort((a, b) => {
    const ta = Number(a.opened_at ?? a.started_at ?? a.t ?? 0);
    const tb = Number(b.opened_at ?? b.started_at ?? b.t ?? 0);
    return ta - tb;
  });
  return out.slice(-30);
}

/** Usa climate_timeline quando disponível; senão timeline de sessão; senão empty. */
export function SessionTimeline({
  climateTimeline,
  sessionTimeline,
  events,
  preferEvents,
}: Props) {
  const lessonEvents = collectLessonEvents(sessionTimeline, events);

  if (preferEvents) {
    if (lessonEvents.length > 0) {
      return (
        <div className="session-timeline-wrap">
          <ul className="timeline-event-list lesson-events">
            {lessonEvents.map((e: any, i: number) => {
              const when = formatEventWhen(e);
              const name = e.full_name || e.student_id || "";
              const label = eventTypePt(e.event_type || e.type);
              const life = String(e.lifecycle || "").toLowerCase();
              const closed = life === "closed" || e.ended_at != null || e.closed_at != null;
              return (
                <li key={e.event_id || i}>
                  {when && <span className="tle-when">{when}</span>}
                  <span className="tle-body">
                    {name ? `${name} — ` : ""}
                    {label}
                    {closed ? " · encerrado" : ""}
                    {e.duration_seconds != null ? ` · ${fmtDur(e.duration_seconds)}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
          {(climateTimeline || []).length > 0 && (
            <details className="timeline-quality-details">
              <summary className="muted">Qualidade ao longo do tempo (% observável)</summary>
              <SessionTimelineChart timeline={climateTimeline || []} title="" />
            </details>
          )}
        </div>
      );
    }
    return (
      <p className="muted">
        Ainda não há ocorrências registradas nesta sessão. Sinais e eventos aparecerão aqui conforme a
        aula avança.
      </p>
    );
  }

  const climate = climateTimeline || [];
  if (climate.length > 0) {
    return (
      <div className="session-timeline-wrap">
        <SessionTimelineChart timeline={climate} title="Linha do tempo da sessão" />
        <div className="timeline-legend muted">
          <span>Barras = % observável ao longo do tempo</span>
        </div>
      </div>
    );
  }

  if (lessonEvents.length > 0) {
    return (
      <div className="session-timeline-wrap">
        <p className="panel-sub">Eventos registrados nesta sessão</p>
        <ul className="timeline-event-list">
          {lessonEvents.slice(-20).map((e: any, i: number) => (
            <li key={e.event_id || i}>
              <span>{eventTypePt(e.event_type || e.type)}</span>
              {e.t != null && <span className="muted"> · t={Math.round(e.t)}s</span>}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <p className="muted">Ainda não há amostras suficientes para a linha do tempo desta sessão.</p>
  );
}
