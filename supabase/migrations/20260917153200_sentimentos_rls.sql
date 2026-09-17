-- Sentimentos v1 — RLS policies (default deny)

ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schools ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.class_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.teacher_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cameras ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.edge_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.class_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.session_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.session_report_snapshots ENABLE ROW LEVEL SECURITY;

-- profiles
CREATE POLICY profiles_select_self_or_school ON public.profiles
  FOR SELECT TO authenticated
  USING (
    id = auth.uid()
    OR public.is_platform_admin()
    OR EXISTS (
      SELECT 1 FROM public.memberships m1
      JOIN public.memberships m2 ON m1.school_id = m2.school_id
      WHERE m1.profile_id = auth.uid() AND m2.profile_id = profiles.id
    )
  );
CREATE POLICY profiles_update_self ON public.profiles
  FOR UPDATE TO authenticated
  USING (id = auth.uid() OR public.is_platform_admin())
  WITH CHECK (id = auth.uid() OR public.is_platform_admin());

-- organizations
CREATE POLICY organizations_select ON public.organizations
  FOR SELECT TO authenticated
  USING (
    public.is_platform_admin()
    OR EXISTS (
      SELECT 1 FROM public.memberships m
      WHERE m.profile_id = auth.uid() AND m.organization_id = organizations.id
    )
  );
CREATE POLICY organizations_admin_write ON public.organizations
  FOR ALL TO authenticated
  USING (public.is_platform_admin())
  WITH CHECK (public.is_platform_admin());

-- schools
CREATE POLICY schools_select ON public.schools
  FOR SELECT TO authenticated
  USING (id IN (SELECT public.my_school_ids()));
CREATE POLICY schools_gestor_write ON public.schools
  FOR ALL TO authenticated
  USING (public.has_school_role(id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(id, ARRAY['gestor']) OR public.is_platform_admin());

-- memberships
CREATE POLICY memberships_select ON public.memberships
  FOR SELECT TO authenticated
  USING (
    profile_id = auth.uid()
    OR public.has_school_role(school_id, ARRAY['gestor'])
    OR public.is_platform_admin()
  );
CREATE POLICY memberships_gestor_write ON public.memberships
  FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

-- generic school-scoped pedagogical tables
CREATE POLICY subjects_select ON public.subjects FOR SELECT TO authenticated
  USING (school_id IN (SELECT public.my_school_ids()));
CREATE POLICY subjects_write ON public.subjects FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

CREATE POLICY class_groups_select ON public.class_groups FOR SELECT TO authenticated
  USING (
    school_id IN (SELECT public.my_school_ids())
    AND (
      public.has_school_role(school_id, ARRAY['gestor','monitor'])
      OR public.is_platform_admin()
      OR id IN (SELECT public.my_teacher_class_group_ids())
    )
  );
CREATE POLICY class_groups_write ON public.class_groups FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

CREATE POLICY students_select ON public.students FOR SELECT TO authenticated
  USING (
    school_id IN (SELECT public.my_school_ids())
    AND (
      public.has_school_role(school_id, ARRAY['gestor','monitor'])
      OR public.is_platform_admin()
      OR EXISTS (
        SELECT 1 FROM public.enrollments e
        WHERE e.student_id = students.id
          AND e.class_group_id IN (SELECT public.my_teacher_class_group_ids())
      )
    )
  );
CREATE POLICY students_write ON public.students FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

CREATE POLICY enrollments_select ON public.enrollments FOR SELECT TO authenticated
  USING (
    school_id IN (SELECT public.my_school_ids())
    AND (
      public.has_school_role(school_id, ARRAY['gestor','monitor'])
      OR public.is_platform_admin()
      OR class_group_id IN (SELECT public.my_teacher_class_group_ids())
    )
  );
CREATE POLICY enrollments_write ON public.enrollments FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

CREATE POLICY teacher_assignments_select ON public.teacher_assignments FOR SELECT TO authenticated
  USING (
    profile_id = auth.uid()
    OR public.has_school_role(school_id, ARRAY['gestor','monitor'])
    OR public.is_platform_admin()
  );
CREATE POLICY teacher_assignments_write ON public.teacher_assignments FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

CREATE POLICY rooms_select ON public.rooms FOR SELECT TO authenticated
  USING (school_id IN (SELECT public.my_school_ids()));
CREATE POLICY rooms_write ON public.rooms FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

CREATE POLICY cameras_select ON public.cameras FOR SELECT TO authenticated
  USING (school_id IN (SELECT public.my_school_ids()));
CREATE POLICY cameras_write ON public.cameras FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

CREATE POLICY edge_devices_select ON public.edge_devices FOR SELECT TO authenticated
  USING (school_id IN (SELECT public.my_school_ids()));
CREATE POLICY edge_devices_write ON public.edge_devices FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

-- credentials: gestor can manage; never expose to professor/monitor select of hashes? gestor needs to create.
CREATE POLICY device_credentials_select ON public.device_credentials FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.edge_devices d
      WHERE d.id = device_credentials.edge_device_id
        AND public.has_school_role(d.school_id, ARRAY['gestor'])
    )
    OR public.is_platform_admin()
  );
