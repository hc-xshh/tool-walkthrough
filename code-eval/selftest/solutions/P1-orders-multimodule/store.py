"""参考解：把取消订单做成一个跨库存、订单和审计的事务。"""

from datetime import datetime
import sqlite3
from pathlib import Path


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    sku TEXT PRIMARY KEY,
    total INTEGER NOT NULL,
    reserved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer TEXT NOT NULL,
    status TEXT NOT NULL,
    total_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    order_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cents INTEGER NOT NULL,
    PRIMARY KEY (order_id, sku)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    event TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

SEED = [("A", 10, 3), ("B", 5, 1)]
SEED_ORDERS = [
    ("O-1001", "林记小馆", "paid", 1200, "2026-10-28T09:15:00+08:00"),
    ("O-1002", "阿岚杂货", "shipped", 300, "2026-10-28T14:20:00+08:00"),
]
SEED_ITEMS = [("O-1001", "A", 2, 500), ("O-1001", "B", 1, 200), ("O-1002", "A", 1, 300)]


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = self.data_dir / "shop.db"
        self.init()

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
            if "cancelled_at" not in columns:
                conn.execute("ALTER TABLE orders ADD COLUMN cancelled_at TEXT")
            if not conn.execute("SELECT 1 FROM inventory LIMIT 1").fetchone():
                conn.executemany("INSERT INTO inventory(sku, total, reserved) VALUES (?, ?, ?)", SEED)
            if not conn.execute("SELECT 1 FROM orders LIMIT 1").fetchone():
                conn.executemany(
                    "INSERT INTO orders(id, customer, status, total_cents, created_at) VALUES (?, ?, ?, ?, ?)",
                    SEED_ORDERS,
                )
                conn.executemany(
                    "INSERT INTO order_items(order_id, sku, qty, unit_cents) VALUES (?, ?, ?, ?)",
                    SEED_ITEMS,
                )

    def get_order(self, order_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not row:
                raise NotFound(order_id)
            items = conn.execute(
                "SELECT sku, qty, unit_cents FROM order_items WHERE order_id = ? ORDER BY sku",
                (order_id,),
            ).fetchall()
        result = dict(row)
        result["items"] = [
            {"sku": item["sku"], "qty": item["qty"], "unit_cents": item["unit_cents"]}
            for item in items
        ]
        return result

    def list_orders(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

    def inventory(self, sku):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM inventory WHERE sku = ?", (sku,)).fetchone()
        if not row:
            raise NotFound(sku)
        return {
            "sku": row["sku"], "total": row["total"], "reserved": row["reserved"],
            "available": row["total"] - row["reserved"],
        }

    def audit(self, order_id):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT order_id, event, created_at FROM audit_log WHERE order_id = ? ORDER BY id",
                (order_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_order(self, order_id):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, status FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            if not row:
                raise NotFound(order_id)
            if row["status"] == "cancelled":
                conn.rollback()
                return self.get_order(order_id)
            if row["status"] != "paid":
                raise Conflict("order_not_cancellable")
            items = conn.execute(
                "SELECT sku, qty FROM order_items WHERE order_id = ?", (order_id,)
            ).fetchall()
            stamp = now()
            for item in items:
                conn.execute(
                    "UPDATE inventory SET reserved = MAX(0, reserved - ?) WHERE sku = ?",
                    (item["qty"], item["sku"]),
                )
            conn.execute(
                "UPDATE orders SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
                (stamp, order_id),
            )
            conn.execute(
                "INSERT INTO audit_log(order_id, event, created_at) VALUES (?, ?, ?)",
                (order_id, "order_cancelled", stamp),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get_order(order_id)
