"""参考解：日报只统计未取消订单，同时返回取消订单数。"""

import sqlite3
from pathlib import Path


def daily(data_dir, date):
    conn = sqlite3.connect(Path(data_dir) / "shop.db")
    conn.row_factory = sqlite3.Row
    active = conn.execute(
        "SELECT COUNT(*) AS orders, COALESCE(SUM(total_cents), 0) AS revenue_cents "
        "FROM orders WHERE substr(created_at, 1, 10) = ? AND status != 'cancelled'",
        (date,),
    ).fetchone()
    cancelled = conn.execute(
        "SELECT COUNT(*) AS n FROM orders "
        "WHERE substr(created_at, 1, 10) = ? AND status = 'cancelled'",
        (date,),
    ).fetchone()
    conn.close()
    return {
        "date": date,
        "revenue_cents": int(active["revenue_cents"]),
        "orders": int(active["orders"]),
        "cancelled_orders": int(cancelled["n"]),
    }
