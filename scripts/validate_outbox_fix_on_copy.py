"""Validação controlada: cópia do dulino_edge.db + SyncWorker corrigido (FakeClient).

NÃO toca data/dulino_edge.db. Não apaga rows na cópia além de mark_sent nos product.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "dulino_edge.db"
OUT_DIR = ROOT / "experiments" / "smoke_e2e_sentimentos"
COPY = OUT_DIR / "dulino_edge_outbox_fix_copy.db"
REPORT = OUT_DIR / "outbox_fix_controlled_run.json"


def counts(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    cur = con.cursor()
    pending = cur.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0]
    by_type = dict(
        cur.execute(
            "SELECT event_type, COUNT(*) FROM events WHERE status='pending' GROUP BY event_type"
        ).fetchall()
    )
    product_types = (
        "class_session_upsert",
        "session_event_upsert",
        "session_report_snapshot",
        "device_heartbeat",
    )
    product_pending = sum(by_type.get(t, 0) for t in product_types)
    telemetry = sum(
        by_type.get(t, 0)
        for t in (
            "climate_window",
            "engagement_window",
            "behavioral_event",
            "attendance_checkin",
            "test",
        )
    )
    con.close()
    return {
        "pending_total": pending,
        "product_pending": product_pending,
        "telemetry_pending": telemetry,
        "pending_by_type": by_type,
    }


def main() -> None:
    assert SRC.exists(), f"missing {SRC}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if COPY.exists():
        COPY.unlink()
    shutil.copy2(SRC, COPY)

    before = counts(COPY)

    import os

    os.environ["SQLITE_PATH"] = str(COPY)
    from app.config import reload_settings
    from app.db.init_db import reset_db_singleton, get_session, close_session
    from app.db.repo import EventRepository
    from app.sync.worker import SyncWorker

    class CaptureClient:
        def __init__(self):
            self.sent = []

        async def send_event(self, payload):
            self.sent.append(payload)
            return True

    reset_db_singleton()
    reload_settings()
    client = CaptureClient()
    worker = SyncWorker(client=client)
    worker.batch_size = 50
    worker.retry_backoff = 0

    # drain product lane
    rounds = 0
    while rounds < 20:
        before_round = len(client.sent)
        asyncio.run(worker.sync_batch())
        rounds += 1
        if len(client.sent) == before_round:
            break

    after = counts(COPY)
    session = get_session()
    try:
        lanes = EventRepository(session).get_outbox_lane_stats()
    finally:
        close_session(session)

    # verify no deletes: total rows same
    con = sqlite3.connect(str(COPY))
    total_rows = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    src_total = sqlite3.connect(str(SRC)).execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con.close()

    report = {
        "source_db": str(SRC),
        "copy_db": str(COPY),
        "before": before,
        "after": after,
        "lanes_after": lanes,
        "sync_rounds": rounds,
        "product_synced": len(client.sent),
        "synced_types": {
            t: sum(1 for p in client.sent if p.get("event_type") == t)
            for t in sorted({p.get("event_type") for p in client.sent})
        },
        "row_count_unchanged": total_rows == src_total,
        "source_row_count": src_total,
        "copy_row_count": total_rows,
        "telemetry_still_pending": after["telemetry_pending"] == before["telemetry_pending"],
        "product_drained": after["product_pending"] == 0,
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
