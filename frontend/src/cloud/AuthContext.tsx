import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  supabase,
  supabaseConfigured,
  type MembershipRow,
  type OrgMembershipRow,
  type SchoolRole,
} from "./supabaseClient";

export type AuthRole = SchoolRole | "root" | "admin_rede";

type AuthState = {
  configured: boolean;
  loading: boolean;
  email: string | null;
  userId: string | null;
  memberships: MembershipRow[];
  orgMemberships: OrgMembershipRow[];
  activeSchoolId: string | null;
  activeOrganizationId: string | null;
  activeRole: AuthRole | null;
  isRoot: boolean;
  isAdminRede: boolean;
  isGestor: boolean;
  canManageFacial: boolean;
  canOpenAdmin: boolean;
  profileStatus: string | null;
  setActiveSchoolId: (id: string) => void;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
  getAccessToken: () => Promise<string | null>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [memberships, setMemberships] = useState<MembershipRow[]>([]);
  const [orgMemberships, setOrgMemberships] = useState<OrgMembershipRow[]>([]);
  const [activeSchoolId, setActiveSchoolId] = useState<string | null>(null);
  const [isRoot, setIsRoot] = useState(false);
  const [profileStatus, setProfileStatus] = useState<string | null>(null);

  const loadMemberships = useCallback(async (uid: string) => {
    if (!supabase) {
      setMemberships([]);
      setOrgMemberships([]);
      setIsRoot(false);
      setProfileStatus(null);
      return;
    }

    const [{ data: mem }, { data: orgMem }, { data: profile }] = await Promise.all([
      supabase.from("memberships").select("role, school_id, organization_id, schools(id, name)"),
      supabase
        .from("organization_memberships")
        .select("role, organization_id, organizations(id, name)"),
      supabase
        .from("profiles")
        .select("is_platform_admin, status")
        .eq("id", uid)
        .maybeSingle(),
    ]);

    const rows = ((mem as unknown) as MembershipRow[]) || [];
    const orgRows = ((orgMem as unknown) as OrgMembershipRow[]) || [];
    const root = Boolean(profile?.is_platform_admin);
    const status = (profile?.status as string) || "active";

    setMemberships(rows);
    setOrgMemberships(orgRows);
    setIsRoot(root);
    setProfileStatus(status);
    setActiveSchoolId((prev) => {
      if (prev && rows.some((r) => r.school_id === prev)) return prev;
      return rows[0]?.school_id || null;
    });

    // Best-effort last_login stamp (RLS allows self update if policy exists; ignore errors)
    void supabase
      .from("profiles")
      .update({ last_login_at: new Date().toISOString() })
      .eq("id", uid);
  }, []);

  const refresh = useCallback(async () => {
    if (!supabase) {
      setLoading(false);
      setEmail(null);
      setUserId(null);
      setMemberships([]);
      setOrgMemberships([]);
      setIsRoot(false);
      return;
    }
    const { data } = await supabase.auth.getSession();
    const session = data.session;
    const uid = session?.user?.id || null;
    setEmail(session?.user?.email || null);
    setUserId(uid);
    if (session && uid) await loadMemberships(uid);
    else {
      setMemberships([]);
      setOrgMemberships([]);
      setActiveSchoolId(null);
      setIsRoot(false);
      setProfileStatus(null);
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

  const isAdminRede = orgMemberships.some((m) => m.role === "admin_rede");

  const activeGestor =
    memberships.find((m) => m.school_id === activeSchoolId && m.role === "gestor") || null;
  const active =
    activeGestor ||
    memberships.find((m) => m.school_id === activeSchoolId) ||
    memberships[0] ||
    null;

  let activeRole: AuthRole | null = null;
  if (isRoot) activeRole = "root";
  else if (isAdminRede && !active) activeRole = "admin_rede";
  else if (active?.role) activeRole = active.role as SchoolRole;

  const schoolRole = (active?.role as SchoolRole | undefined) || null;
  const isGestor =
    isRoot ||
    isAdminRede ||
    schoolRole === "gestor" ||
    schoolRole === "coordenador";
  const canManageFacial =
    isRoot || isAdminRede || schoolRole === "gestor" || schoolRole === "coordenador";
  const canOpenAdmin =
    isRoot ||
    isAdminRede ||
    schoolRole === "gestor" ||
    schoolRole === "coordenador" ||
    schoolRole === "professor" ||
    schoolRole === "monitor";

  const value = useMemo<AuthState>(
    () => ({
      configured: supabaseConfigured,
      loading,
      email,
      userId,
      memberships,
      orgMemberships,
      activeSchoolId: active?.school_id || activeSchoolId,
      activeOrganizationId:
        active?.organization_id || orgMemberships[0]?.organization_id || null,
      activeRole,
      isRoot,
      isAdminRede,
      isGestor,
      canManageFacial,
      canOpenAdmin,
      profileStatus,
      setActiveSchoolId,
      refresh,
      signOut: async () => {
        if (supabase) await supabase.auth.signOut();
      },
      getAccessToken: async () => {
        if (!supabase) return null;
        const { data } = await supabase.auth.getSession();
        return data.session?.access_token || null;
      },
    }),
    [
      loading,
      email,
      userId,
      memberships,
      orgMemberships,
      active,
      activeSchoolId,
      activeRole,
      isRoot,
      isAdminRede,
      isGestor,
      canManageFacial,
      canOpenAdmin,
      profileStatus,
      refresh,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
