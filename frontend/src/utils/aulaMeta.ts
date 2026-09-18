/** Meta pedagógica local — fallback até LXP. Não inventa presença. */

export type AulaMeta = {
  turma: string;
  disciplina: string;
  professor: string;
  /** minutos previstos: 50, 100 ou custom */
  durationMinutes: number | null;
  /** ID da aula no LXP/simulador; vazio = não configurada */
  externalLessonId: string;
};

export const AULA_META_KEY = "presenca_aula_meta";

const DEFAULTS: AulaMeta = {
  turma: "",
  disciplina: "",
  professor: "",
  durationMinutes: 50,
  externalLessonId: "",
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
      externalLessonId: String(parsed.externalLessonId || "").trim(),
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveAulaMeta(meta: AulaMeta): void {
  localStorage.setItem(AULA_META_KEY, JSON.stringify(meta));
}

export function formatClockFromUnix(ts: number | null | undefined): string {
  if (!ts) return "--:--";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function formatExternalLessonLabel(meta: AulaMeta): string {
  const id = (meta.externalLessonId || "").trim();
  if (!id) return "Aula externa não configurada";
  return `Aula externa: ${id}`;
}
