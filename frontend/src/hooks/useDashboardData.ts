import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Tab, WsState } from "../types";
import {
  classifyFetchFailure,
  toFriendlyError,
  type EdgeConnectivity,
} from "../utils/friendlyError";

function apiHeaders(): HeadersInit {
  const token = localStorage.getItem("api_token") || "";
  return token ? { "X-API-Token": token } : {};
}

async function apiGet(path: string) {
  const r = await fetch(path, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function formatLastUpdate(ts: number | null): string {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export function useDashboardData() {
  const [tab, setTabRaw] = useState<Tab>("live");
  const [status, setStatus] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [tracks, setTracks] = useState<any[]>([]);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [students, setStudents] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [report, setReport] = useState<any>(null);
  const [perf, setPerf] = useState<any>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [wsState, setWsState] = useState<WsState>("connecting");
  const [edgeState, setEdgeState] = useState<EdgeConnectivity>("reconnecting");
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [reviewFilter, setReviewFilter] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const hadSuccessRef = useRef(false);

  const setTab = useCallback((t: Tab) => {
    setTabRaw(t === "overview" ? "live" : t);
  }, []);

  const sessionId = status?.session?.session_id as string | undefined;
  const isDemo = Boolean(status?.is_simulated || status?.runtime_mode === "demo");
  const elapsed = status?.session?.t_seconds as number | undefined;

  const refresh = useCallback(async () => {
    try {
      const st = await apiGet("/api/v1/live/status");
      setStatus(st);
      const sm = await apiGet("/api/v1/live/classroom-summary");
      setSummary(sm);
      const tr = await apiGet("/api/v1/live/tracks");
      setTracks(tr.tracks || []);
      const sid = st?.session?.session_id;
      if (sid) {
        const [tl, stu, ev, rp, pf] = await Promise.all([
          apiGet(`/api/v1/sessions/${sid}/timeline`),
          apiGet(`/api/v1/sessions/${sid}/students`),
          apiGet(`/api/v1/sessions/${sid}/behavioral-events`),
          apiGet(`/api/v1/sessions/${sid}/summary`),
          apiGet("/api/v1/system/performance").catch(() => ({})),
        ]);
        setTimeline(tl.timeline || []);
        setStudents(stu.students || []);
        setEvents(ev.events || []);
        setReport(rp);
        setPerf(pf);
      }
      setErr("");
      setEdgeState("live");
      setLastSuccessAt(Date.now());
      hadSuccessRef.current = true;
      setLoading(false);
    } catch (e) {
      const kind = classifyFetchFailure(e);
      setEdgeState(kind === "broken" ? "broken" : kind);
      if (kind === "auth" || kind === "permission" || kind === "broken") {
        setErr(toFriendlyError(e));
      } else if (hadSuccessRef.current) {
        setErr("");
      } else {
        setErr(toFriendlyError(e));
      }
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    let closed = false;
    let retry = 0;
    const connect = () => {
      if (closed) return;
      setWsState("connecting");
      const token = localStorage.getItem("api_token") || "";
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const q = token ? `?api_token=${encodeURIComponent(token)}` : "";
      const ws = new WebSocket(`${proto}://${location.host}/api/v1/ws/live${q}`);
      wsRef.current = ws;
      ws.onopen = () => {
        setWsState("connected");
        retry = 0;
      };
      ws.onclose = () => {
        setWsState("disconnected");
        setTimeout(connect, Math.min(10000, 1000 * Math.pow(2, retry++)));
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      wsRef.current?.close();
    };
  }, []);

  const demoControl = async (body: Record<string, unknown>) => {
    await fetch("/api/v1/demo/control", {
      method: "POST",
      headers: { ...apiHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    await refresh();
  };

  const patchReview = async (eventId: string, statusValue: string) => {
    await fetch(`/api/v1/review/events/${eventId}`, {
      method: "PATCH",
      headers: { ...apiHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ status: statusValue, notes: notes[eventId] || "" }),
    });
    await refresh();
  };

  const filteredEvents = useMemo(() => {
    if (!reviewFilter) return events;
    return events.filter(
      (e) => (e.review_status || e.attribution_status) === reviewFilter
    );
  }, [events, reviewFilter]);

  const k = summary || status?.kpis || {};
  const climateDist = summary?.climate_distribution || k.climate_distribution || {};
  const visible = Number(k.visible_people ?? k.visible ?? tracks.length) || 0;
  const observable = Number(k.observable_people ?? k.observable ?? 0) || 0;
  const obsPct = visible > 0 ? Math.round((100 * observable) / visible) : null;

  const edgeDegraded = edgeState === "offline" || edgeState === "reconnecting";
  const lastUpdateLabel = formatLastUpdate(lastSuccessAt);

  return {
    tab,
    setTab,
    loading,
    err,
    status,
    summary,
    tracks,
    timeline,
    students,
    events,
    report,
    perf,
    wsState,
    edgeState,
    edgeDegraded,
    lastUpdateLabel,
    sessionId,
    isDemo,
    reviewFilter,
    setReviewFilter,
    notes,
    setNotes,
    filteredEvents,
    patchReview,
    demoControl,
    k,
    climateDist,
    obsPct,
    elapsed,
  };
}
