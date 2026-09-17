import { useMemo, useState } from "react";
import { deriveStudentStatus } from "../components/ui/StudentCompactCard";
import { trackHasAttentionNow } from "../utils/events";

export type LiveFilterId =
  | "all"
  | "present"
  | "attention"
  | "for_review"
  | "inconclusive";

const PAGE_SIZE = 30;

function sortRank(t: any): number {
  if (trackHasAttentionNow(t)) return 0;
  const st = deriveStudentStatus(t);
  if (st === "inconclusive" || st === "identity_uncertain") return 1;
  if (st === "not_visible") return 2;
  return 3;
}

export function useLiveFilters(tracks: any[]) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<LiveFilterId>("all");
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = (tracks || []).filter((t) => {
      const name = String(t.full_name || t.student_id || "").toLowerCase();
      if (q && !name.includes(q)) return false;
      const st = deriveStudentStatus(t);
      if (filter === "all") return true;
      if (filter === "present") return st === "present" || st === "adequate" || st === "for_review";
      if (filter === "attention") return trackHasAttentionNow(t);
      if (filter === "for_review") return st === "for_review";
      if (filter === "inconclusive") return st === "inconclusive" || st === "identity_uncertain";
      return true;
    });
    return [...list].sort((a, b) => {
      const d = sortRank(a) - sortRank(b);
      if (d !== 0) return d;
      return String(a.full_name || "").localeCompare(String(b.full_name || ""), "pt-BR");
    });
  }, [tracks, search, filter]);

  const total = filtered.length;
  const pageSafe = Math.min(page, Math.max(1, Math.ceil(total / PAGE_SIZE) || 1));
  const pageItems = filtered.slice((pageSafe - 1) * PAGE_SIZE, pageSafe * PAGE_SIZE);

  const setFilterReset = (id: LiveFilterId) => {
    setFilter(id);
    setPage(1);
  };
  const setSearchReset = (v: string) => {
    setSearch(v);
    setPage(1);
  };

  return {
    search,
    setSearch: setSearchReset,
    filter,
    setFilter: setFilterReset,
    page: pageSafe,
    setPage,
    pageSize: PAGE_SIZE,
    total,
    pageItems,
    filtered,
  };
}
