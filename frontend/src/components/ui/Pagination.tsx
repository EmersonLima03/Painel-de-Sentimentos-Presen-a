type Props = {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
};

export function Pagination({ page, pageSize, total, onPage }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <div className="pagination" role="navigation" aria-label="Paginação">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Página anterior">
        Anterior
      </button>
      <span className="muted">
        Página {page} de {pages} · {total} itens
      </span>
      <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Próxima página">
        Próxima
      </button>
    </div>
  );
}
