import { useState } from "react";
import { AppSidebar } from "./AppSidebar";
import type { Tab } from "../../types";

type NavItem = { id: Tab; label: string; badge?: number };

type Props = {
  active: Tab;
  onNavigate: (tab: Tab) => void;
  productItems: NavItem[];
  adminItems?: NavItem[];
  qaItems?: NavItem[];
  demoBanner?: React.ReactNode;
  sessionEmail?: string | null;
  onSignOut?: () => void;
  children: React.ReactNode;
};

export function AppShell({
  active,
  onNavigate,
  productItems,
  adminItems,
  qaItems,
  demoBanner,
  sessionEmail,
  onSignOut,
  children,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="app-shell">
      {demoBanner}
      <button
        type="button"
        className="menu-toggle"
        aria-label="Abrir menu"
        onClick={() => setMenuOpen(true)}
      >
        Menu
      </button>
      <AppSidebar
        active={active}
        onNavigate={onNavigate}
        productItems={productItems}
        adminItems={adminItems}
        qaItems={qaItems}
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        sessionEmail={sessionEmail}
        onSignOut={onSignOut}
      />
      <div className="app-main">{children}</div>
    </div>
  );
}
