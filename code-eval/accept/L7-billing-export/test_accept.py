"""L7 隐藏验收：128 个文件里定位到真正的 CSV 导出器，作废单不能丢。"""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.exporters.csv import export_csv

ROOT = Path(__file__).resolve().parents[1]
HEADER = ["id", "created_at", "customer", "amount", "status", "voided"]


def order(oid, status, amount="10.00", customer="客户"):
    return {
        "id": oid,
        "created_at": "2026-03-01",
        "customer": customer,
        "amount": float(amount),
        "status": status,
    }


class ExportAccept(unittest.TestCase):
    def run_export(self, orders):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            export_csv(orders, path)
            return list(csv.reader(path.read_text(encoding="utf-8").splitlines()))

    def test_header_is_stable(self):
        rows = self.run_export([])
        self.assertEqual(rows[0], HEADER)
        self.assertEqual(len(rows), 1, "空订单也要有表头")

    def test_void_rows_are_kept_and_flagged(self):
        rows = self.run_export([order("o1", "paid"), order("o2", "void"), order("o3", "pending")])
        self.assertEqual([r[0] for r in rows[1:]], ["o1", "o2", "o3"], "作废单被丢掉了")
        by_id = {r[0]: r for r in rows[1:]}
        self.assertEqual(by_id["o2"][5], "1")
        self.assertEqual(by_id["o1"][5], "0")
        self.assertEqual(by_id["o3"][5], "0")

    def test_refunded_and_cancelled_are_not_dropped(self):
        rows = self.run_export([order("r1", "refunded"), order("c1", "cancelled")])
        self.assertEqual([r[0] for r in rows[1:]], ["r1", "c1"])

    def test_amount_keeps_two_decimals(self):
        rows = self.run_export([order("a1", "paid", amount="12.3"), order("a2", "void", amount="5")])
        self.assertEqual(rows[1][3], "12.30")
        self.assertEqual(rows[2][3], "5.00")

    def test_order_is_preserved(self):
        rows = self.run_export([order(f"o{i}", "paid") for i in range(1, 6)])
        self.assertEqual([r[0] for r in rows[1:]], ["o1", "o2", "o3", "o4", "o5"])

    def test_unicode_customer_survives(self):
        rows = self.run_export([order("u1", "void", customer="深圳甲公司")])
        self.assertEqual(rows[1][2], "深圳甲公司")

    def test_cli_export_includes_void_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "orders.json"
            dst = tmp / "out.csv"
            src.write_text(
                json.dumps(
                    [
                        {"id": "o1", "created_at": "2026-03-01", "customer": "甲", "amount": 10, "status": "paid"},
                        {"id": "o2", "created_at": "2026-03-02", "customer": "乙", "amount": 20, "status": "void"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            res = subprocess.run(
                [sys.executable, "-m", "app.cli", "export", "--in", str(src), "--out", str(dst)],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            rows = list(csv.reader(dst.read_text(encoding="utf-8").splitlines()))
        self.assertEqual([r[0] for r in rows[1:]], ["o1", "o2"])
        self.assertEqual(rows[2][5], "1")


if __name__ == "__main__":
    unittest.main()
