type Props = {
  title?: string;
  message: string;
  hint?: string;
};

export function EmptyState({ title = "Sem dados", message, hint }: Props) {
  return (
    <div className="state-box empty" role="status">
      <strong>{title}</strong>
      <p>{message}</p>
      {hint && <p className="muted state-hint">{hint}</p>}
    </div>
  );
}

export function LoadingState({ label = "Carregando…" }: { label?: string }) {
  return (
    <div className="state-box loading" role="status" aria-busy="true" aria-label={label}>
      <div className="skeleton-row" />
      <div className="skeleton-grid">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="skeleton-card" />
        ))}
      </div>
      <p className="muted">{label}</p>
    </div>
  );
}

export function UnavailableState({
  title = "Ainda não disponível",
  message,
}: {
  title?: string;
  message: string;
}) {
  return (
    <div className="state-box unavailable" role="status">
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}

export function ErrorState({
  message,
  title = "Não foi possível atualizar",
  hint,
}: {
  message: string;
  title?: string;
  hint?: string;
}) {
  return (
    <div className="state-box error-box" role="alert">
      <strong>{title}</strong>
      <p>{message}</p>
      {hint ? <p className="state-hint">{hint}</p> : null}
    </div>
  );
}

export function DegradedState({
  lastUpdateLabel,
}: {
  lastUpdateLabel?: string;
}) {
  return (
    <div className="state-box warn-box" role="status">
      <strong>Conexão com a sala temporariamente indisponível.</strong>
      <p>Estamos tentando reconectar. Os dados serão atualizados quando a conexão for restabelecida.</p>
      {lastUpdateLabel ? <p className="state-hint">Última atualização: {lastUpdateLabel}</p> : null}
    </div>
  );
}
