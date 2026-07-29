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

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state-box error-box" role="alert">
      <strong>Não foi possível atualizar</strong>
      <p>{message}</p>
    </div>
  );
}
