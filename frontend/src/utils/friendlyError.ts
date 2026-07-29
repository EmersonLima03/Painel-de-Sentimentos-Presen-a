/** Mensagem amigável; detalhes técnicos só no console. */
export function toFriendlyError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err || "");
  console.error("[dashboard]", err);
  if (/Failed to fetch|NetworkError|ERR_CONNECTION|ECONNREFUSED/i.test(raw)) {
    return "Não foi possível atualizar os dados. Verifique se o servidor está em execução e tente novamente.";
  }
  if (/401|403|Unauthorized|Forbidden/i.test(raw)) {
    return "Não foi possível autenticar. Verifique o token da API nas configurações.";
  }
  if (/404|Not Found/i.test(raw)) {
    return "Um recurso solicitado não foi encontrado. Tente novamente em instantes.";
  }
  if (/500|502|503|Internal Server/i.test(raw)) {
    return "O servidor encontrou um problema temporário. Tente novamente em instantes.";
  }
  return "Não foi possível atualizar os dados. Verifique se o servidor está em execução e tente novamente.";
}
