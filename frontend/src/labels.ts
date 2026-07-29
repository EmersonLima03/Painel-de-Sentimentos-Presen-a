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
      return "Expressão mista";
    case "surprise":
      return "Expressão de surpresa aparente";
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
    possible_drowsiness: "Possível sonolência aparente",
    probable_drowsiness: "Sonolência aparente consistente",
    possible_phone_interaction: "Possível uso de celular",
    probable_phone_interaction: "Provável uso de celular",
    low_visual_attention: "Atenção visual baixa",
    head_down_persistent: "Cabeça baixa prolongada",
    face_occluded_persistent: "Rosto ocluído",
  };
  return (t && map[t]) || t || "Evento";
}

export const DISCLAIMER =
  "Indicadores estimados a partir de sinais visuais. Não constituem diagnóstico, avaliação psicológica ou comprovação de aprendizagem.";

export const DEMO_BANNER =
  "Modo demonstração — todos os indicadores apresentados nesta sessão são simulados.";
