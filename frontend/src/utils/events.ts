/**
 * Deduplica eventos por event_id.
 * Não some o mesmo evento vindo de tracks[].active_events, events[], KPIs ou relatório.
 */

/** Evento ainda aberto (Atenção agora) — não confundir com revisão posterior. */
export function isActiveNowEvent(ev: any): boolean {
  const life = String(ev?.lifecycle || "").toLowerCase();
  if (life === "closed" || life === "ended") return false;
  if (ev?.ended_at != null || ev?.closed_at != null) return false;
  if (life === "opened" || life === "updated" || life === "active") return true;
  // active_events nos tracks costumam ser abertos mesmo sem lifecycle
  return true;
}

export function trackHasAttentionNow(track: any): boolean {
  const active = track?.active_events || track?.alert_events || [];
  if (Array.isArray(active) && active.some(isActiveNowEvent)) return true;
  if (track?.alert_type) return true;
  return false;
}

/** Alunos com sinais ativos neste momento (KPI / ordenação). */
export function collectAttentionNow(tracks: any[]): any[] {
  const out: any[] = [];
  const seen = new Set<string>();
  for (const t of tracks || []) {
    if (!trackHasAttentionNow(t)) continue;
    const active = (t.active_events || t.alert_events || []).filter(isActiveNowEvent);
    const key = String(t.student_id || t.person_track_id || t.track_id || "");
    if (key && seen.has(key)) continue;
    if (key) seen.add(key);
    const primary = active[0] || { event_type: t.alert_type };
    out.push({
      ...primary,
      event_id: primary.event_id || primary.id,
      full_name: t.full_name,
      student_id: t.student_id,
      person_track_id: t.person_track_id || t.track_id,
      duration_seconds: primary.duration_seconds,
      _track: t,
    });
  }
  return out;
}

export function countAttentionNow(tracks: any[]): number {
  return collectAttentionNow(tracks).length;
}

export function dedupeEventsById(lists: any[][]): any[] {
  const seen = new Set<string>();
  const out: any[] = [];
  for (const list of lists) {
    for (const ev of list || []) {
      const id = String(ev?.event_id || "").trim();
      if (!id) {
        // Sem id: incluir com chave composta para não colapsar todos
        const fallback = `${ev?.event_type || "ev"}:${ev?.person_track_id || ev?.track_id || ""}:${ev?.started_at || ev?.opened_at || ""}`;
        if (seen.has(fallback)) continue;
        seen.add(fallback);
        out.push(ev);
        continue;
      }
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(ev);
    }
  }
  return out;
}

/** Eventos ativos nos tracks + lista de sessão, deduplicados. */
export function collectReviewEvents(tracks: any[], events: any[]): any[] {
  const fromTracks: any[] = [];
  for (const t of tracks || []) {
    const active = t.active_events || t.alert_events || [];
    for (const ev of active) {
      fromTracks.push({
        ...ev,
        event_id: ev.event_id || ev.id,
        full_name: t.full_name,
        student_id: t.student_id || ev.student_id,
        person_track_id: t.person_track_id || t.track_id,
      });
    }
  }
  return dedupeEventsById([fromTracks, events || []]);
}

/** Contagem única para “Para revisão” — nunca soma KPIs + listas. */
export function countReviewEvents(opts: {
  tracks: any[];
  events: any[];
  reportEventsOpen?: number | null;
  kpiActiveEvents?: number | null;
}): number {
  const deduped = collectReviewEvents(opts.tracks, opts.events);
  if (deduped.length > 0) return deduped.length;
  // Só usa contadores agregados se não houver lista detalhada
  const open = opts.reportEventsOpen;
  if (open != null && !Number.isNaN(Number(open))) return Number(open);
  const kpi = opts.kpiActiveEvents;
  if (kpi != null && !Number.isNaN(Number(kpi))) return Number(kpi);
  return 0;
}

export function isPendingReview(ev: any): boolean {
  const st = String(ev?.review_status || ev?.attribution_status || ev?.status || "").toLowerCase();
  if (!st || st === "pending" || st === "pending_review" || st === "observed" || st === "possible" || st === "probable") {
    return true;
  }
  if (st === "confirmed" || st === "rejected" || st === "inconclusive") return false;
  return true;
}
