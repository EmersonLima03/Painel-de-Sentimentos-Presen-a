import { useEffect, useState } from "react";
import { supabase, supabaseConfigured, type MembershipRow } from "../lib/supabaseClient";

type Props = {
  onAuthChange?: (email: string | null) => void;
};

export function CloudAuthPanel({ onAuthChange }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [memberships, setMemberships] = useState<MembershipRow[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then((res: { data: { session: any } }) => {
      const e = res.data.session?.user?.email || null;
      setUserEmail(e);
      onAuthChange?.(e);
      if (res.data.session) void loadMemberships();
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_ev: string, session: any) => {
      const e = session?.user?.email || null;
      setUserEmail(e);
      onAuthChange?.(e);
      if (session) void loadMemberships();
      else setMemberships([]);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  async function loadMemberships() {
    if (!supabase) return;
    const { data, error } = await supabase
      .from("memberships")
      .select("role, school_id, organization_id, schools(id, name)");
    if (error) {
      setErr(error.message);
      return;
    }
    setMemberships((data as any) || []);
  }

  async function login(e: React.FormEvent) {
    e.preventDefault();
    if (!supabase) return;
    setBusy(true);
    setErr("");
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setErr(error.message);
  }

  async function logout() {
    if (!supabase) return;
    await supabase.auth.signOut();
    setMemberships([]);
  }

  if (!supabaseConfigured) {
    return (
      <div className="state-box unavailable" role="status">
        <strong>Cloud Auth</strong>
        <p>Configure VITE_SUPABASE_URL e VITE_SUPABASE_ANON_KEY para login Sentimentos.</p>
      </div>
    );
  }

  if (userEmail) {
    return (
      <div className="cloud-auth-panel">
        <p>
          Conectado: <strong>{userEmail}</strong>
        </p>
        <ul>
          {memberships.map((m) => (
            <li key={`${m.school_id}-${m.role}`}>
              {(m.schools as any)?.name || m.school_id} — {m.role}
            </li>
          ))}
        </ul>
        <button type="button" className="btn" onClick={() => void logout()}>
          Sair
        </button>
      </div>
    );
  }

  return (
    <form className="cloud-auth-panel" onSubmit={login}>
      <h3>Entrar (Sentimentos)</h3>
      <label>
        E-mail
        <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
      </label>
      <label>
        Senha
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password"
          required
        />
      </label>
      {err && <p className="error-text">{err}</p>}
      <button type="submit" className="btn" disabled={busy}>
        {busy ? "Entrando…" : "Entrar"}
      </button>
    </form>
  );
}
