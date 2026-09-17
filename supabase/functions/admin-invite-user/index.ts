// Invite professor/monitor — JWT required; caller must be gestor of school_id.
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

    const body = await req.json();
    const email = String(body.email || "").trim().toLowerCase();
    const fullName = String(body.full_name || "").trim();
    const role = String(body.role || "").trim();
    const schoolId = String(body.school_id || "").trim();
    const password = String(body.temporary_password || "").trim();

    if (!email || !fullName || !schoolId || !password) {
      return json({ error: "missing_fields" }, 400);
    }
    if (role !== "professor" && role !== "monitor" && role !== "gestor") {
      return json({ error: "invalid_role" }, 400);
    }
    if (password.length < 8) {
      return json({ error: "password_too_short" }, 400);
    }

    const admin = createClient(supabaseUrl, serviceKey);

    // Caller must be gestor (or platform admin) of the school
    const { data: callerProfile } = await admin
      .from("profiles")
      .select("is_platform_admin")
      .eq("id", user.id)
      .maybeSingle();

    const { data: callerMem } = await admin
      .from("memberships")
      .select("role")
      .eq("profile_id", user.id)
      .eq("school_id", schoolId)
      .maybeSingle();

    const allowed =
      callerProfile?.is_platform_admin === true || callerMem?.role === "gestor";
    if (!allowed) return json({ error: "forbidden" }, 403);

    const { data: school, error: schoolErr } = await admin
      .from("schools")
      .select("id, organization_id")
      .eq("id", schoolId)
      .maybeSingle();
    if (schoolErr || !school) return json({ error: "school_not_found" }, 404);

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
    });

    const { error: memErr } = await admin.from("memberships").upsert(
      {
        profile_id: uid,
        school_id: school.id,
        organization_id: school.organization_id,
        role,
      },
      { onConflict: "profile_id,school_id" },
    );
    if (memErr) {
      return json({ error: memErr.message, user_id: uid }, 400);
    }

    return json({
      ok: true,
      user_id: uid,
      email,
      role,
      school_id: school.id,
    });
  } catch (e) {
    return json({ error: String(e) }, 500);
  }
});
