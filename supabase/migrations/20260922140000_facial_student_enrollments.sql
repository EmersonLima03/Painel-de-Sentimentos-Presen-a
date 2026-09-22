-- Product facial enrollment status per official student (Supabase A).
-- No biometrics. Templates remain on Edge face_embeddings / FAISS.
-- Keeps facial_enrollment_campaigns/roster/sessions for internal compat.

CREATE TABLE IF NOT EXISTS public.facial_student_enrollments (
  student_id uuid PRIMARY KEY REFERENCES public.students(id) ON DELETE CASCADE,
  edge_student_key text,
  status text NOT NULL CHECK (
    status IN ('not_enrolled', 'in_progress', 'enrolled', 'expired', 'revoked', 'failed')
  ),
  version integer NOT NULL DEFAULT 1,
  completed_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS facial_student_enrollments_status_idx
  ON public.facial_student_enrollments(status);
CREATE INDEX IF NOT EXISTS facial_student_enrollments_edge_key_idx
  ON public.facial_student_enrollments(edge_student_key)
  WHERE edge_student_key IS NOT NULL;

ALTER TABLE public.facial_student_enrollments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS facial_student_enrollments_select ON public.facial_student_enrollments;
CREATE POLICY facial_student_enrollments_select ON public.facial_student_enrollments
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.students s
      JOIN public.memberships m ON m.profile_id = auth.uid() AND m.role = 'gestor'
      WHERE s.id = facial_student_enrollments.student_id
        AND (
          m.school_id = s.school_id
          OR m.organization_id = s.organization_id
        )
    )
  );

COMMENT ON TABLE public.facial_student_enrollments IS
  'Product facial enrollment status keyed by official students.id. No embeddings.';
