"""Official roster source for M2 campaigns: Supabase A (presence) or fixtures (tests/lab).

Product contract (Supabase A = rmiaadljzxyehwyuhhgd):
  schools.id / schools.name
  class_groups.id / class_groups.name / class_groups.school_id
  students.id / students.full_name / students.edge_student_key
  enrollments (active) links student_id ↔ class_group_id

Supabase B (LXP) is never queried here.

Env:
  M2_ROSTER_SOURCE=auto|supabase|fixtures   (default auto)
  M2_OPS_SUPABASE_URL / SUPABASE_URL
  M2_OPS_SUPABASE_SERVICE_KEY / SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("m2.roster_source")

_DEFAULT_FIXTURES = (
    Path(__file__).resolve().parent.parent / "data" / "fixtures" / "schools.json"
)


def _ops_url() -> str:
    return (
        os.environ.get("M2_OPS_SUPABASE_URL", "").strip()
        or os.environ.get("SUPABASE_URL", "").strip()
    ).rstrip("/")


def _ops_key() -> str:
    return (
        os.environ.get("M2_OPS_SUPABASE_SERVICE_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )


def supabase_credentials_ok() -> bool:
    return bool(_ops_url() and _ops_key())


def resolve_mode() -> str:
    """Return 'supabase' | 'fixtures'."""
    raw = (os.environ.get("M2_ROSTER_SOURCE", "auto") or "auto").strip().lower()
    if raw in ("fixtures", "fixture", "poc"):
        return "fixtures"
    if raw in ("supabase", "cloud", "a"):
        if not supabase_credentials_ok():
            raise RuntimeError(
                "M2_ROSTER_SOURCE=supabase mas SUPABASE_URL/SERVICE_ROLE_KEY ausentes"
            )
        return "supabase"
    # auto
    if supabase_credentials_ok():
        return "supabase"
    return "fixtures"


def _rest_get(path: str, query: str = "") -> Any:
    base = _ops_url()
    key = _ops_key()
    url = f"{base}/rest/v1/{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_schools_from_supabase() -> list[dict[str, Any]]:
    """Shape compatible with gestor UI / create_campaign fixtures."""
    schools_raw = _rest_get(
        "schools",
        "select=id,name,organization_id&order=name.asc",
    )
    groups_raw = _rest_get(
        "class_groups",
        "select=id,name,school_id,year_label&order=name.asc",
    )
    # Active enrollments with student names
    enroll_raw = _rest_get(
        "enrollments",
        "select=id,school_id,class_group_id,student_id,status,"
        "students(id,full_name,edge_student_key)&status=eq.active",
    )

    by_school_groups: dict[str, list[dict[str, Any]]] = {}
    for g in groups_raw:
        by_school_groups.setdefault(g["school_id"], []).append(g)

    students_by_class: dict[str, list[dict[str, Any]]] = {}
    for e in enroll_raw:
        if e.get("status") != "active":
            continue
        stu = e.get("students") or {}
        if isinstance(stu, list):
            stu = stu[0] if stu else {}
        if not stu or not stu.get("id"):
            continue
        cg = e["class_group_id"]
        students_by_class.setdefault(cg, []).append(
            {
                "student_id": stu["id"],
                "display_name": stu.get("full_name") or "Aluno",
                "fixture_key": stu.get("edge_student_key") or stu["id"],
                "edge_student_key": stu.get("edge_student_key"),
            }
        )

    out: list[dict[str, Any]] = []
    for s in schools_raw:
        groups = []
        for g in by_school_groups.get(s["id"], []):
            students = sorted(
                students_by_class.get(g["id"], []),
                key=lambda x: (x["display_name"] or "").lower(),
            )
            groups.append(
                {
                    "id": g["id"],
                    "label": g.get("name") or g["id"],
                    "shift": g.get("year_label"),
                    "students": students,
                }
            )
        out.append(
            {
                "id": s["id"],
                "name": s["name"],
                "organization_id": s.get("organization_id"),
                "class_groups": groups,
            }
        )
    logger.info(
        "m2_roster_supabase_ok schools=%s class_groups=%s enrollments=%s",
        len(out),
        sum(len(s["class_groups"]) for s in out),
        sum(len(cg["students"]) for s in out for cg in s["class_groups"]),
    )
    return out


def list_schools_from_fixtures(fixtures_path: Path | str = _DEFAULT_FIXTURES) -> list[dict[str, Any]]:
    path = Path(fixtures_path)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    schools = []
    for s in data["schools"]:
        groups = []
        for cg in s["class_groups"]:
            students = []
            for st in cg.get("students", []):
                students.append(
                    {
                        "student_id": st.get("student_id"),  # usually absent in fixtures
                        "display_name": st["display_name"],
                        "fixture_key": st.get("fixture_key"),
                        "edge_student_key": st.get("fixture_key"),
                    }
                )
            groups.append(
                {
                    "id": cg["id"],
                    "label": cg["label"],
                    "shift": cg.get("shift"),
                    "students": students,
                }
            )
        schools.append({"id": s["id"], "name": s["name"], "class_groups": groups})
    return schools


def list_schools(fixtures_path: Path | str = _DEFAULT_FIXTURES) -> tuple[str, list[dict[str, Any]]]:
    """Returns (mode, schools). Never raises for fixtures mode."""
    mode = resolve_mode()
    if mode == "supabase":
        try:
            return "supabase", list_schools_from_supabase()
        except Exception as exc:
            logger.error("m2_roster_supabase_failed err=%s", exc)
            raise
    return "fixtures", list_schools_from_fixtures(fixtures_path)


def resolve_class(
    school_id: str,
    class_group_id: str,
    *,
    fixtures_path: Path | str = _DEFAULT_FIXTURES,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Return (mode, school, class_group) or raise KeyError."""
    mode, schools = list_schools(fixtures_path)
    for school in schools:
        if school["id"] != school_id:
            continue
        for cg in school["class_groups"]:
            if cg["id"] == class_group_id:
                return mode, school, cg
    raise KeyError(f"escola/turma não encontrada: {school_id}/{class_group_id}")