CREATE POLICY device_credentials_write ON public.device_credentials FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.edge_devices d
      WHERE d.id = device_credentials.edge_device_id
        AND public.has_school_role(d.school_id, ARRAY['gestor'])
    )
    OR public.is_platform_admin()
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.edge_devices d
      WHERE d.id = device_credentials.edge_device_id
        AND public.has_school_role(d.school_id, ARRAY['gestor'])
    )
    OR public.is_platform_admin()
  );

-- sessions / events / snapshots
CREATE POLICY class_sessions_select ON public.class_sessions FOR SELECT TO authenticated
  USING (
    school_id IN (SELECT public.my_school_ids())
    AND (
      public.has_school_role(school_id, ARRAY['gestor','monitor'])
      OR public.is_platform_admin()
      OR class_group_id IN (SELECT public.my_teacher_class_group_ids())
      OR teacher_profile_id = auth.uid()
    )
  );
CREATE POLICY class_sessions_write ON public.class_sessions FOR ALL TO authenticated
  USING (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin())
  WITH CHECK (public.has_school_role(school_id, ARRAY['gestor']) OR public.is_platform_admin());

CREATE POLICY session_events_select ON public.session_events FOR SELECT TO authenticated
  USING (
    school_id IN (SELECT public.my_school_ids())
    AND (
      public.has_school_role(school_id, ARRAY['gestor','monitor'])
      OR public.is_platform_admin()
      OR EXISTS (
        SELECT 1 FROM public.class_sessions s
        WHERE s.id = session_events.session_id
          AND (
            s.class_group_id IN (SELECT public.my_teacher_class_group_ids())
            OR s.teacher_profile_id = auth.uid()
          )
      )
    )
  );
CREATE POLICY session_events_review_update ON public.session_events FOR UPDATE TO authenticated
  USING (
    public.has_school_role(school_id, ARRAY['gestor'])
    OR public.is_platform_admin()
    OR EXISTS (
      SELECT 1 FROM public.class_sessions s
      WHERE s.id = session_events.session_id
        AND (
          s.class_group_id IN (SELECT public.my_teacher_class_group_ids())
          OR s.teacher_profile_id = auth.uid()
        )
    )
  )
  WITH CHECK (
    public.has_school_role(school_id, ARRAY['gestor'])
    OR public.is_platform_admin()
    OR EXISTS (
      SELECT 1 FROM public.class_sessions s
      WHERE s.id = session_events.session_id
        AND (
          s.class_group_id IN (SELECT public.my_teacher_class_group_ids())
          OR s.teacher_profile_id = auth.uid()
        )
    )
  );

CREATE POLICY session_report_snapshots_select ON public.session_report_snapshots FOR SELECT TO authenticated
  USING (
    school_id IN (SELECT public.my_school_ids())
    AND (
      public.has_school_role(school_id, ARRAY['gestor','monitor'])
      OR public.is_platform_admin()
      OR EXISTS (
        SELECT 1 FROM public.class_sessions s
        WHERE s.id = session_report_snapshots.session_id
          AND (
            s.class_group_id IN (SELECT public.my_teacher_class_group_ids())
            OR s.teacher_profile_id = auth.uid()
          )
      )
    )
  );
