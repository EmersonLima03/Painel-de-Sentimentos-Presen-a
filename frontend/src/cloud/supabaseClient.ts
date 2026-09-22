/**
 * Cliente Supabase (browser) — apenas publishable/anon key.
 * Nunca service_role aqui.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = (import.meta as any).env?.VITE_SUPABASE_URL || "";
const anon = (import.meta as any).env?.VITE_SUPABASE_ANON_KEY || "";

export const supabaseConfigured = Boolean(url && anon);

export const supabase: SupabaseClient | null = supabaseConfigured
  ? createClient(url, anon, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;

/** School-scoped staff roles (memberships.role). */
export type SchoolRole = "gestor" | "coordenador" | "professor" | "monitor";

/** Organization-scoped role. */
export type OrgRole = "admin_rede";

export type MembershipRow = {
  role: SchoolRole;
  school_id: string;
  organization_id: string;
  schools?: { id: string; name: string } | null;
};

export type OrgMembershipRow = {
  role: OrgRole;
  organization_id: string;
  organizations?: { id: string; name: string } | null;
};
