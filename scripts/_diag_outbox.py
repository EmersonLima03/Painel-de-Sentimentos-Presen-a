import json
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parents[1] / "data" / "dulino_edge.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'").fetchall()]
print("tables", tabs)
for t in tabs:
    if "event" in t.lower() or "outbox" in t.lower():
        cols = [c[1] for c in con.execute(f"pragma table_info({t})")]
        print("==", t, cols)
        try:
            rows = con.execute(f"select * from {t} order by rowid desc limit 8").fetchall()
            for r in rows:
                d = dict(r)
                for k, v in list(d.items()):
                    if isinstance(v, str) and len(v) > 220:
                        d[k] = v[:220] + "..."
                print(json.dumps(d, ensure_ascii=False)[:600])
        except Exception as e:
            print("err", e)
