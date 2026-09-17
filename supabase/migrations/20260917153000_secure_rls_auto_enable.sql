-- Sentimentos v1 — Fase 1: secure rls_auto_enable
-- Keep event trigger ensure_rls; revoke public RPC EXECUTE on SECURITY DEFINER.

REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon;
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM authenticated;
