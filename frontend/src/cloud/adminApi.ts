/**
 * Helpers CRUD admin via Supabase (anon + JWT). Sem service_role.
 */
import { supabase } from "./supabaseClient";

export type SchoolRow = {
  id: string;
  organization_id: string;
  name: string;
  external_ref: string | null;
  organizations?: { name: string } | null;
};

export type SubjectRow = {
  id: string;
  school_id: string;
  organization_id: string;
  name: string;
  external_ref: string | null;
  is_active: boolean;
};

export type ClassGroupRow = {
  id: string;
  school_id: string;
  organization_id: string;
  name: string;
  year_label: string | null;
  shift: string | null;
  is_active: boolean;
};

export type StudentRow = {
  id: string;
  school_id: string;
  organization_id: string;
  full_name: string;
  external_ref: string | null;
  is_active: boolean;
};

export type EnrollmentRow = {
  id: string;
  student_id: string;
  class_group_id: string;
  status: string;
  students?: { full_name: string } | null;
  class_groups?: { name: string } | null;
};

export type RoomRow = {
  id: string;
  school_id: string;
  organization_id: string;
  name: string;
  code: string | null;
  description: string | null;
  is_active: boolean;
};

export type DeviceRow = {
  id: string;
  school_id: string;
  organization_id: string;
  room_id: string | null;
  device_code: string;
  display_name: string;
  status: string;
  last_seen_at: string | null;
  app_version: string | null;
  rooms?: { name: string } | null;
};

export type CameraRow = {
  id: string;
  school_id: string;
  organization_id: string;
  room_id: string;
  label: string;
  edge_camera_id: string;
  is_active: boolean;
  rooms?: { name: string } | null;
};

export type TeamMember = {
  id: string;
  role: string;
  profile_id: string;
  profiles?: { full_name: string; email: string | null } | null;
};

function sb() {
  if (!supabase) throw new Error("Supabase não configurado");
  return supabase;
}

export async function fetchSchool(schoolId: string) {
  return sb()
    .from("schools")
    .select("id, organization_id, name, external_ref, organizations(name)")
    .eq("id", schoolId)
    .maybeSingle();
}

export async function updateSchoolName(schoolId: string, name: string) {
  return sb().from("schools").update({ name }).eq("id", schoolId);
}

export async function fetchTeam(schoolId: string) {
  return sb()
    .from("memberships")
    .select("id, role, profile_id, profiles(full_name, email)")
    .eq("school_id", schoolId)
    .order("role");
}

export async function inviteTeamMember(payload: {
  email: string;
  full_name: string;
  role: "professor" | "monitor" | "gestor";
  school_id: string;
  temporary_password: string;
}) {
  const client = sb();
  const { data: session } = await client.auth.getSession();
  const token = session.session?.access_token;
  if (!token) throw new Error("Faça login novamente");
  const base = (import.meta as any).env?.VITE_SUPABASE_URL || "";
  const anon = (import.meta as any).env?.VITE_SUPABASE_ANON_KEY || "";
  const res = await fetch(`${base}/functions/v1/admin-invite-user`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      apikey: anon,
    },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

export async function fetchSubjects(schoolId: string) {
  return sb().from("subjects").select("*").eq("school_id", schoolId).order("name");
}

export async function upsertSubject(row: Partial<SubjectRow> & { school_id: string; organization_id: string; name: string }) {
  if (row.id) return sb().from("subjects").update(row).eq("id", row.id).select().single();
  return sb().from("subjects").insert(row).select().single();
}

export async function fetchClassGroups(schoolId: string) {
  return sb().from("class_groups").select("*").eq("school_id", schoolId).order("name");
}

export async function upsertClassGroup(
  row: Partial<ClassGroupRow> & { school_id: string; organization_id: string; name: string },
) {
  if (row.id) return sb().from("class_groups").update(row).eq("id", row.id).select().single();
  return sb().from("class_groups").insert(row).select().single();
}

export async function fetchStudents(schoolId: string) {
  return sb().from("students").select("*").eq("school_id", schoolId).order("full_name");
}

export async function upsertStudent(
  row: Partial<StudentRow> & { school_id: string; organization_id: string; full_name: string },
) {
  if (row.id) return sb().from("students").update(row).eq("id", row.id).select().single();
  return sb().from("students").insert(row).select().single();
}

export async function fetchEnrollments(schoolId: string, classGroupId?: string) {
  let q = sb()
    .from("enrollments")
    .select("id, student_id, class_group_id, status, students(full_name), class_groups(name)")
    .eq("school_id", schoolId);
  if (classGroupId) q = q.eq("class_group_id", classGroupId);
  return q.order("created_at", { ascending: false });
}

export async function enrollStudent(row: {
  school_id: string;
  organization_id: string;
  student_id: string;
  class_group_id: string;
}) {
  return sb()
    .from("enrollments")
    .insert({ ...row, status: "active" })
    .select()
    .single();
}

export async function setEnrollmentStatus(id: string, status: "active" | "inactive" | "withdrawn") {
  return sb().from("enrollments").update({ status }).eq("id", id);
}

export async function fetchTeacherAssignments(schoolId: string) {
  return sb()
    .from("teacher_assignments")
    .select("id, profile_id, class_group_id, subject_id, is_primary, profiles(full_name), class_groups(name), subjects(name)")
    .eq("school_id", schoolId);
}

export async function assignTeacher(row: {
  school_id: string;
  organization_id: string;
  profile_id: string;
  class_group_id: string;
  subject_id?: string | null;
}) {
  return sb()
    .from("teacher_assignments")
    .insert({ ...row, is_primary: true })
    .select()
    .single();
}

export async function removeTeacherAssignment(id: string) {
  return sb().from("teacher_assignments").delete().eq("id", id);
}

export async function fetchRooms(schoolId: string) {
  return sb().from("rooms").select("*").eq("school_id", schoolId).order("name");
}

export async function upsertRoom(
  row: Partial<RoomRow> & { school_id: string; organization_id: string; name: string },
) {
  if (row.id) return sb().from("rooms").update(row).eq("id", row.id).select().single();
  return sb().from("rooms").insert(row).select().single();
}

export async function fetchDevices(schoolId: string) {
  return sb()
    .from("edge_devices")
    .select("id, school_id, organization_id, room_id, device_code, display_name, status, last_seen_at, app_version, rooms(name)")
    .eq("school_id", schoolId)
    .order("display_name");
}

export async function updateDevice(id: string, patch: { display_name?: string; room_id?: string | null; status?: string }) {
  return sb().from("edge_devices").update(patch).eq("id", id);
}

export async function revokeDeviceCredentials(edgeDeviceId: string) {
  return sb()
    .from("device_credentials")
    .update({ revoked_at: new Date().toISOString() })
    .eq("edge_device_id", edgeDeviceId)
    .is("revoked_at", null);
}

export async function fetchCameras(schoolId: string) {
  return sb()
    .from("cameras")
    .select("id, school_id, organization_id, room_id, label, edge_camera_id, is_active, rooms(name)")
    .eq("school_id", schoolId)
    .order("label");
}

export async function upsertCamera(
  row: Partial<CameraRow> & {
    school_id: string;
    organization_id: string;
    room_id: string;
    label: string;
    edge_camera_id: string;
  },
) {
  if (row.id) return sb().from("cameras").update(row).eq("id", row.id).select().single();
  return sb().from("cameras").insert({ ...row, is_active: row.is_active ?? true }).select().single();
}

/** Turmas do professor autenticado (RLS já filtra). */
export async function fetchMyClassGroups() {
  return sb().from("class_groups").select("*").order("name");
}
