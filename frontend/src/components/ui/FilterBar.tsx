type Filter = { id: string; label: string };

type Props = {
  search: string;
  onSearch: (v: string) => void;
  filters: Filter[];
  activeFilter: string;
  onFilter: (id: string) => void;
  searchPlaceholder?: string;
};

export function FilterBar({
  search,
  onSearch,
  filters,
  activeFilter,
  onFilter,
  searchPlaceholder = "Buscar por nome…",
}: Props) {
  return (
    <div className="filter-bar">
      <label className="filter-search">
        <span className="sr-only">Buscar</span>
        <input
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={searchPlaceholder}
          aria-label="Buscar alunos"
        />
      </label>
      <div className="filter-chips" role="group" aria-label="Filtros">
        {filters.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`filter-chip ${activeFilter === f.id ? "active" : ""}`}
            onClick={() => onFilter(f.id)}
            aria-pressed={activeFilter === f.id}
          >
            {f.label}
          </button>
        ))}
      </div>
    </div>
  );
}
