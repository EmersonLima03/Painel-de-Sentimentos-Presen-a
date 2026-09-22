-- Auth SaaS RBAC foundation (mirror of applied remote migration)
-- Expand only; do not drop existing product tables.

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS last_login_at timestamptz,
  ADD COLUMN IF NOT EXISTS must_reset_password boolean NOT NULL DEFAULT false;

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_status_check;
ALTER TABLE public.profiles
  ADD CONSTRAINT profiles_status_check CHECK (status IN ('active', 'disabled', 'invited'));

ALTER TABLE public.memberships DROP CONSTRAINT IF EXISTS memberships_role_check;
ALTER TABLE public.memberships
  ADD CONSTRAINT memberships_role_check
  CHECK (role IN ('gestor', 'coordenador', 'professor', 'monitor'));

CREATE TABLE IF NOT EXISTS public.organization_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('admin_rede')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (profile_id, organization_id)
);

CREATE INDEX IF NOT EXISTS organization_memberships_org_idx
  ON public.organization_memberships(organization_id);
CREATE INDEX IF NOT EXISTS organization_memberships_profile_idx
  ON public.organization_memberships(profile_id);

CREATE TABLE IF NOT EXISTS public.invites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL,
  full_name text,
  role text NOT NULL,
  organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid REFERENCES public.schools(id) ON DELETE CASCADE,
  invited_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  token_hash text,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '7 days'),
  accepted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS invites_email_idx ON public.invites(email);
CREATE INDEX IF NOT EXISTS invites_school_idx ON public.invites(school_id);

CREATE TABLE IF NOT EXISTS public.audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  action text NOT NULL,
  resource_type text,
  resource_id text,
  organization_id uuid,
  school_id uuid,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_logs_actor_idx ON public.audit_logs(actor_id);
CREATE INDEX IF NOT EXISTS audit_logs_created_idx ON public.audit_logs(created_at DESC);

CREATE OR REPLACE FUNCTION public.is_root()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT COALESCE(
    (SELECT is_platform_admin FROM public.profiles WHERE id = auth.uid()),
    false
  );
$$;

CREATE OR REPLACE FUNCTION public.my_org_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT organization_id FROM public.organization_memberships WHERE profile_id = auth.uid()
  UNION
  SELECT organization_id FROM public.memberships WHERE profile_id = auth.uid()
  UNION
  SELECT id FROM public.organizations WHERE public.is_root();
$$;

CREATE OR REPLACE FUNCTION public.has_org_role(p_organization_id uuid, p_roles text[])
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT public.is_root()
    OR EXISTS (
      SELECT 1 FROM public.organization_memberships om
      WHERE om.profile_id = auth.uid()
        AND om.organization_id = p_organization_id
        AND om.role = ANY (p_roles)
    );
$$;

CREATE OR REPLACE FUNCTION public.is_platform_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT public.is_root();
$$;

REVOKE ALL ON FUNCTION public.is_root() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.my_org_ids() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.has_org_role(uuid, text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_root() TO authenticated;
GRANT EXECUTE ON FUNCTION public.my_org_ids() TO authenticated;
GRANT EXECUTE ON FUNCTION public.has_org_role(uuid, text[]) TO authenticated;

ALTER TABLE public.organization_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_memberships_select ON public.organization_memberships;
CREATE POLICY organization_memberships_select ON public.organization_memberships
  FOR SELECT TO authenticated
  USING (
    public.is_root()
    OR profile_id = auth.uid()
    OR public.has_org_role(organization_id, ARRAY['admin_rede'])
  );

DROP POLICY IF EXISTS organization_memberships_write ON public.organization_memberships;
CREATE POLICY organization_memberships_write ON public.organization_memberships
  FOR ALL TO authenticated
  USING (public.is_root() OR public.has_org_role(organization_id, ARRAY['admin_rede']))
  WITH CHECK (public.is_root() OR public.has_org_role(organization_id, ARRAY['admin_rede']));

DROP POLICY IF EXISTS invites_select ON public.invites;
CREATE POLICY invites_select ON public.invites
  FOR SELECT TO authenticated
  USING (
    public.is_root()
    OR (organization_id IS NOT NULL AND public.has_org_role(organization_id, ARRAY['admin_rede']))
    OR (school_id IS NOT NULL AND public.has_school_role(school_id, ARRAY['gestor']))
  );

DROP POLICY IF EXISTS invites_write ON public.invites;
CREATE POLICY invites_write ON public.invites
  FOR ALL TO authenticated
  USING (
    public.is_root()
    OR (organization_id IS NOT NULL AND public.has_org_role(organization_id, ARRAY['admin_rede']))
    OR (school_id IS NOT NULL AND public.has_school_role(school_id, ARRAY['gestor']))
  )
  WITH CHECK (
    public.is_root()
    OR (organization_id IS NOT NULL AND public.has_org_role(organization_id, ARRAY['admin_rede']))
    OR (school_id IS NOT NULL AND public.has_school_role(school_id, ARRAY['gestor']))
  );

DROP POLICY IF EXISTS audit_logs_select ON public.audit_logs;
CREATE POLICY audit_logs_select ON public.audit_logs
  FOR SELECT TO authenticated
  USING (
    public.is_root()
    OR (organization_id IS NOT NULL AND public.has_org_role(organization_id, ARRAY['admin_rede']))
    OR (school_id IS NOT NULL AND public.has_school_role(school_id, ARRAY['gestor']))
  );

DROP POLICY IF EXISTS audit_logs_insert ON public.audit_logs;
CREATE POLICY audit_logs_insert ON public.audit_logs
  FOR INSERT TO authenticated
  WITH CHECK (actor_id = auth.uid() OR public.is_root());

DROP POLICY IF EXISTS organizations_write_saas ON public.organizations;
CREATE POLICY organizations_write_saas ON public.organizations
  FOR ALL TO authenticated
  USING (public.is_root())
  WITH CHECK (public.is_root());

DROP POLICY IF EXISTS schools_write_saas ON public.schools;
CREATE POLICY schools_write_saas ON public.schools
  FOR ALL TO authenticated
  USING (public.is_root() OR public.has_org_role(organization_id, ARRAY['admin_rede']))
  WITH CHECK (public.is_root() OR public.has_org_role(organization_id, ARRAY['admin_rede']));
