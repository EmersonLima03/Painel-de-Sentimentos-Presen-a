import type { WsState } from "../../types";

type Props = {
  wsState: WsState;
};

export function LiveStatusBadge({ wsState }: Props) {
  const on = wsState === "connected";
  const label = on ? "Ao vivo" : wsState === "connecting" ? "Conectando…" : "Desconectado";
  return (
    <div className="live-pill" role="status" aria-live="polite">
      <span className={`dot ${on ? "on" : ""}`} aria-hidden />
      <span>{label}</span>
    </div>
  );
}
