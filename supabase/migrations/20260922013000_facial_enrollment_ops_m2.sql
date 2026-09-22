-- M2 facial enrollment operational state on Supabase A (presence).
-- No biometrics / embeddings. Templates remain TEMP/local on Edge M2.

CREATE TABLE IF NOT EXISTS public.facial_enrollment_campaigns (
  id text PRIMARY KEY,
  organization_id uuid REFERENCES public.organizations(id) ON DELETE SET NULL,
  school_id text NOT NULL,
  school_name text NOT NULL,
  class_group_id text NOT NULL,
  class_label text NOT NULL,
  campaign_token_hash text NOT NULL UNIQUE,
  status text NOT NULL CHECK (status IN ('active', 'expired', 'revoked')),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.facial_enrollment_roster (
  id text PRIMARY KEY,
  campaign_id text NOT NULL REFERENCES public.facial_enrollment_campaigns(id) ON DELETE CASCADE,
  student_id uuid REFERENCES public.students(id) ON DELETE SET NULL,
  fixture_key text,
  display_name text NOT NULL,
  claim_code text NOT NULL,
  status text NOT NULL CHECK (status IN ('pending', 'claimed', 'in_progress', 'completed', 'failed', 'expired')),
  session_id text,
  claimed_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (campaign_id, claim_code)
);

CREATE TABLE IF NOT EXISTS public.facial_enrollment_sessions (
  id text PRIMARY KEY,
  campaign_id text NOT NULL REFERENCES public.facial_enrollment_campaigns(id) ON DELETE CASCADE,
  roster_id text NOT NULL REFERENCES public.facial_enrollment_roster(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,
  status text NOT NULL,
  expires_at timestamptz NOT NULL,
  consent_ok boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS facial_enroll_campaigns_school_idx
  ON public.facial_enrollment_campaigns(school_id, status);
CREATE INDEX IF NOT EXISTS facial_enroll_roster_campaign_status_idx
  ON public.facial_enrollment_roster(campaign_id, status);
CREATE INDEX IF NOT EXISTS facial_enroll_sessions_roster_idx
  ON public.facial_enrollment_sessions(roster_id);

ALTER TABLE public.facial_enrollment_campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.facial_enrollment_roster ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.facial_enrollment_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS facial_enroll_campaigns_select ON public.facial_enrollment_campaigns;
CREATE POLICY facial_enroll_campaigns_select ON public.facial_enrollment_campaigns
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.memberships m
      WHERE m.profile_id = auth.uid()
        AND m.role = 'gestor'
        AND (
          m.school_id::text = facial_enrollment_campaigns.school_id
          OR EXISTS (
            SELECT 1 FROM public.schools s
            WHERE s.id = m.school_id
              AND (s.id::text = facial_enrollment_campaigns.school_id
                   OR s.name = facial_enrollment_campaigns.school_name)
          )
        )
    )
  );

DROP POLICY IF EXISTS facial_enroll_roster_select ON public.facial_enrollment_roster;
CREATE POLICY facial_enroll_roster_select ON public.facial_enrollment_roster
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.facial_enrollment_campaigns c
      JOIN public.memberships m ON m.profile_id = auth.uid() AND m.role = 'gestor'
      WHERE c.id = facial_enrollment_roster.campaign_id
        AND (
          m.school_id::text = c.school_id
          OR EXISTS (
            SELECT 1 FROM public.schools s
            WHERE s.id = m.school_id
              AND (s.id::text = c.school_id OR s.name = c.school_name)
          )
        )
    )
  );

DROP POLICY IF EXISTS facial_enroll_sessions_select ON public.facial_enrollment_sessions;
CREATE POLICY facial_enroll_sessions_select ON public.facial_enrollment_sessions
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.facial_enrollment_campaigns c
      JOIN public.memberships m ON m.profile_id = auth.uid() AND m.role = 'gestor'
      WHERE c.id = facial_enrollment_sessions.campaign_id
        AND (
          m.school_id::text = c.school_id
          OR EXISTS (
            SELECT 1 FROM public.schools s
            WHERE s.id = m.school_id
              AND (s.id::text = c.school_id OR s.name = c.school_name)
          )
        )
    )
  );
