-- Sentimentos v1 — core schema (produto)
-- Edge owns class_sessions.id and session_events.id (UUID upsert).
-- No biometrics, no video, no cloud outbox.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- helpers
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE public.organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  slug text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.schools (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  external_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX schools_organization_id_idx ON public.schools(organization_id);
CREATE UNIQUE INDEX schools_org_external_ref_uidx
  ON public.schools(organization_id, external_ref)
  WHERE external_ref IS NOT NULL;

CREATE TABLE public.profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name text NOT NULL DEFAULT '',
  email text,
  is_platform_admin boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('gestor', 'professor', 'monitor')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (profile_id, school_id)
);
CREATE INDEX memberships_school_id_idx ON public.memberships(school_id);
CREATE INDEX memberships_profile_id_idx ON public.memberships(profile_id);

CREATE TABLE public.subjects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  name text NOT NULL,
  external_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX subjects_school_id_idx ON public.subjects(school_id);

CREATE TABLE public.class_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  name text NOT NULL,
  year_label text,
  external_ref text,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX class_groups_school_id_idx ON public.class_groups(school_id);

CREATE TABLE public.students (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  full_name text NOT NULL,
  external_ref text,
  edge_student_key text,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX students_school_id_idx ON public.students(school_id);
CREATE UNIQUE INDEX students_school_edge_key_uidx
  ON public.students(school_id, edge_student_key)
  WHERE edge_student_key IS NOT NULL;

CREATE TABLE public.enrollments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  class_group_id uuid NOT NULL REFERENCES public.class_groups(id) ON DELETE CASCADE,
  student_id uuid NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (class_group_id, student_id)
);
CREATE INDEX enrollments_student_id_idx ON public.enrollments(student_id);

CREATE TABLE public.teacher_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  class_group_id uuid NOT NULL REFERENCES public.class_groups(id) ON DELETE CASCADE,
  profile_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  subject_id uuid REFERENCES public.subjects(id) ON DELETE SET NULL,
  is_primary boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (class_group_id, profile_id, subject_id)
);
CREATE INDEX teacher_assignments_profile_id_idx ON public.teacher_assignments(profile_id);

CREATE TABLE public.rooms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  name text NOT NULL,
  code text,
  external_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX rooms_school_id_idx ON public.rooms(school_id);

CREATE TABLE public.cameras (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  room_id uuid NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
  label text NOT NULL,
  edge_camera_id text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (school_id, edge_camera_id)
);
CREATE INDEX cameras_room_id_idx ON public.cameras(room_id);

CREATE TABLE public.edge_devices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  room_id uuid REFERENCES public.rooms(id) ON DELETE SET NULL,
  device_code text NOT NULL UNIQUE,
  display_name text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'unknown' CHECK (status IN ('online', 'offline', 'unknown')),
  last_seen_at timestamptz,
  app_version text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX edge_devices_school_id_idx ON public.edge_devices(school_id);

CREATE TABLE public.device_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  edge_device_id uuid NOT NULL REFERENCES public.edge_devices(id) ON DELETE CASCADE,
  token_hash text NOT NULL,
  label text NOT NULL DEFAULT 'default',
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX device_credentials_device_id_idx ON public.device_credentials(edge_device_id);
CREATE UNIQUE INDEX device_credentials_active_hash_uidx
  ON public.device_credentials(token_hash)
  WHERE revoked_at IS NULL;

-- PK = Edge session UUID (no cloud-generated replacement)
CREATE TABLE public.class_sessions (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  room_id uuid REFERENCES public.rooms(id) ON DELETE SET NULL,
  edge_device_id uuid REFERENCES public.edge_devices(id) ON DELETE SET NULL,
  class_group_id uuid REFERENCES public.class_groups(id) ON DELETE SET NULL,
  subject_id uuid REFERENCES public.subjects(id) ON DELETE SET NULL,
  teacher_profile_id uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  title text,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended', 'abandoned')),
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  scheduled_start_at timestamptz,
  scheduled_duration_minutes integer,
  source_device_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  synced_at timestamptz
);
CREATE INDEX class_sessions_school_started_idx ON public.class_sessions(school_id, started_at DESC);
CREATE INDEX class_sessions_device_status_idx ON public.class_sessions(edge_device_id, status);
CREATE INDEX class_sessions_class_group_idx ON public.class_sessions(class_group_id, started_at DESC);

CREATE TABLE public.session_events (
  id uuid PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES public.class_sessions(id) ON DELETE CASCADE,
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  device_id text NOT NULL,
  edge_camera_id text,
  student_id uuid REFERENCES public.students(id) ON DELETE SET NULL,
  anonymous_track_id text,
  event_type text NOT NULL,
  opened_at timestamptz NOT NULL,
  closed_at timestamptz,
  duration_seconds double precision,
  confidence double precision,
  observation_quality text,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  review_status text NOT NULL DEFAULT 'none'
    CHECK (review_status IN ('none', 'pending_review', 'confirmed', 'rejected')),
  reviewed_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  reviewed_at timestamptz,
  review_notes text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  synced_at timestamptz
);
CREATE INDEX session_events_session_opened_idx ON public.session_events(session_id, opened_at);
CREATE INDEX session_events_school_type_idx ON public.session_events(school_id, event_type, opened_at DESC);

CREATE TABLE public.session_report_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES public.class_sessions(id) ON DELETE CASCADE,
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  schema_version integer NOT NULL DEFAULT 1,
  captured_at timestamptz NOT NULL,
  report jsonb NOT NULL,
  source_device_id text NOT NULL,
  is_final boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  synced_at timestamptz,
  UNIQUE (session_id, captured_at)
);
CREATE INDEX session_report_snapshots_session_idx
  ON public.session_report_snapshots(session_id, captured_at DESC);

-- updated_at triggers
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'organizations','schools','profiles','subjects','class_groups','students',
    'enrollments','rooms','cameras','edge_devices','class_sessions','session_events'
  ]
  LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON public.%I
       FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()', t, t);
  END LOOP;
END $$;

-- profile bootstrap on auth signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (id, full_name, email)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1), ''),
    NEW.email
  )
  ON CONFLICT (id) DO UPDATE
    SET email = EXCLUDED.email,
        updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- RLS helper functions (security definer, locked search_path)
CREATE OR REPLACE FUNCTION public.is_platform_admin()
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

CREATE OR REPLACE FUNCTION public.has_school_role(p_school_id uuid, p_roles text[])
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT public.is_platform_admin()
    OR EXISTS (
      SELECT 1 FROM public.memberships m
      WHERE m.profile_id = auth.uid()
        AND m.school_id = p_school_id
        AND m.role = ANY (p_roles)
    );
$$;

CREATE OR REPLACE FUNCTION public.my_school_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT school_id FROM public.memberships WHERE profile_id = auth.uid()
  UNION
  SELECT s.id FROM public.schools s WHERE public.is_platform_admin();
$$;

CREATE OR REPLACE FUNCTION public.my_teacher_class_group_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT class_group_id FROM public.teacher_assignments
  WHERE profile_id = auth.uid();
$$;

REVOKE ALL ON FUNCTION public.is_platform_admin() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.has_school_role(uuid, text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.my_school_ids() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.my_teacher_class_group_ids() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_platform_admin() TO authenticated;
GRANT EXECUTE ON FUNCTION public.has_school_role(uuid, text[]) TO authenticated;
GRANT EXECUTE ON FUNCTION public.my_school_ids() TO authenticated;
GRANT EXECUTE ON FUNCTION public.my_teacher_class_group_ids() TO authenticated;
