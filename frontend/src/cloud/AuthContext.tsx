import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { supabase, supabaseConfigured, type MembershipRow } from "./supabaseClient";

export type AuthRole = "gestor" | "professor" | "monitor";

type AuthState = {
  configured: boolean;
  loading: boolean;
  email: string | null;
  userId: string | null;
  memberships: MembershipRow[];
  activeSchoolId: string | null;
  activeOrganizationId: string | null;
  activeRole: AuthRole | null;
  isGestor: boolean;
  setActiveSchoolId: (id: string) => void;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [memberships, setMemberships] = useState<MembershipRow[]>([]);
  const [activeSchoolId, setActiveSchoolId] = useState<string | null>(null);

  const loadMemberships = useCallback(async () => {
    if (!supabase) {
      setMemberships([]);
      return;
    }
    const { data } = await supabase
      .from("memberships")
      .select("role, school_id, organization_id, schools(id, name)");
    const rows = ((data as unknown) as MembershipRow[]) || [];
    setMemberships(rows);
    setActiveSchoolId((prev) => {
      if (prev && rows.some((r) => r.school_id === prev)) return prev;
      return rows[0]?.school_id || null;
    });
  }, []);

  const refresh = useCallback(async () => {
    if (!supabase) {
      setLoading(false);
      return;
    }
    const { data } = await supabase.auth.getSession();
    const session = data.session;
    setEmail(session?.user?.email || null);
    setUserId(session?.user?.id || null);
    if (session) await loadMemberships();
    else {
      setMemberships([]);
      setActiveSchoolId(null);
    }
    setLoading(false);
  }, [loadMemberships]);

  useEffect(() => {
    void refresh();
    if (!supabase) return;
    const { data: sub } = supabase.auth.onAuthStateChange(() => {
      void refresh();
    });
    return () => sub.subscription.unsubscribe();
  }, [refresh]);

  const activeGestor =
    memberships.find((m) => m.school_id === activeSchoolId && m.role === "gestor") || null;
  const active =
    activeGestor ||
    memberships.find((m) => m.school_id === activeSchoolId) ||
    memberships[0] ||
    null;
  const activeRole = (active?.role as AuthRole) || null;

  const value = useMemo<AuthState>(
    () => ({
      configured: supabaseConfigured,
      loading,
      email,
      userId,
      memberships,
      activeSchoolId: active?.school_id || null,
      activeOrganizationId: active?.organization_id || null,
      activeRole,
      isGestor: activeRole === "gestor",
      setActiveSchoolId,
      refresh,
      signOut: async () => {
        if (supabase) await supabase.auth.signOut();
      },
    }),
    [loading, email, userId, memberships, active, activeRole, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
