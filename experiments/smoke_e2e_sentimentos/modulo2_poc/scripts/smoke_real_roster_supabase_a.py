#!/usr/bin/env python3
"""Smoke: campanha com roster real do Supabase A + dual-write.

Carrega .env do worktree/Presenca sem imprimir secrets.
Uso:
  python scripts/smoke_real_roster_supabase_a.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def main() -> int:
    integrate_root = ROOT.parents[2]  # .../_integrate_m2_ux
    _load_dotenv(integrate_root / ".env")
    _load_dotenv(integrate_root.parent / "Presenca" / ".env")

    os.environ["M2_ROSTER_SOURCE"] = "supabase"
    os.environ.setdefault("M2_ENROLL_HMAC_SECRET", "smoke-real-hmac-secret-32bytes-xx")

    url = (os.environ.get("SUPABASE_URL") or os.environ.get("M2_OPS_SUPABASE_URL") or "").strip()
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("M2_OPS_SUPABASE_SERVICE_KEY")
        or ""
    ).strip()
    print("supabase_url_set=", bool(url))
    print("service_role_set=", bool(key))
    if not url or not key:
        print("FAIL: configure SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY no .env")
        return 2

    import enrollment_ops_sync as sync
    import enrollment_roster_source as roster
    from enrollment_store import ClaimSuccess, EnrollmentStore

    sync.reset_config_for_tests()
    assert sync.configured(), "ops sync should enable with service role"

    mode, schools = roster.list_schools()
    assert mode == "supabase", mode
    # Prefer turma com mais alunos (ex.: Escola Piloto)
    candidates = []
    for s in schools:
        for g in s["class_groups"]:
            if g.get("students"):
                candidates.append((len(g["students"]), s, g))
    if not candidates:
        print("FAIL: nenhuma turma com alunos ativos no Supabase A")
        return 3
    candidates.sort(key=lambda x: -x[0])
    _, school, cg = candidates[0]

    print("school=", school["name"], school["id"])
    print("class=", cg["label"], cg["id"], "students=", len(cg["students"]))
    for st in cg["students"]:
        assert st.get("student_id"), "student_id obrigatório"
        print("  student=", st["display_name"], st["student_id"][:8] + "…")

    db = ROOT / "results" / "enrollment_escalavel" / f"smoke_real_{int(time.time())}.db"
    store = EnrollmentStore(db)
    created = store.create_campaign(school_id=school["id"], class_group_id=cg["id"])
    print("campaign_id=", created["campaign_id"])
    print("roster_source=", created.get("roster_source"))
    print("share_path=", created["qr_path"])

    time.sleep(2.5)

    camp_id = created["campaign_id"]
    req = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/facial_enrollment_campaigns?id=eq.{camp_id}&select=id,status,school_name,class_label",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        rows = json.loads(resp.read().decode())
    print("supabase_campaign_rows=", rows)
    assert rows and rows[0]["id"] == camp_id

    req2 = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/facial_enrollment_roster?campaign_id=eq.{camp_id}&select=id,display_name,student_id,status",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req2, timeout=10) as resp:
        roster_rows = json.loads(resp.read().decode())
    print("supabase_roster_count=", len(roster_rows))
    assert len(roster_rows) == len(cg["students"])
    assert all(r.get("student_id") for r in roster_rows)

    code = created["claim_sheet"][0]["claim_code"]
    claim = store.claim(campaign_token=created["campaign_token"], claim_code=code)
    assert isinstance(claim, ClaimSuccess), claim
    time.sleep(1.5)

    req3 = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/facial_enrollment_roster?campaign_id=eq.{camp_id}&status=eq.claimed&select=id,status",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req3, timeout=10) as resp:
        claimed = json.loads(resp.read().decode())
    print("supabase_claimed=", len(claimed))
    assert len(claimed) >= 1

    print("PASS smoke_real_roster_supabase_a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
