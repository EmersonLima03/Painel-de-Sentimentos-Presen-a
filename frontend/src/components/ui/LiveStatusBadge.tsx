import type { WsState } from "../../types";
import type { EdgeConnectivity } from "../../utils/friendlyError";

type Props = {
  wsState: WsState;
  edgeState?: EdgeConnectivity;
};

export function LiveStatusBadge({ wsState, edgeState }: Props) {
  const degraded =
    edgeState === "offline" ||
    edgeState === "reconnecting" ||
    (edgeState !== "live" && edgeState !== undefined && edgeState !== "broken" && edgeState !== "auth");

  let label = "Ao vivo";
  let on = false;
  if (edgeState === "offline" || (wsState === "disconnected" && edgeState !== "live")) {
    label = "Sem conexão";
  } else if (edgeState === "reconnecting" || wsState === "connecting" || degraded) {
    label = "Reconectando";
  } else if (wsState === "connected" && (edgeState === "live" || !edgeState)) {
    label = "Ao vivo";
    on = true;
  } else if (wsState === "disconnected") {
    label = "Sem conexão";
  } else {
    label = "Conectando…";
  }

  return (
    <div className="live-pill" role="status" aria-live="polite">
      <span className={`dot ${on ? "on" : ""}`} aria-hidden />
      <span>{label}</span>
    </div>
  );
}
