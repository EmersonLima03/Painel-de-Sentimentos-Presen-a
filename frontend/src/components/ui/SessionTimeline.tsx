import { SessionTimelineChart } from "../SessionTimelineChart";

type Props = {
  climateTimeline?: any[];
  sessionTimeline?: any[];
};

/** Usa climate_timeline quando disponível; senão timeline de sessão; senão empty. */
export function SessionTimeline({ climateTimeline, sessionTimeline }: Props) {
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

  const events = (sessionTimeline || []).filter(
    (e) => e?.type === "event_opened" || e?.event_type || e?.lifecycle === "opened"
  );
  if (events.length > 0) {
    return (
      <div className="session-timeline-wrap">
        <p className="panel-sub">Eventos registrados nesta sessão</p>
        <ul className="timeline-event-list">
          {events.slice(-20).map((e: any, i: number) => (
            <li key={e.event_id || i}>
              <span>{e.event_type || e.type || "evento"}</span>
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
