import type { Tab } from "../../types";

type NavItem = {
  id: Tab;
  label: string;
  badge?: number;
};

type Props = {
  active: Tab;
  onNavigate: (tab: Tab) => void;
  productItems: NavItem[];
  adminItems?: NavItem[];
  qaItems?: NavItem[];
  open?: boolean;
  onClose?: () => void;
  sessionEmail?: string | null;
  onSignOut?: () => void;
};

export function AppSidebar({
  active,
  onNavigate,
  productItems,
  adminItems = [],
  qaItems = [],
  open,
  onClose,
  sessionEmail,
  onSignOut,
}: Props) {
  const go = (id: Tab) => {
    onNavigate(id);
    onClose?.();
  };

  return (
    <>
      {open && <div className="sidebar-backdrop" onClick={onClose} aria-hidden />}
      <aside className={`app-sidebar ${open ? "open" : ""}`} aria-label="Navegação principal">
        <div className="sidebar-brand">
          <strong>Presença</strong>
          <span className="muted">painel da aula</span>
        </div>
        <nav className="sidebar-nav">
          {productItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sidebar-item ${active === item.id || (item.id === "live" && active === "overview") ? "active" : ""}`}
              onClick={() => go(item.id)}
              aria-current={active === item.id || (item.id === "live" && active === "overview") ? "page" : undefined}
            >
              <span>{item.label}</span>
              {item.badge != null && item.badge > 0 && (
                <span className="tab-badge">{item.badge}</span>
              )}
            </button>
          ))}
        </nav>
        {adminItems.length > 0 && (
          <div className="sidebar-qa">
            <div className="sidebar-section-label">Administração</div>
            {adminItems.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`sidebar-item ${active === item.id ? "active" : ""}`}
                onClick={() => go(item.id)}
                aria-current={active === item.id ? "page" : undefined}
              >
                {item.label}
              </button>
            ))}
          </div>
        )}
        {qaItems.length > 0 && (
          <div className="sidebar-qa">
            <div className="sidebar-section-label">Ferramentas internas</div>
            {qaItems.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`sidebar-item ${active === item.id ? "active" : ""}`}
                onClick={() => go(item.id)}
                aria-current={active === item.id ? "page" : undefined}
              >
                {item.label}
              </button>
            ))}
          </div>
        )}
        <div className="sidebar-foot muted">
          {sessionEmail && (
            <div className="sidebar-session">
              <span className="sidebar-session-email" title={sessionEmail}>
                {sessionEmail}
              </span>
              {onSignOut && (
                <button type="button" className="sidebar-link" onClick={onSignOut}>
                  Sair
                </button>
              )}
            </div>
          )}
          <a href="/dashboard-legacy" className="sidebar-link">
            Painel legado
          </a>
        </div>
      </aside>
    </>
  );
}
