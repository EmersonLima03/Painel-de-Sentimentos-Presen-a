import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parents[1] / "data" / "dulino_edge.db"
c = sqlite3.connect(db)
print("lxp by status:", c.execute(
    "select status, count(*) from events where event_type='lxp_attendance_event' group by status"
).fetchall())
rows = c.execute(
    "select event_id, status, retries, payload_json from events "
    "where event_type='lxp_attendance_event' order by id desc limit 5"
).fetchall()
for r in rows:
    print(r[0], r[1], r[2], (r[3] or "")[:240])
