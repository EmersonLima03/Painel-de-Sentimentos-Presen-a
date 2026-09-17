export function exprLabel(raw: string | undefined): string {
  switch (raw) {
    case "predominantly_positive":
    case "positive":
      return "Expressão predominantemente positiva";
    case "predominantly_neutral":
    case "neutral":
      return "Expressão predominantemente neutra";
    case "predominantly_negative":
    case "negative":
      return "Expressão predominantemente negativa";
    case "mixed":
    case "surprise":
      return "Expressão predominantemente neutra";
    case "inconclusive":
      return "Inconclusivo";
    default:
      return raw ? String(raw) : "Sem dado";
  }
}

export function attnLabel(raw: string | undefined): string {
  switch (raw) {
    case "high":
      return "Alta";
    case "moderate":
      return "Moderada";
    case "low":
      return "Baixa";
    case "inconclusive":
      return "Inconclusiva";
    default:
      return raw ? String(raw) : "Sem dado";
  }
}

export function attnClass(raw: string | undefined): string {
  if (raw === "high") return "good";
  if (raw === "moderate") return "mid";
  if (raw === "low") return "warn";
  return "muted";
}

export function exprClass(raw: string | undefined): string {
  if (!raw || raw === "inconclusive") return "muted";
  if (raw.includes("positive")) return "good";
  if (raw.includes("negative")) return "warn";
  return "mid";
}

export function qualityLabel(raw: string | undefined): string {
  switch (raw) {
    case "observable":
      return "Observável";
    case "partially_observable":
      return "Parcial";
    case "low_quality":
      return "Baixa qualidade";
    case "inconclusive":
      return "Inconclusivo";
    default:
      return raw || "—";
  }
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${Math.round(n)}%`;
}

export function fmtDur(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "—";
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m} min ${r}s` : `${m} min`;
}

export function eventTypePt(t: string | undefined): string {
  const map: Record<string, string> = {
    possible_drowsiness: "Sinal compatível com olhos fechados",
    probable_drowsiness: "Sinal mais consistente de olhos fechados",
    possible_phone_interaction: "Uso aparente de celular",
    probable_phone_interaction: "Uso aparente de celular",
    low_visual_attention: "Sinal de atenção baixa",
    head_down_persistent: "Sinal de cabeça baixa",
    face_occluded_persistent: "Rosto parcialmente coberto (leitura limitada)",
  };
  return (t && map[t]) || t || "Ocorrência observada";
}

/** Rótulo curto para cards (sem jargão técnico). */
export function eventTypePtShort(t: string | undefined): string {
  return eventTypePt(t);
}

export function attnStatePt(raw: string | undefined): string {
  switch (raw) {
    case "high":
      return "Atenção: estável";
    case "moderate":
      return "Atenção: moderada";
    case "low":
      return "Sinal de atenção baixa";
    case "inconclusive":
      return "Atenção: leitura inconclusiva";
    default:
      return "Atenção: sem dado";
  }
}

export function phoneStatePt(raw: string | undefined): string {
  const s = String(raw || "").toLowerCase();
  if (!s || s === "not_detected" || s === "none") return "Celular: sem sinal atual";
  if (s.includes("probable") || s.includes("possible") || s === "phone_in_hand") {
    return "Uso aparente de celular";
  }
  if (s.includes("near")) return "Celular: próximo (sem uso confirmado)";
  return "Celular: sinal observado";
}

export function qualityReadingPt(raw: string | undefined): string {
  switch (raw) {
    case "observable":
      return "Qualidade da leitura: boa";
    case "partially_observable":
      return "Qualidade da leitura: parcial";
    case "low_quality":
      return "Qualidade da leitura: limitada";
    case "inconclusive":
      return "Qualidade da leitura: inconclusiva";
    case "not_visible":
      return "Não localizado neste enquadramento";
    default:
      return "Qualidade da leitura: —";
  }
}

export const DISCLAIMER =
  "Indicadores estimados a partir de sinais visuais. Não constituem diagnóstico, avaliação psicológica ou comprovação de aprendizagem.";

export const DEMO_BANNER =
  "Modo demonstração — todos os indicadores apresentados nesta sessão são simulados.";
