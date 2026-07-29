type Props = {
  title: string;
  children?: React.ReactNode;
  empty?: boolean;
  emptyMessage?: string;
};

export function ChartCard({ title, children, empty, emptyMessage }: Props) {
  return (
    <div className="panel chart-card">
      <h3 className="chart-card-title">{title}</h3>
      {empty ? (
        <p className="muted">{emptyMessage || "Ainda não há dados suficientes para este período."}</p>
      ) : (
        children
      )}
    </div>
  );
}
