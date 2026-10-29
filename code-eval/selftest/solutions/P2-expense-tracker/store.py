"""参考解：记账应用的数据层（SQLite，标准库）。"""

import csv
import io
import re
import sqlite3
from datetime import date
from pathlib import Path

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = self.data_dir / "expenses.db"
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS expenses ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "amount_cents INTEGER NOT NULL, "
                "category TEXT NOT NULL, "
                "spent_on TEXT NOT NULL, "
                "note TEXT NOT NULL DEFAULT '')"
            )

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _check_month(month):
        if not isinstance(month, str) or not MONTH_RE.fullmatch(month):
            raise ValueError("month must be YYYY-MM")

    @staticmethod
    def _row(row):
        return {
            "id": row["id"],
            "amount_cents": row["amount_cents"],
            "category": row["category"],
            "spent_on": row["spent_on"],
            "note": row["note"],
        }

    def create_expense(self, body):
        if not isinstance(body, dict):
            raise ValueError("body must be an object")
        amount = body.get("amount_cents")
        if type(amount) is not int or amount <= 0:
            raise ValueError("amount_cents must be a positive integer")
        category = body.get("category")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category is required")
        spent_on = body.get("spent_on")
        if not isinstance(spent_on, str):
            raise ValueError("spent_on is required")
        try:
            date.fromisoformat(spent_on)
        except ValueError as exc:
            raise ValueError("spent_on must be YYYY-MM-DD") from exc
        if len(spent_on) != 10:
            raise ValueError("spent_on must be YYYY-MM-DD")
        note = body.get("note", "")
        if note is None:
            note = ""
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO expenses(amount_cents, category, spent_on, note) VALUES (?, ?, ?, ?)",
                (amount, category.strip(), spent_on, note.strip()),
            )
            expense_id = cur.lastrowid
        return self.get_expense(expense_id)

    def get_expense(self, expense_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if not row:
            return None
        return self._row(row)

    def list_expenses(self, month=None):
        sql = "SELECT * FROM expenses"
        args = []
        if month:
            self._check_month(month)
            sql += " WHERE spent_on LIKE ?"
            args.append(month + "-%")
        sql += " ORDER BY spent_on DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._row(row) for row in rows]

    def summary(self, month=None):
        if month:
            self._check_month(month)
        rows = self.list_expenses(month)
        total = sum(row["amount_cents"] for row in rows)
        grouped = {}
        for row in rows:
            item = grouped.setdefault(row["category"], {"category": row["category"], "total_cents": 0, "count": 0})
            item["total_cents"] += row["amount_cents"]
            item["count"] += 1
        by_category = sorted(grouped.values(), key=lambda x: (-x["total_cents"], x["category"]))
        return {"month": month, "total_cents": total, "by_category": by_category}

    def delete_expense(self, expense_id):
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return cur.rowcount > 0

    def export_csv(self, month=None):
        rows = self.list_expenses(month)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["id", "spent_on", "category", "amount_cents", "note"])
        for row in rows:
            writer.writerow([row["id"], row["spent_on"], row["category"], row["amount_cents"], row["note"]])
        return out.getvalue()
