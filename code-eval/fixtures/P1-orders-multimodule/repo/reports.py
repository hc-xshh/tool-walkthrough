"""日报查询（基线版本）。"""

import sqlite3
from pathlib import Path


def daily(data_dir, date):
    db = Path(data_dir) / "shop.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) AS orders, COALESCE(SUM(total_cents), 0) AS revenue_cents "
        "FROM orders WHERE substr(created_at, 1, 10) = ?",
        (date,),
    ).fetchone()
    conn.close()
    return {"date": date, "revenue_cents": int(row["revenue_cents"]), "orders": int(row["orders"])}
