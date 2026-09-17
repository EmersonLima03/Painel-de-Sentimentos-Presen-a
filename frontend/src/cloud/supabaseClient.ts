/**
 * Cliente Supabase (browser) — apenas publishable/anon key.
 * Nunca service_role aqui.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = (import.meta as any).env?.VITE_SUPABASE_URL || "";
const anon = (import.meta as any).env?.VITE_SUPABASE_ANON_KEY || "";

export const supabaseConfigured = Boolean(url && anon);

export const supabase: SupabaseClient | null = supabaseConfigured
  ? createClient(url, anon)
  : null;

export type MembershipRow = {
  role: "gestor" | "professor" | "monitor";
  school_id: string;
  organization_id: string;
  schools?: { id: string; name: string } | null;
};
