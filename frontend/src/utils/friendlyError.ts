/** Mensagens pedagógicas — sem stack/HTTP bruto na UI. */
export type EdgeConnectivity =
  | "live"
  | "reconnecting"
  | "offline"
  | "auth"
  | "permission"
  | "broken";

export function classifyFetchFailure(err: unknown): EdgeConnectivity {
  const raw = err instanceof Error ? err.message : String(err || "");
  const lower = raw.toLowerCase();
  if (/\b401\b/.test(raw) || /unauthorized|não autentic|not authenticated/i.test(raw)) {
    return "auth";
  }
  if (/\b403\b/.test(raw) || /forbidden|permiss/i.test(raw)) {
    return "permission";
  }
  // Rede / Edge fora / proxy caiu
  if (
    /failed to fetch|networkerror|net::|load failed|econnrefused|connection refused|timeout|aborted/i.test(
      lower,
    ) ||
    /\b502\b|\b503\b|\b504\b/.test(raw)
  ) {
    return "offline";
  }
  // 500 transitório durante restart do Edge
  if (/\b500\b|\binternal server error\b/i.test(raw)) {
    return "reconnecting";
  }
  return "broken";
}

export function toFriendlyError(err: unknown): string {
  const kind = classifyFetchFailure(err);
  console.error("[dashboard]", err);
  if (kind === "auth") {
    return "Não foi possível autenticar. Verifique o token da API nas configurações.";
  }
  if (kind === "permission") {
    return "Você não tem permissão para esta operação.";
  }
  if (kind === "offline" || kind === "reconnecting") {
    return "Conexão com a sala temporariamente indisponível.";
  }
  return "Não foi possível atualizar os dados agora. Tente novamente em instantes.";
}

export function connectivityLabel(kind: EdgeConnectivity, wsState?: string): string {
  if (kind === "live" && wsState === "connected") return "Ao vivo";
  if (kind === "reconnecting" || wsState === "connecting") return "Reconectando";
  if (kind === "offline" || wsState === "disconnected") return "Sem conexão";
  if (kind === "auth") return "Autenticação";
  if (kind === "permission") return "Sem permissão";
  return "Indisponível";
}
