// Platform ROOT admin actions — JWT required; caller must be is_platform_admin.
// Uses service role only inside the function (never in browser).

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.1";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

async function audit(
  admin: ReturnType<typeof createClient>,
  actorId: string,
  action: string,
  resourceType?: string,
  resourceId?: string,
  meta: Record<string, unknown> = {},
  organizationId?: string,
  schoolId?: string,
) {
  await admin.from("audit_logs").insert({
    actor_id: actorId,
    action,
    resource_type: resourceType || null,
    resource_id: resourceId || null,
    organization_id: organizationId || null,
    school_id: schoolId || null,
    meta,
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const anonKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
    if (!supabaseUrl || !serviceKey || !anonKey) {
      return json({ error: "server_misconfigured" }, 500);
    }

    const authHeader = req.headers.get("Authorization") || "";
    if (!authHeader.startsWith("Bearer ")) {
      return json({ error: "missing_auth" }, 401);
    }

    const userClient = createClient(supabaseUrl, anonKey, {
      global: { headers: { Authorization: authHeader } },
    });
    const {
      data: { user },
      error: userErr,
    } = await userClient.auth.getUser();
    if (userErr || !user) return json({ error: "unauthorized" }, 401);

    const admin = createClient(supabaseUrl, serviceKey);
    const { data: callerProfile } = await admin
      .from("profiles")
      .select("is_platform_admin, status")
      .eq("id", user.id)
      .maybeSingle();

    if (!callerProfile?.is_platform_admin) {
      return json({ error: "forbidden" }, 403);
    }
    if (callerProfile.status === "disabled") {
      return json({ error: "forbidden_disabled" }, 403);
    }

    const body = await req.json();
    const action = String(body.action || "").trim();

    if (action === "create_organization") {
      const name = String(body.name || "").trim();
      const slug = String(body.slug || "").trim() || null;
      if (!name) return json({ error: "missing_fields" }, 400);
      const { data, error } = await admin
        .from("organizations")
        .insert({ name, slug })
        .select("id, name, slug")
        .single();
      if (error) return json({ error: error.message }, 400);
      await audit(admin, user.id, "create_organization", "organization", data.id, { name });
      return json({ ok: true, organization: data });
    }

    if (action === "create_school") {
      const name = String(body.name || "").trim();
      const organizationId = String(body.organization_id || "").trim();
      if (!name || !organizationId) return json({ error: "missing_fields" }, 400);
      const { data, error } = await admin
        .from("schools")
        .insert({ name, organization_id: organizationId })
        .select("id, name, organization_id")
        .single();
      if (error) return json({ error: error.message }, 400);
      await audit(
        admin,
        user.id,
        "create_school",
        "school",
        data.id,
        { name },
        organizationId,
        data.id,
      );
      return json({ ok: true, school: data });
    }

    if (action === "set_user_status") {
      const userId = String(body.user_id || "").trim();
      const status = String(body.status || "").trim();
      if (!userId || !["active", "disabled", "invited"].includes(status)) {
        return json({ error: "missing_fields" }, 400);
      }
      if (userId === user.id && status === "disabled") {
        return json({ error: "cannot_disable_self" }, 400);
      }
      const { error } = await admin.from("profiles").update({ status }).eq("id", userId);
      if (error) return json({ error: error.message }, 400);
      await audit(admin, user.id, "set_user_status", "profile", userId, { status });
      return json({ ok: true });
    }

    if (action === "reset_password") {
      const userId = String(body.user_id || "").trim();
      const password = String(body.temporary_password || "").trim();
      if (!userId || password.length < 8) return json({ error: "missing_fields" }, 400);
      const { error } = await admin.auth.admin.updateUserById(userId, { password });
      if (error) return json({ error: error.message }, 400);
      await admin
        .from("profiles")
        .update({ must_reset_password: true })
        .eq("id", userId);
      await audit(admin, user.id, "reset_password", "profile", userId, {});
      return json({ ok: true });
    }

    if (action === "invite_user") {
      const email = String(body.email || "").trim().toLowerCase();
      const fullName = String(body.full_name || "").trim();
      const role = String(body.role || "").trim();
      const schoolId = String(body.school_id || "").trim();
      const password = String(body.temporary_password || "").trim();
      if (!email || !fullName || !password || password.length < 8) {
        return json({ error: "missing_fields" }, 400);
      }
      const schoolRoles = ["gestor", "coordenador", "professor", "monitor"];
      if (role !== "admin_rede" && !schoolRoles.includes(role)) {
        return json({ error: "invalid_role" }, 400);
      }

      const { data: created, error: createErr } = await admin.auth.admin.createUser({
        email,
        password,
        email_confirm: true,
        user_metadata: { full_name: fullName },
      });
      if (createErr || !created.user) {
        return json({ error: createErr?.message || "create_failed" }, 400);
      }
      const uid = created.user.id;
      await admin.from("profiles").upsert({
        id: uid,
        full_name: fullName,
        email,
        status: "active",
        must_reset_password: true,
      });

      if (role === "admin_rede") {
        let organizationId = String(body.organization_id || "").trim();
        if (!organizationId && schoolId) {
          const { data: school } = await admin
            .from("schools")
            .select("organization_id")
            .eq("id", schoolId)
            .maybeSingle();
          organizationId = school?.organization_id || "";
        }
        if (!organizationId) {
          return json({ error: "organization_required", user_id: uid }, 400);
        }
        const { error: omErr } = await admin.from("organization_memberships").upsert(
          { profile_id: uid, organization_id: organizationId, role: "admin_rede" },
          { onConflict: "profile_id,organization_id" },
        );
        if (omErr) return json({ error: omErr.message, user_id: uid }, 400);
        await admin.from("invites").insert({
          email,
          full_name: fullName,
          role,
          organization_id: organizationId,
          invited_by: user.id,
          status: "accepted",
          accepted_at: new Date().toISOString(),
        });
        await audit(admin, user.id, "invite_user", "profile", uid, { role, email }, organizationId);
        return json({ ok: true, user_id: uid });
      }

      if (!schoolId) return json({ error: "school_required", user_id: uid }, 400);
      const { data: school, error: schoolErr } = await admin
        .from("schools")
        .select("id, organization_id")
        .eq("id", schoolId)
        .maybeSingle();
      if (schoolErr || !school) return json({ error: "school_not_found", user_id: uid }, 404);

      const { error: memErr } = await admin.from("memberships").upsert(
        {
          profile_id: uid,
          school_id: school.id,
          organization_id: school.organization_id,
          role,
        },
        { onConflict: "profile_id,school_id" },
      );
      if (memErr) return json({ error: memErr.message, user_id: uid }, 400);

      await admin.from("invites").insert({
        email,
        full_name: fullName,
        role,
        organization_id: school.organization_id,
        school_id: school.id,
        invited_by: user.id,
        status: "accepted",
        accepted_at: new Date().toISOString(),
      });
      await audit(
        admin,
        user.id,
        "invite_user",
        "profile",
        uid,
        { role, email },
        school.organization_id,
        school.id,
      );
      return json({ ok: true, user_id: uid });
    }

    return json({ error: "unknown_action" }, 400);
  } catch (e) {
    return json({ error: String(e) }, 500);
  }
});
