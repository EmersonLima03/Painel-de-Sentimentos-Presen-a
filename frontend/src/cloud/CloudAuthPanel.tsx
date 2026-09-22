import { useState } from "react";
import { useAuth } from "./AuthContext";
import { supabase, supabaseConfigured } from "./supabaseClient";

/**
 * Compact account panel for Settings — uses AuthContext as source of truth.
 */
export function CloudAuthPanel() {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  if (!supabaseConfigured || !supabase) {
    return (
      <div className="state-box unavailable" role="status">
        <strong>Cloud Auth</strong>
        <p>Configure VITE_SUPABASE_URL e VITE_SUPABASE_ANON_KEY para login Sentimentos.</p>
      </div>
    );
  }

  if (auth.email) {
    return (
      <div className="cloud-auth-panel">
        <p>
          Conectado: <strong>{auth.email}</strong>
          {auth.isRoot ? " (ROOT)" : ""}
          {auth.activeRole ? ` — ${auth.activeRole}` : ""}
        </p>
        <ul>
          {auth.memberships.map((m) => (
            <li key={`${m.school_id}-${m.role}`}>
              {(m.schools as any)?.name || m.school_id} — {m.role}
            </li>
          ))}
          {auth.orgMemberships.map((m) => (
            <li key={`org-${m.organization_id}-${m.role}`}>
              {(m.organizations as any)?.name || m.organization_id} — {m.role}
            </li>
          ))}
        </ul>
        <button type="button" className="btn" onClick={() => void auth.signOut()}>
          Sair
        </button>
      </div>
    );
  }

  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const { error } = await supabase!.auth.signInWithPassword({ email, password });
      if (error) {
        setErr(
          /invalid|credencial|password|email/i.test(error.message)
            ? "E-mail ou senha incorretos. Verifique e tente novamente."
            : error.message || "Não foi possível entrar. Tente novamente.",
        );
      }
    } catch {
      setErr("Falha de conexão ao entrar. Verifique a internet e tente novamente.");
    } finally {
      setBusy(false);
    }
  }

  async function forgot() {
    if (!email) {
      setErr("Informe o e-mail para recuperar a senha.");
      return;
    }
    setBusy(true);
    setErr("");
    setInfo("");
    try {
      const { error } = await supabase!.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/dashboard`,
      });
      if (error) setErr(error.message);
      else setInfo("Se o e-mail existir, enviamos um link de recuperação.");
    } catch {
      setErr("Falha ao solicitar recuperação.");
    } finally {
      setBusy(false);
    }
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
      {info && <p className="muted">{info}</p>}
      <button type="submit" className="btn" disabled={busy}>
        {busy ? "Entrando…" : "Entrar"}
      </button>
      <button type="button" className="btn-link" disabled={busy} onClick={() => void forgot()}>
        Esqueci a senha
      </button>
    </form>
  );
}
