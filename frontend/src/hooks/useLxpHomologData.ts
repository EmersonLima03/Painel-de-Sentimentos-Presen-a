import { useCallback, useEffect, useState } from "react";

export type HomologSnapshot = {
  ok?: boolean;
  environment?: {
    title?: string;
    subtitle?: string;
    badge?: string;
    disclaimer?: string;
    simulator_label?: string;
    simulator_host?: string;
    project_ref?: string;
  };
  simulator?: {
    status?: string;
    host?: string;
    mode?: string;
    reason?: string;
  };
  context?: Record<string, unknown>;
  recognition?: { tracks?: any[]; present?: number | null };
  outbox_summary?: {
    pending?: number;
    sent?: number;
    failed?: number;
    retries_total?: number;
    total?: number;
  };
  history?: any[];
  checkins?: any[];
  pipeline?: {
    steps?: any[];
    detail?: any;
    selected_event_id?: string;
  };
  presence?: any[];
  idempotency?: {
    observed?: boolean;
    event_id?: string;
    receipts?: any[];
    attendance_record_count?: number;
    message?: string;
  };
  admin_simulator_hint?: string;
  error?: string;
};

function apiToken(): string {
  return localStorage.getItem("api_token") || "";
}

export function useLxpHomologData(pollMs = 2000) {
  const [data, setData] = useState<HomologSnapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const tok = apiToken();
      const q = selectedEventId
        ? `?event_id=${encodeURIComponent(selectedEventId)}`
        : "";
      const r = await fetch(`/api/v1/homolog/lxp${q}`, {
        headers: tok ? { "X-API-Token": tok } : {},
      });
      if (!r.ok) {
        setErr(`HTTP ${r.status}`);
        return;
      }
      const j = (await r.json()) as HomologSnapshot;
      setData(j);
      setErr(null);
      if (!selectedEventId && j.pipeline?.selected_event_id) {
        setSelectedEventId(j.pipeline.selected_event_id);
      }
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }, [selectedEventId]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
  }, [refresh, pollMs]);

  /** Recompute pipeline detail from history selection (client-side join of fields already in history). */
  const selectedRow =
    (data?.history || []).find((h) => h.event_id === selectedEventId) ||
    (data?.history || [])[0] ||
    null;

  return {
    data,
    err,
    loading,
    refresh,
    selectedEventId: selectedEventId || selectedRow?.event_id || null,
    setSelectedEventId,
    selectedRow,
  };
}
