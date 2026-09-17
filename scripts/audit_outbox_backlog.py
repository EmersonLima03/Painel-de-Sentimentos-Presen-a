"""Auditoria read-only do backlog outbox em dulino_edge.db. Não modifica nada."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "dulino_edge.db"
OUT = ROOT / "experiments" / "smoke_e2e_sentimentos" / "backlog_audit.json"


def main() -> None:
    con = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    report: dict = {
        "db_path": str(DB.resolve()),
        "db_size_mb": round(DB.stat().st_size / 1024 / 1024, 3),
        "page_count": cur.execute("PRAGMA page_count").fetchone()[0],
        "page_size": cur.execute("PRAGMA page_size").fetchone()[0],
        "freelist_count": cur.execute("PRAGMA freelist_count").fetchone()[0],
    }

    def q(sql: str, args=()):
        return [dict(r) for r in cur.execute(sql, args).fetchall()]

    report["by_status"] = q(
        "SELECT status, COUNT(*) AS n FROM events GROUP BY status ORDER BY n DESC"
    )
    report["pending_by_type"] = q(
        """
        SELECT event_type, COUNT(*) AS n
        FROM events WHERE status='pending'
        GROUP BY event_type ORDER BY n DESC
        """
    )
    report["all_type_status"] = q(
        """
        SELECT event_type, status, COUNT(*) AS n
        FROM events GROUP BY event_type, status
        ORDER BY event_type, status
        """
    )
    report["pending_range"] = q(
        """
        SELECT MIN(created_at) AS min_created, MAX(created_at) AS max_created, COUNT(*) AS n
        FROM events WHERE status='pending'
        """
    )[0]
    report["pending_by_day"] = q(
        """
        SELECT date(created_at) AS day, COUNT(*) AS n
        FROM events WHERE status='pending'
        GROUP BY date(created_at) ORDER BY day
        """
    )
    report["pending_by_day_type"] = q(
        """
        SELECT date(created_at) AS day, event_type, COUNT(*) AS n
        FROM events WHERE status='pending'
        GROUP BY date(created_at), event_type
        ORDER BY day, event_type
        """
    )
    report["retries_pending"] = q(
        """
        SELECT retries, COUNT(*) AS n
        FROM events WHERE status='pending'
        GROUP BY retries ORDER BY retries
        """
    )
    report["failed_by_type"] = q(
        """
        SELECT event_type, COUNT(*) AS n, ROUND(AVG(retries),2) AS avg_retries
        FROM events WHERE status='failed'
        GROUP BY event_type ORDER BY n DESC
        """
    )
    report["product_pending"] = q(
        """
        SELECT event_type, COUNT(*) AS n, MIN(created_at) AS min_c, MAX(created_at) AS max_c
        FROM events
        WHERE status='pending'
          AND event_type IN (
            'class_session_upsert','session_event_upsert',
            'session_report_snapshot','device_heartbeat'
          )
        GROUP BY event_type
        """
    )
    report["oldest_pending"] = q(
        """
        SELECT event_id, event_type, created_at, retries, length(payload_json) AS payload_bytes
        FROM events WHERE status='pending'
        ORDER BY created_at ASC LIMIT 20
        """
    )
    report["newest_pending"] = q(
        """
        SELECT event_id, event_type, created_at, retries
        FROM events WHERE status='pending'
        ORDER BY created_at DESC LIMIT 20
        """
    )
    report["payload_bytes_pending"] = q(
        """
        SELECT event_type,
               COUNT(*) AS n,
               SUM(length(payload_json)) AS bytes,
               ROUND(AVG(length(payload_json)),1) AS avg_bytes,
               MAX(length(payload_json)) AS max_bytes
        FROM events WHERE status='pending'
        GROUP BY event_type ORDER BY bytes DESC
        """
    )
    for row in report["payload_bytes_pending"]:
        row["mb"] = round((row["bytes"] or 0) / 1024 / 1024, 3)

    # Prefix of oldest pending types (starvation simulation)
    oldest_batch = q(
        """
        SELECT event_type, COUNT(*) AS n FROM (
          SELECT event_type FROM events
          WHERE status='pending'
          ORDER BY created_at ASC LIMIT 10
        ) GROUP BY event_type
        """
    )
    report["oldest_10_pending_composition"] = oldest_batch

    oldest_100 = q(
        """
        SELECT event_type, COUNT(*) AS n FROM (
          SELECT event_type FROM events
          WHERE status='pending'
          ORDER BY created_at ASC LIMIT 100
        ) GROUP BY event_type
        """
    )
    report["oldest_100_pending_composition"] = oldest_100

    # How many pending before first product event?
    first_product = q(
        """
        SELECT event_id, event_type, created_at FROM events
        WHERE status='pending'
          AND event_type IN (
            'class_session_upsert','session_event_upsert',
            'session_report_snapshot','device_heartbeat'
          )
        ORDER BY created_at ASC LIMIT 1
        """
    )
    report["first_product_pending"] = first_product[0] if first_product else None
    if first_product:
        ahead = q(
            """
            SELECT COUNT(*) AS n FROM events
            WHERE status='pending' AND created_at < ?
            """,
            (first_product[0]["created_at"],),
        )[0]["n"]
        report["pending_ahead_of_first_product"] = ahead
    else:
        report["pending_ahead_of_first_product"] = None

    # sample last_error for failed
    report["sample_failed_errors"] = q(
        """
        SELECT event_type, last_error, COUNT(*) AS n
        FROM events WHERE status='failed'
        GROUP BY event_type, last_error
        ORDER BY n DESC LIMIT 10
        """
    )

    # sent counts for comparison
    report["sent_by_type"] = q(
        """
        SELECT event_type, COUNT(*) AS n
        FROM events WHERE status='sent'
        GROUP BY event_type ORDER BY n DESC
        """
    )

    # position: count climate/engagement older than newest product
    report["telemetry_pending_total"] = q(
        """
        SELECT COUNT(*) AS n FROM events
        WHERE status='pending'
          AND event_type IN ('climate_window','engagement_window')
        """
    )[0]["n"]

    con.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
