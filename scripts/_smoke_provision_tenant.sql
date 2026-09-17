-- Smoke provision: school B, room, pedagogical context, device, memberships
-- IDs alinhados a .env.smoke.local (sem tokens plaintext)

INSERT INTO public.schools (id, organization_id, name)
VALUES (
  '33333333-3333-3333-3333-333333333333',
  '11111111-1111-1111-1111-111111111111',
  'Escola B Isolamento RLS'
)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO public.rooms (id, organization_id, school_id, name)
VALUES (
  'dbaf17f0-ddd4-4243-8625-e89fab7bf166',
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222222',
  'Sala Demo 1'
)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO public.subjects (id, organization_id, school_id, name)
VALUES (
  'e098ad11-9061-44f6-9e26-31625a3e3833',
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222222',
  'Matemática Demo'
)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO public.class_groups (id, organization_id, school_id, name)
VALUES (
  '3f4b690c-d809-4dbb-a471-f5b93db84e1e',
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222222',
  'Turma Demo 7A'
)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

-- class group only in school A for professor isolation tests
INSERT INTO public.class_groups (id, organization_id, school_id, name)
VALUES (
  '44444444-4444-4444-4444-444444444444',
  '11111111-1111-1111-1111-111111111111',
  '33333333-3333-3333-3333-333333333333',
  'Turma Escola B (não atribuída)'
)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO public.edge_devices (
  id, organization_id, school_id, room_id, device_code, display_name, status
) VALUES (
  '4e4f3854-d6fc-452e-8a24-eaec74594875',
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222222',
  'dbaf17f0-ddd4-4243-8625-e89fab7bf166',
  'edge-demo-001',
  'Edge Demo Sala 1',
  'offline'
)
ON CONFLICT (device_code) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  room_id = EXCLUDED.room_id,
  school_id = EXCLUDED.school_id;

-- token hash only (from local smoke env)
INSERT INTO public.device_credentials (edge_device_id, token_hash, label)
SELECT d.id, 'f46d8e498eb37afd6b9ceecfd56481943bb479b88ba8de9424747076cd413f0f', 'smoke-default'
FROM public.edge_devices d
WHERE d.device_code = 'edge-demo-001'
  AND NOT EXISTS (
    SELECT 1 FROM public.device_credentials c
    WHERE c.edge_device_id = d.id
      AND c.token_hash = 'f46d8e498eb37afd6b9ceecfd56481943bb479b88ba8de9424747076cd413f0f'
      AND c.revoked_at IS NULL
  );

-- memberships (profiles created by trigger)
INSERT INTO public.memberships (profile_id, organization_id, school_id, role)
VALUES
  ('daa9da7c-44dc-5662-af74-1fb6428a176e', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'gestor'),
  ('994126e2-f0b7-544e-867e-0f580f256f8e', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'professor'),
  ('ef884275-5020-58b3-99f9-69ec9d412939', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'monitor')
ON CONFLICT DO NOTHING;

INSERT INTO public.teacher_assignments (profile_id, class_group_id, school_id, organization_id)
VALUES (
  '994126e2-f0b7-544e-867e-0f580f256f8e',
  '3f4b690c-d809-4dbb-a471-f5b93db84e1e',
  '22222222-2222-2222-2222-222222222222',
  '11111111-1111-1111-1111-111111111111'
)
ON CONFLICT DO NOTHING;
