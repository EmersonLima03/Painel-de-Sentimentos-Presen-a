import { useMemo, useState } from "react";
import { deriveStudentStatus } from "../components/ui/StudentCompactCard";

export type LiveFilterId =
  | "all"
  | "present"
  | "for_review"
  | "inconclusive"
  | "not_visible";

const PAGE_SIZE = 30;

export function useLiveFilters(tracks: any[]) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<LiveFilterId>("all");
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (tracks || []).filter((t) => {
      const name = String(t.full_name || t.student_id || "").toLowerCase();
      if (q && !name.includes(q)) return false;
      const st = deriveStudentStatus(t);
      if (filter === "all") return true;
      if (filter === "present") return st === "present" || st === "adequate";
      if (filter === "for_review") return st === "for_review";
      if (filter === "inconclusive") return st === "inconclusive" || st === "identity_uncertain";
      if (filter === "not_visible") return st === "not_visible";
      return true;
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
