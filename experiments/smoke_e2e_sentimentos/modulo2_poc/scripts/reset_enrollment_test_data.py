#!/usr/bin/env python3
"""Reset SAFE de dados de teste de enrollment facial (lab apenas).

NÃO roda automaticamente. NÃO tem botão no Dashboard.

Uso:
  set M2_RESET_CONFIRM=RESET-ENROLLMENT-TEST
  set M2_RESET_ENV=lab
  python scripts/reset_enrollment_test_data.py --dry-run
  python scripts/reset_enrollment_test_data.py --execute

O que pode remover (somente com --execute + flags):
  - SQLite local do M2 (campaigns/roster/sessions/student_facial_status)
  - gallery_temp/enrollment_campaigns/*
  - (opcional) facial_student_enrollments / facial_enrollment_* no Supabase A
    apenas para student_id de homologação (Homolog Edge p0x), NUNCA em massa

Nunca toca Supabase B.
Nunca apaga schools/class_groups/students/enrollments oficiais.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


HOMOLOG_STUDENT_IDS = (
    "44444444-4444-4444-4444-444444444411",  # p01
    "44444444-4444-4444-4444-444444444412",  # p02
    "44444444-4444-4444-4444-444444444413",  # p03
)


def main() -> int:
    p = argparse.ArgumentParser(description="Reset enrollment test data (explicit only)")
    p.add_argument("--dry-run", action="store_true", help="Show what would be removed")
    p.add_argument("--execute", action="store_true", help="Actually delete (requires env)")
    p.add_argument("--sqlite", action="store_true", help="Clear local M2 SQLite enrollment DB")
    p.add_argument("--gallery-temp", action="store_true", help="Clear TEMP gallery campaigns")
    p.add_argument(
        "--supabase-homolog",
        action="store_true",
        help="Delete homolog facial_* rows for p01/p02/p03 only on Supabase A",
    )
    args = p.parse_args()

    env_name = (os.environ.get("M2_RESET_ENV") or "").strip().lower()
    confirm = (os.environ.get("M2_RESET_CONFIRM") or "").strip()

    print("=== reset_enrollment_test_data ===")
    print(f"env M2_RESET_ENV={env_name or '(unset)'}")
    print(f"confirm set={bool(confirm)}")
    print(f"dry_run={args.dry_run} execute={args.execute}")

    if env_name in ("prod", "production"):
        print("REFUSED: M2_RESET_ENV=production — use lab/staging only.")
        return 2
    if args.execute and confirm != "RESET-ENROLLMENT-TEST":
        print("REFUSED: set M2_RESET_CONFIRM=RESET-ENROLLMENT-TEST to execute.")
        return 2
    if not args.dry_run and not args.execute:
        print("Nothing to do. Pass --dry-run or --execute.")
        return 1

    from poc_common import GALLERY
    from enrollment_store import DEFAULT_DB_PATH

    targets = []
    if args.sqlite or (not args.gallery_temp and not args.supabase_homolog):
        targets.append(("sqlite", Path(DEFAULT_DB_PATH)))
    if args.gallery_temp or (not args.sqlite and not args.supabase_homolog):
        targets.append(("gallery_temp", GALLERY / "enrollment_campaigns"))

    for kind, path in targets:
        exists = path.exists()
        print(f"[{kind}] {path} exists={exists}")
        if args.execute and exists:
            if path.is_file():
                path.unlink()
                print(f"  deleted file")
            else:
                shutil.rmtree(path)
                path.mkdir(parents=True, exist_ok=True)
                print(f"  cleared directory")

    if args.supabase_homolog:
        try:
            import enrollment_ops_sync as sync
        except ImportError:
            print("[supabase] ops_sync unavailable")
            return 1
        if not sync.configured():
            print("[supabase] not configured — skip")
        else:
            print(f"[supabase-A] would clear facial_* for {len(HOMOLOG_STUDENT_IDS)} homolog ids")
            if args.execute:
                for sid in HOMOLOG_STUDENT_IDS:
                    # Best-effort: status revoke only (no DROP of official students)
                    sync.upsert_student_facial_status(
                        student_id=sid,
                        edge_student_key="",
                        status="revoked",
                        completed_at=None,
                    )
                    print(f"  revoked facial status student_id={sid}")

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
