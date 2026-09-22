import { useState } from "react";
import { supabase, supabaseConfigured } from "../../cloud/supabaseClient";

type Mode = "login" | "forgot" | "reset";

/**
 * Full-screen login / password recovery for SaaS Dashboard.
 */
export function LoginView() {
  const [mode, setMode] = useState<Mode>(() => {
    const hash = window.location.hash || "";
    if (hash.includes("type=recovery")) return "reset";
    return "login";
  });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  if (!supabaseConfigured || !supabase) {
    return (
      <div className="login-screen">
        <div className="login-card state-box unavailable" role="alert">
          <h1>Presença</h1>
          <p>
            Login cloud indisponível: o build do Dashboard precisa de{" "}
            <code>VITE_SUPABASE_URL</code> e <code>VITE_SUPABASE_ANON_KEY</code>.
          </p>
          <p className="muted">
            Rebuild com essas variáveis (ex.: a partir de <code>.env.smoke.local</code>) e
            reinicie o boot Edge+M2.
          </p>
        </div>
      </div>
    );
  }

  async function onLogin(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setInfo("");
    try {
      const { error } = await supabase!.auth.signInWithPassword({ email, password });
      if (error) {
        setErr(
          /invalid|credencial|password|email/i.test(error.message)
            ? "E-mail ou senha incorretos."
            : error.message,
        );
      }
    } catch {
      setErr("Falha de conexão. Tente novamente.");
    } finally {
      setBusy(false);
    }
  }

  async function onForgot(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setInfo("");
    try {
      const redirectTo = `${window.location.origin}/dashboard`;
      const { error } = await supabase!.auth.resetPasswordForEmail(email, { redirectTo });
      if (error) setErr(error.message);
      else {
        setInfo("Se o e-mail existir, enviamos um link para redefinir a senha.");
        setMode("login");
      }
    } catch {
      setErr("Falha ao solicitar recuperação.");
    } finally {
      setBusy(false);
    }
  }

  async function onReset(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 8) {
      setErr("A senha deve ter pelo menos 8 caracteres.");
      return;
    }
    if (password !== password2) {
      setErr("As senhas não coincidem.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const { error } = await supabase!.auth.updateUser({ password });
      if (error) setErr(error.message);
      else {
        setInfo("Senha atualizada. Você já pode usar o painel.");
        setMode("login");
        window.location.hash = "";
      }
    } catch {
      setErr("Falha ao definir nova senha.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <h1>Presença</h1>
        <p className="muted">Entre com sua conta de staff (gestor, professor ou administrador).</p>

        {mode === "login" && (
          <form onSubmit={onLogin} className="login-form">
            <label>
              E-mail
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="username"
              />
            </label>
            <label>
              Senha
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </label>
            {err && <p className="error-text">{err}</p>}
            {info && <p className="muted">{info}</p>}
            <button type="submit" className="btn" disabled={busy}>
              {busy ? "Entrando…" : "Entrar"}
            </button>
            <button type="button" className="btn-link" onClick={() => setMode("forgot")}>
              Esqueci a senha
            </button>
          </form>
        )}

        {mode === "forgot" && (
          <form onSubmit={onForgot} className="login-form">
            <label>
              E-mail
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>
            {err && <p className="error-text">{err}</p>}
            <button type="submit" className="btn" disabled={busy}>
              {busy ? "Enviando…" : "Enviar link de recuperação"}
            </button>
            <button type="button" className="btn-link" onClick={() => setMode("login")}>
              Voltar ao login
            </button>
          </form>
        )}

        {mode === "reset" && (
          <form onSubmit={onReset} className="login-form">
            <h2>Nova senha</h2>
            <label>
              Senha
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </label>
            <label>
              Confirmar senha
              <input
                type="password"
                value={password2}
                onChange={(e) => setPassword2(e.target.value)}
                required
                minLength={8}
              />
            </label>
            {err && <p className="error-text">{err}</p>}
            {info && <p className="muted">{info}</p>}
            <button type="submit" className="btn" disabled={busy}>
              {busy ? "Salvando…" : "Salvar nova senha"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
