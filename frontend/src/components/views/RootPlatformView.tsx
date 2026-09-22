import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../../cloud/AuthContext";
import { supabase } from "../../cloud/supabaseClient";
import { SectionHeader } from "../ui/SectionHeader";

type Org = { id: string; name: string; slug: string | null };
type School = { id: string; name: string; organization_id: string };
type Profile = {
  id: string;
  email: string | null;
  full_name: string | null;
  status: string;
  is_platform_admin: boolean;
};
type Audit = {
  id: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
  meta: Record<string, unknown>;
};

type RootTab = "orgs" | "schools" | "users" | "audit";

async function callPlatformAdmin(pathAction: string, body: Record<string, unknown>) {
  if (!supabase) throw new Error("Supabase não configurado");
  const { data: session } = await supabase.auth.getSession();
  const token = session.session?.access_token;
  if (!token) throw new Error("Faça login novamente");
  const base = (import.meta as any).env?.VITE_SUPABASE_URL || "";
  const anon = (import.meta as any).env?.VITE_SUPABASE_ANON_KEY || "";
  const res = await fetch(`${base}/functions/v1/platform-admin`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      apikey: anon,
    },
    body: JSON.stringify({ action: pathAction, ...body }),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || json.message || `HTTP ${res.status}`);
  return json;
}

/**
 * Área ROOT — organizações, escolas, usuários e auditoria.
 * Visível apenas para is_platform_admin / isRoot.
 */
