-- Auto edge_student_key: derive from students.id, backfill, never overwrite existing keys.
-- Matcher forbids raw UUID as student_id; prefix e_ keeps the contract.

CREATE OR REPLACE FUNCTION public.derive_edge_student_key(p_id uuid)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT 'e_' || replace(lower(p_id::text), '-', '');
$$;

CREATE OR REPLACE FUNCTION public.students_ensure_edge_student_key()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.id IS NULL THEN
    RAISE EXCEPTION 'students.id is required to derive edge_student_key';
  END IF;

  IF NEW.edge_student_key IS NULL OR btrim(NEW.edge_student_key) = '' THEN
    NEW.edge_student_key := public.derive_edge_student_key(NEW.id);
  ELSIF NEW.edge_student_key ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
    RAISE EXCEPTION 'edge_student_key cannot be a UUID (matcher identity contract)';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_students_ensure_edge_student_key ON public.students;

CREATE TRIGGER trg_students_ensure_edge_student_key
BEFORE INSERT OR UPDATE ON public.students
FOR EACH ROW
EXECUTE FUNCTION public.students_ensure_edge_student_key();

-- Backfill existing rows without a key (do not touch non-empty keys like p01).
UPDATE public.students
SET edge_student_key = public.derive_edge_student_key(id)
WHERE edge_student_key IS NULL
   OR btrim(edge_student_key) = '';

COMMENT ON FUNCTION public.derive_edge_student_key(uuid) IS
  'Stable non-UUID matcher key: e_<students.id hex without hyphens>';
COMMENT ON FUNCTION public.students_ensure_edge_student_key() IS
  'Auto-fill students.edge_student_key on insert/update when empty; reject UUID keys';
