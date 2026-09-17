/** Meta pedagógica local (Fase 1) — fallback até LXP. Não inventa presença/fora da sala. */

export type AulaMeta = {
  turma: string;
  disciplina: string;
  professor: string;
  /** minutos previstos: 50, 100 ou custom */
  durationMinutes: number | null;
};

export const AULA_META_KEY = "presenca_aula_meta";

const DEFAULTS: AulaMeta = {
  turma: "",
  disciplina: "",
  professor: "",
  durationMinutes: 50,
};

export function loadAulaMeta(): AulaMeta {
  try {
    const raw = localStorage.getItem(AULA_META_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<AulaMeta>;
    const dur = parsed.durationMinutes;
    return {
      turma: String(parsed.turma || "").trim(),
      disciplina: String(parsed.disciplina || "").trim(),
      professor: String(parsed.professor || "").trim(),
      durationMinutes:
        dur === null || dur === undefined
          ? 50
          : Number.isFinite(Number(dur)) && Number(dur) > 0
            ? Math.round(Number(dur))
            : 50,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveAulaMeta(meta: AulaMeta): void {
  localStorage.setItem(AULA_META_KEY, JSON.stringify(meta));
}

export function formatClockFromUnix(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(Number(sec))) return "—";
  const d = new Date(Number(sec) * 1000);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}
