-- Fase 6 — Aula planejada (lesson_occurrences) + vínculo na sessão real
-- TRI intocado. RLS por escola. Gestor escreve; professor lê as suas.

-- Garantir coluna external_lesson_id em class_sessions (pode já existir em ambientes homologados)
ALTER TABLE public.class_sessions
  ADD COLUMN IF NOT EXISTS external_lesson_id text;
CREATE INDEX IF NOT EXISTS class_sessions_external_lesson_id_idx
  ON public.class_sessions(external_lesson_id);

CREATE TABLE IF NOT EXISTS public.lesson_occurrences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  class_group_id uuid NOT NULL REFERENCES public.class_groups(id) ON DELETE CASCADE,
  subject_id uuid NOT NULL REFERENCES public.subjects(id) ON DELETE RESTRICT,
  teacher_profile_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
  room_id uuid REFERENCES public.rooms(id) ON DELETE SET NULL,
  title text,
  scheduled_start_at timestamptz NOT NULL,
  scheduled_duration_minutes integer NOT NULL
    CHECK (scheduled_duration_minutes > 0 AND scheduled_duration_minutes <= 480),
  external_lesson_id text,
  -- Preparação futura (100 min = 2×50); MVP não usa
  block_group_id uuid,
  status text NOT NULL DEFAULT 'scheduled'
    CHECK (status IN ('scheduled', 'in_progress', 'completed', 'cancelled')),
  -- Reserva futura (neurodivergência / perfil de observação) — sem efeito no TRI
  observation_profile_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX lesson_occurrences_school_day_idx
  ON public.lesson_occurrences(school_id, scheduled_start_at);
CREATE INDEX lesson_occurrences_teacher_day_idx
  ON public.lesson_occurrences(teacher_profile_id, scheduled_start_at);
CREATE INDEX lesson_occurrences_class_group_idx
  ON public.lesson_occurrences(class_group_id);
CREATE INDEX lesson_occurrences_external_lesson_idx
  ON public.lesson_occurrences(external_lesson_id)
  WHERE external_lesson_id IS NOT NULL;
CREATE INDEX lesson_occurrences_block_group_idx
  ON public.lesson_occurrences(block_group_id)
  WHERE block_group_id IS NOT NULL;

DROP TRIGGER IF EXISTS lesson_occurrences_set_updated_at ON public.lesson_occurrences;
CREATE TRIGGER lesson_occurrences_set_updated_at
  BEFORE UPDATE ON public.lesson_occurrences
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.class_sessions
  ADD COLUMN IF NOT EXISTS lesson_occurrence_id uuid
    REFERENCES public.lesson_occurrences(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS class_sessions_lesson_occurrence_id_idx
  ON public.class_sessions(lesson_occurrence_id);

ALTER TABLE public.lesson_occurrences ENABLE ROW LEVEL SECURITY;

-- SELECT: gestor/monitor da escola; professor só das suas turmas/atribuições
CREATE POLICY lesson_occurrences_select ON public.lesson_occurrences
  FOR SELECT TO authenticated
  USING (
    school_id IN (SELECT public.my_school_ids())
    AND (
      public.has_school_role(school_id, ARRAY['gestor', 'monitor'])
      OR public.is_platform_admin()
      OR teacher_profile_id = auth.uid()
      OR class_group_id IN (SELECT public.my_teacher_class_group_ids())
    )
  );

-- WRITE: somente gestor (ou platform admin)
CREATE POLICY lesson_occurrences_gestor_write ON public.lesson_occurrences
  FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

COMMENT ON TABLE public.lesson_occurrences IS
  'Fase 6: aula planejada. Distinta de class_sessions (execução real).';
COMMENT ON COLUMN public.lesson_occurrences.block_group_id IS
  'Reserva futura para agrupar blocos 50+50; MVP = NULL.';
COMMENT ON COLUMN public.lesson_occurrences.observation_profile_id IS
  'Reserva futura (neurodivergência); não altera TRI.';

-- Professor pode atualizar status da própria ocorrência (iniciar/encerrar)
DROP POLICY IF EXISTS lesson_occurrences_teacher_status ON public.lesson_occurrences;
CREATE POLICY lesson_occurrences_teacher_status ON public.lesson_occurrences
  FOR UPDATE TO authenticated
  USING (
    teacher_profile_id = auth.uid()
    OR public.has_school_role(school_id, ARRAY['gestor'])
    OR public.is_platform_admin()
  )
  WITH CHECK (
    teacher_profile_id = auth.uid()
    OR public.has_school_role(school_id, ARRAY['gestor'])
    OR public.is_platform_admin()
  );
