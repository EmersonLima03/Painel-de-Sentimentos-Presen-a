import { LiveStatusBadge } from "../ui/LiveStatusBadge";
import { Disclaimer } from "../ui/Disclaimer";
import { fmtDur } from "../../labels";
import type { WsState } from "../../types";

type Props = {
  title: string;
  subtitle?: string;
  wsState?: WsState;
  showLive?: boolean;
  elapsed?: number | null;
  runtimeMode?: string;
  sessionId?: string;
  updatedHint?: string;
  children?: React.ReactNode;
};

export function PageHeader({
  title,
  subtitle,
  wsState,
  showLive,
  elapsed,
  runtimeMode,
  sessionId,
  updatedHint,
  children,
}: Props) {
  return (
    <header className="page-header">
      <div className="page-header-row">
        <div>
          <h1 className="page-title">{title}</h1>
          {subtitle && <p className="page-sub muted">{subtitle}</p>}
          <div className="page-meta muted">
            {runtimeMode && <span>Modo: {runtimeMode}</span>}
            {sessionId && <span>Sessão: {sessionId.slice(0, 8)}…</span>}
            {elapsed != null && <span>Duração: {fmtDur(elapsed)}</span>}
            {updatedHint && <span>{updatedHint}</span>}
          </div>
        </div>
        <div className="page-header-aside">
          {showLive && wsState && <LiveStatusBadge wsState={wsState} />}
          {children}
        </div>
      </div>
      <Disclaimer compact />
    </header>
  );
}
