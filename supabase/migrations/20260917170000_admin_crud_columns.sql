-- Admin CRUD MVP: campos UX mínimos sem quebrar schema existente
ALTER TABLE public.subjects
  ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

ALTER TABLE public.class_groups
  ADD COLUMN IF NOT EXISTS shift text;

ALTER TABLE public.rooms
  ADD COLUMN IF NOT EXISTS description text,
  ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;
