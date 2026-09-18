/**
 * Fase 6 — aulas planejadas (Supabase) + push de contexto ao Edge.
 * localStorage NÃO é fonte de verdade.
 */
import { supabase } from "./supabaseClient";

function sb() {
  if (!supabase) throw new Error("Supabase não configurado");
  return supabase;
}

function edgeHeaders(): HeadersInit {
  const token = localStorage.getItem("api_token") || "";
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h["X-API-Token"] = token;
  return h;
}

export type LessonOccurrenceRow = {
  id: string;
  organization_id: string;
  school_id: string;
  class_group_id: string;
  subject_id: string;
  teacher_profile_id: string;
  room_id: string | null;
  title: string | null;
  scheduled_start_at: string;
  scheduled_duration_minutes: number;
  external_lesson_id: string | null;
  block_group_id: string | null;
  status: string;
  class_groups?: { name: string; year_label?: string | null } | null;
  subjects?: { name: string } | null;
  rooms?: { name: string; code?: string | null } | null;
  profiles?: { full_name: string } | null;
};

export async function fetchLessonOccurrences(schoolId: string, dayIso?: string) {
  let q = sb()
    .from("lesson_occurrences")
    .select(
      "id, organization_id, school_id, class_group_id, subject_id, teacher_profile_id, room_id, title, scheduled_start_at, scheduled_duration_minutes, external_lesson_id, block_group_id, status, class_groups(name, year_label), subjects(name), rooms(name, code), profiles(full_name)",
    )
    .eq("school_id", schoolId)
    .order("scheduled_start_at");
  if (dayIso) {
    const start = `${dayIso}T00:00:00.000Z`;
    const end = `${dayIso}T23:59:59.999Z`;
    q = q.gte("scheduled_start_at", start).lte("scheduled_start_at", end);
  }
  return q;
}

/** Aulas do professor autenticado no dia (RLS filtra). */
export async function fetchMyLessonsToday(dayIso: string) {
  const start = `${dayIso}T00:00:00.000Z`;
  const end = `${dayIso}T23:59:59.999Z`;
  return sb()
    .from("lesson_occurrences")
    .select(
      "id, organization_id, school_id, class_group_id, subject_id, teacher_profile_id, room_id, title, scheduled_start_at, scheduled_duration_minutes, external_lesson_id, block_group_id, status, class_groups(name, year_label), subjects(name), rooms(name, code), profiles(full_name)",
    )
    .gte("scheduled_start_at", start)
    .lte("scheduled_start_at", end)
    .order("scheduled_start_at");
}

export async function createLessonOccurrence(row: {
  organization_id: string;
  school_id: string;
  class_group_id: string;
  subject_id: string;
  teacher_profile_id: string;
  room_id?: string | null;
  title?: string | null;
  scheduled_start_at: string;
  scheduled_duration_minutes: number;
  external_lesson_id?: string | null;
}) {
  return sb()
    .from("lesson_occurrences")
    .insert({
      ...row,
      status: "scheduled",
      block_group_id: null,
    })
    .select()
    .single();
}

export async function updateLessonOccurrence(
  id: string,
  patch: Partial<{
    scheduled_start_at: string;
    scheduled_duration_minutes: number;
    external_lesson_id: string | null;
    room_id: string | null;
    title: string | null;
    status: string;
    teacher_profile_id: string;
    subject_id: string;
    class_group_id: string;
  }>,
) {
  return sb().from("lesson_occurrences").update(patch).eq("id", id).select().single();
}

export async function fetchRosterForClassGroup(classGroupId: string) {
  return sb()
    .from("enrollments")
    .select("student_id, status, students(id, full_name, edge_student_key, external_ref, is_active)")
    .eq("class_group_id", classGroupId)
    .eq("status", "active");
}

export function buildEdgeContextPayload(
  occ: LessonOccurrenceRow,
  rosterRows: Array<{
    students?: {
      edge_student_key?: string | null;
      external_ref?: string | null;
      full_name?: string;
      id?: string;
    } | null;
  }>,
) {
  const roster = (rosterRows || [])
    .map((e) => {
      const s = e.students;
      if (!s) return null;
      return {
        student_id: s.id,
        full_name: s.full_name,
        edge_student_key: s.edge_student_key || null,
        external_ref: s.external_ref || null,
      };
    })
    .filter(Boolean);

  return {
    lesson_occurrence_id: occ.id,
    organization_id: occ.organization_id,
    school_id: occ.school_id,
    class_group_id: occ.class_group_id,
    subject_id: occ.subject_id,
    teacher_profile_id: occ.teacher_profile_id,
    room_id: occ.room_id,
    class_group_name: occ.class_groups?.name || null,
    subject_name: occ.subjects?.name || null,
    teacher_name: occ.profiles?.full_name || null,
    room_name: occ.rooms?.name || null,
    title:
      occ.title ||
      [occ.class_groups?.name, occ.subjects?.name].filter(Boolean).join(" · ") ||
      null,
    scheduled_start_at: occ.scheduled_start_at,
    scheduled_duration_minutes: occ.scheduled_duration_minutes,
    external_lesson_id: occ.external_lesson_id,
    block_group_id: occ.block_group_id,
    roster,
  };
}

export async function pushLessonsCacheToEdge(occurrences: unknown[]) {
  const r = await fetch("/api/v1/lessons/cache", {
    method: "POST",
    headers: edgeHeaders(),
    body: JSON.stringify({ occurrences }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.message || data?.error || `${r.status}`);
  return data;
}

export async function startLessonOnEdge(payload: Record<string, unknown>) {
  const r = await fetch("/api/v1/sessions/start-with-context", {
    method: "POST",
    headers: edgeHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, data };
}

export async function endLessonOnEdge(sessionId: string) {
  const r = await fetch(`/sessions/${sessionId}/end`, {
    method: "POST",
    headers: edgeHeaders(),
  });
  const data = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, data };
}

export async function fetchEdgeCurrentContext() {
  const r = await fetch("/api/v1/sessions/current-context", { headers: edgeHeaders() });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

export function localDayIso(d = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