export function RootPlatformView() {
  const auth = useAuth();
  const [tab, setTab] = useState<RootTab>("orgs");
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [schools, setSchools] = useState<School[]>([]);
  const [users, setUsers] = useState<Profile[]>([]);
  const [audits, setAudits] = useState<Audit[]>([]);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [schoolName, setSchoolName] = useState("");
  const [schoolOrgId, setSchoolOrgId] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState("gestor");
  const [inviteSchoolId, setInviteSchoolId] = useState("");
  const [invitePassword, setInvitePassword] = useState("");

  const load = useCallback(async () => {
    if (!supabase || !auth.isRoot) return;
    setErr("");
    const [o, s, p, a] = await Promise.all([
      supabase.from("organizations").select("id, name, slug").order("name"),
      supabase.from("schools").select("id, name, organization_id").order("name"),
      supabase
        .from("profiles")
        .select("id, email, full_name, status, is_platform_admin")
        .order("email"),
      supabase
        .from("audit_logs")
        .select("id, action, resource_type, resource_id, created_at, meta")
        .order("created_at", { ascending: false })
        .limit(50),
    ]);
    if (o.error) setErr(o.error.message);
    setOrgs((o.data as Org[]) || []);
    setSchools((s.data as School[]) || []);
    setUsers((p.data as Profile[]) || []);
    setAudits((a.data as Audit[]) || []);
    if (!schoolOrgId && o.data?.[0]) setSchoolOrgId(o.data[0].id);
    if (!inviteSchoolId && s.data?.[0]) setInviteSchoolId(s.data[0].id);
  }, [auth.isRoot, schoolOrgId, inviteSchoolId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!auth.isRoot) {
    return (
      <section>
        <h1>Plataforma</h1>
        <p className="muted">Acesso restrito ao ROOT.</p>
      </section>
    );
  }

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(true);
    setErr("");
    setInfo("");
    try {
      await fn();
      setInfo(label);
      await load();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="root-platform-view">
      <h1>Plataforma (ROOT)</h1>
      <p className="muted">Gestão global de organizações, escolas, usuários e auditoria.</p>

      <div className="root-tabs">
        {(
          [
            ["orgs", "Organizações"],
            ["schools", "Escolas"],
            ["users", "Usuários"],
            ["audit", "Auditoria"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={tab === id ? "btn" : "btn-link"}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {err && <p className="error-text">{err}</p>}
      {info && <p className="muted">{info}</p>}

      {tab === "orgs" && (
        <div className="panel">
          <SectionHeader title="Organizações" subtitle="Redes / tenants" />
          <ul>
            {orgs.map((o) => (
              <li key={o.id}>
                <strong>{o.name}</strong> <span className="muted">{o.slug || o.id}</span>
              </li>
            ))}
          </ul>
          <form
            className="login-form"
            onSubmit={(e) => {
              e.preventDefault();
              void run("Organização criada", async () => {
                await callPlatformAdmin("create_organization", {
                  name: orgName,
                  slug: orgSlug || undefined,
                });
                setOrgName("");
                setOrgSlug("");
              });
            }}
          >
            <label>
              Nome
              <input value={orgName} onChange={(e) => setOrgName(e.target.value)} required />
            </label>
            <label>
              Slug (opcional)
              <input value={orgSlug} onChange={(e) => setOrgSlug(e.target.value)} />
            </label>
            <button type="submit" className="btn" disabled={busy}>
              Criar organização
            </button>
          </form>
        </div>
      )}

      {tab === "schools" && (
        <div className="panel">
          <SectionHeader title="Escolas" />
          <ul>
            {schools.map((s) => (
              <li key={s.id}>
                <strong>{s.name}</strong>{" "}
                <span className="muted">
                  {orgs.find((o) => o.id === s.organization_id)?.name || s.organization_id}
                </span>
              </li>
            ))}
          </ul>
          <form
            className="login-form"
            onSubmit={(e) => {
              e.preventDefault();
              void run("Escola criada", async () => {
                await callPlatformAdmin("create_school", {
                  name: schoolName,
                  organization_id: schoolOrgId,
                });
                setSchoolName("");
              });
            }}
          >
            <label>
              Organização
              <select value={schoolOrgId} onChange={(e) => setSchoolOrgId(e.target.value)} required>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Nome da escola
              <input value={schoolName} onChange={(e) => setSchoolName(e.target.value)} required />
            </label>
            <button type="submit" className="btn" disabled={busy}>
              Criar escola
            </button>
          </form>
        </div>
      )}

      {tab === "users" && (
        <div className="panel">
          <SectionHeader title="Usuários" subtitle="Staff (auth.users / profiles)" />
          <ul className="root-user-list">
            {users.map((u) => (
              <li key={u.id}>
                <div>
                  <strong>{u.full_name || u.email}</strong> — {u.email}{" "}
                  <span className="muted">
                    [{u.status}]{u.is_platform_admin ? " ROOT" : ""}
                  </span>
                </div>
                <div className="row">
                  {u.status !== "disabled" ? (
                    <button
                      type="button"
                      className="btn-link"
                      disabled={busy}
                      onClick={() =>
                        void run("Usuário desativado", async () => {
                          await callPlatformAdmin("set_user_status", {
                            user_id: u.id,
                            status: "disabled",
                          });
                        })
                      }
                    >
                      Desativar
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn-link"
                      disabled={busy}
                      onClick={() =>
                        void run("Usuário reativado", async () => {
                          await callPlatformAdmin("set_user_status", {
                            user_id: u.id,
                            status: "active",
                          });
                        })
                      }
                    >
                      Reativar
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-link"
                    disabled={busy}
                    onClick={() => {
                      const pw = window.prompt("Nova senha temporária (mín. 8 caracteres):");
                      if (!pw || pw.length < 8) return;
                      void run("Senha redefinida", async () => {
                        await callPlatformAdmin("reset_password", {
                          user_id: u.id,
                          temporary_password: pw,
                        });
                      });
                    }}
                  >
                    Reset senha
                  </button>
                </div>
              </li>
            ))}
          </ul>

          <SectionHeader title="Convidar / criar usuário" subtitle="Cria conta + membership escolar" />
          <form
            className="login-form"
            onSubmit={(e) => {
              e.preventDefault();
              void run("Usuário criado", async () => {
                await callPlatformAdmin("invite_user", {
                  email: inviteEmail,
                  full_name: inviteName,
                  role: inviteRole,
                  school_id: inviteSchoolId,
                  temporary_password: invitePassword,
                });
                setInviteEmail("");
                setInviteName("");
                setInvitePassword("");
              });
            }}
          >
            <label>
              Nome
              <input value={inviteName} onChange={(e) => setInviteName(e.target.value)} required />
            </label>
            <label>
              E-mail
              <input
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                required
              />
            </label>
            <label>
              Papel
              <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
                <option value="gestor">Gestor</option>
                <option value="coordenador">Coordenador</option>
                <option value="professor">Professor</option>
                <option value="monitor">Monitor</option>
                <option value="admin_rede">Admin rede</option>
              </select>
            </label>
            <label>
              Escola
              <select
                value={inviteSchoolId}
                onChange={(e) => setInviteSchoolId(e.target.value)}
                required={inviteRole !== "admin_rede"}
              >
                {schools.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Senha temporária
              <input
                type="password"
                value={invitePassword}
                onChange={(e) => setInvitePassword(e.target.value)}
                required
                minLength={8}
              />
            </label>
            <button type="submit" className="btn" disabled={busy}>
              Criar usuário
            </button>
          </form>
        </div>
      )}

      {tab === "audit" && (
        <div className="panel">
          <SectionHeader title="Auditoria" subtitle="Últimos 50 eventos" />
          <ul>
            {audits.map((a) => (
              <li key={a.id}>
                <code>{a.created_at}</code> — <strong>{a.action}</strong>{" "}
                <span className="muted">
                  {a.resource_type} {a.resource_id}
                </span>
              </li>
            ))}
            {audits.length === 0 && <li className="muted">Sem eventos ainda.</li>}
          </ul>
        </div>
      )}
    </section>
  );
}
