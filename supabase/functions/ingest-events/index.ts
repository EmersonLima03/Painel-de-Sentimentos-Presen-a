// Sentimentos ingest — device token auth, idempotent UPSERT
// verify_jwt=false: device uses ?token= + anon key gateway

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.1";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-device-token",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function hasForbiddenPayload(obj: unknown): boolean {
  const s = JSON.stringify(obj || {}).toLowerCase();
  return (
    s.includes("embedding") ||
    s.includes("face_template") ||
    s.includes("frame_jpeg") ||
    s.includes("video_base64") ||
    s.includes("rtsp_url")
  );
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  try {
    const url = new URL(req.url);
    const token =
      url.searchParams.get("token") ||
      req.headers.get("x-device-token") ||
      "";
    if (!token) return json({ ok: false, status: "unauthorized", error: "missing_token" }, 401);

    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
    if (!supabaseUrl || !serviceKey) {
      return json({ ok: false, status: "retryable_error", error: "server_misconfigured" }, 500);
    }
    const sb = createClient(supabaseUrl, serviceKey);

    const tokenHash = await sha256Hex(token);
    const { data: cred, error: credErr } = await sb
      .from("device_credentials")
      .select("id, edge_device_id, revoked_at, edge_devices!inner(id, device_code, school_id, organization_id, status)")
      .eq("token_hash", tokenHash)
      .is("revoked_at", null)
      .maybeSingle();

    if (credErr || !cred) {
      return json({ ok: false, status: "unauthorized", error: "invalid_or_revoked_token" }, 401);
    }

    const device = (cred as any).edge_devices;
    const payload = await req.json();
    if (hasForbiddenPayload(payload)) {
      return json({ ok: false, status: "invalid", error: "forbidden_fields" }, 400);
    }

    const eventType = payload.event_type as string;
    const eventId = payload.event_id as string;
    if (!eventType || !eventId) {
      return json({ ok: false, status: "invalid", error: "missing_event_type_or_id" }, 400);
    }

    // heartbeat
    if (eventType === "device_heartbeat") {
      await sb
        .from("edge_devices")
        .update({
          last_seen_at: payload.last_seen_at || new Date().toISOString(),
          app_version: payload.app_version || null,
          status: "online",
        })
        .eq("id", device.id);
      return json({ ok: true, status: "inserted", event_id: eventId, received: 1 });
    }

    if (eventType === "class_session_upsert") {
      const s = payload.session || {};
      if (!s.id) return json({ ok: false, status: "invalid", error: "missing_session_id" }, 400);
      const row = {
        id: s.id,
        organization_id: s.organization_id || device.organization_id,
        school_id: s.school_id || device.school_id,
        edge_device_id: device.id,
        title: s.title || "Sessão",
        status: s.status || "active",
        started_at: s.started_at,
        ended_at: s.ended_at || null,
        scheduled_start_at: s.scheduled_start_at || null,
        scheduled_duration_minutes: s.scheduled_duration_minutes || null,
        external_lesson_id: s.external_lesson_id || null,
        lesson_occurrence_id: s.lesson_occurrence_id || null,
        class_group_id: s.class_group_id || null,
        subject_id: s.subject_id || null,
        teacher_profile_id: s.teacher_profile_id || null,
        room_id: s.room_id || null,
        source_device_id: s.source_device_id || device.device_code,
        synced_at: new Date().toISOString(),
      };
      if (!row.organization_id || !row.school_id || !row.started_at) {
        return json({ ok: false, status: "invalid", error: "session_missing_tenant_or_time" }, 400);
      }
      if (row.school_id !== device.school_id) {
        return json({ ok: false, status: "unauthorized", error: "school_mismatch" }, 403);
      }
      const { error } = await sb.from("class_sessions").upsert(row, { onConflict: "id" });
      if (error) {
        if ((error as any).code === "23505") {
          return json({ ok: true, status: "duplicate", event_id: eventId });
        }
        return json({ ok: false, status: "retryable_error", error: error.message }, 500);
      }
      return json({ ok: true, status: "inserted", event_id: eventId });
    }

    if (eventType === "session_event_upsert") {
      const e = payload.session_event || {};
      if (!e.id || !e.session_id) {
        return json({ ok: false, status: "invalid", error: "missing_event_or_session" }, 400);
      }
      const row = {
        id: e.id,
        session_id: e.session_id,
        organization_id: e.organization_id || device.organization_id,
        school_id: e.school_id || device.school_id,
        device_id: e.device_id || device.device_code,
        edge_camera_id: e.edge_camera_id || null,
        student_id: e.student_id || null,
        anonymous_track_id: e.anonymous_track_id || null,
        event_type: e.event_type,
        opened_at: e.opened_at,
        closed_at: e.closed_at || null,
        duration_seconds: e.duration_seconds ?? null,
        confidence: e.confidence ?? null,
        observation_quality: e.observation_quality || null,
        status: e.status || "open",
        review_status: e.review_status || "none",
        payload: e.payload || {},
        synced_at: new Date().toISOString(),
      };
      if (row.school_id !== device.school_id) {
        return json({ ok: false, status: "unauthorized", error: "school_mismatch" }, 403);
      }
      const { error } = await sb.from("session_events").upsert(row, { onConflict: "id" });
      if (error) {
        if ((error as any).code === "23505") {
          return json({ ok: true, status: "duplicate", event_id: eventId });
        }
        return json({ ok: false, status: "retryable_error", error: error.message }, 500);
      }
      return json({ ok: true, status: "inserted", event_id: eventId });
    }

    if (eventType === "session_report_snapshot") {
      const s = payload.snapshot || {};
      if (!s.session_id || !s.captured_at || !s.report) {
        return json({ ok: false, status: "invalid", error: "missing_snapshot_fields" }, 400);
      }
      const row = {
        id: s.id || crypto.randomUUID(),
        session_id: s.session_id,
        organization_id: s.organization_id || device.organization_id,
        school_id: s.school_id || device.school_id,
        schema_version: s.schema_version || 1,
        captured_at: s.captured_at,
        report: s.report,
        source_device_id: s.source_device_id || device.device_code,
        is_final: !!s.is_final,
        synced_at: new Date().toISOString(),
      };
      if (row.school_id !== device.school_id) {
        return json({ ok: false, status: "unauthorized", error: "school_mismatch" }, 403);
      }
      const { error } = await sb.from("session_report_snapshots").upsert(row, {
        onConflict: "session_id,captured_at",
      });
      if (error) {
        if ((error as any).code === "23505") {
          return json({ ok: true, status: "duplicate", event_id: eventId });
        }
        return json({ ok: false, status: "retryable_error", error: error.message }, 500);
      }
      return json({ ok: true, status: "inserted", event_id: eventId });
    }

    // legacy behavioral_event / attendance passthrough ignored for product ingest
    return json({
      ok: true,
      status: "ignored",
      event_id: eventId,
      message: "event_type_not_handled_by_product_ingest",
    });
  } catch (e) {
    return json(
      { ok: false, status: "retryable_error", error: String(e) },
      500,
    );
  }
});
