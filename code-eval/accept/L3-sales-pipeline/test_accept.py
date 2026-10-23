"""L3 隐藏验收：金额换算、退款/赠品保留、汇总。"""

import csv
import tempfile
import unittest
from pathlib import Path

from pipeline.importer import import_rows
from pipeline.sources import read_rows
from pipeline.transforms import apply_discount, mark_refund, to_money

ROWS = [
    {"sku": "A-1", "unit_price": "12.345", "discount": "", "qty": "1"},
    {"sku": "A-2", "unit_price": "0", "discount": "", "qty": "3"},
    {"sku": "R-1", "unit_price": "-1", "discount": "", "qty": "1"},
    {"sku": "D-1", "unit_price": "12.345", "discount": "10", "qty": "2"},
]


class PipelineAccept(unittest.TestCase):
    def run_import(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=["sku", "unit_price", "discount", "qty"]
                )
                writer.writeheader()
                writer.writerows(rows)
            return import_rows(path)

    def test_half_up_rounding(self):
        self.assertEqual(to_money({"unit_price": "12.345"})["unit_price_cents"], 1235)
        self.assertEqual(to_money({"unit_price": "12.344"})["unit_price_cents"], 1234)
        self.assertEqual(to_money({"unit_price": "0.005"})["unit_price_cents"], 1)

    def test_discount_then_half_up(self):
        row = apply_discount({"unit_price": "12.345", "discount": "10"})
        self.assertEqual(row["unit_price_cents"], 1111)

    def test_mark_refund(self):
        self.assertTrue(mark_refund({"unit_price_cents": -100})["is_refund"])
        self.assertFalse(mark_refund({"unit_price_cents": 0})["is_refund"])

    def test_source_rows_are_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.csv"
            path.write_text(" sku , unit_price \n A , 1.00 \n", encoding="utf-8")
            rows = list(read_rows(path))
        self.assertEqual(rows[0]["sku"], "A")
        self.assertEqual(rows[0]["unit_price"], "1.00")

    def test_refund_kept_and_flagged(self):
        rows, _ = self.run_import(ROWS)
        refunds = [r for r in rows if r["sku"] == "R-1"]
        self.assertEqual(len(refunds), 1, "退款行被丢掉了")
        self.assertTrue(refunds[0]["is_refund"])

    def test_free_row_kept(self):
        rows, _ = self.run_import(ROWS)
        free = [r for r in rows if r["sku"] == "A-2"]
        self.assertEqual(len(free), 1, "0 价赠品行被丢掉了")
        self.assertEqual(free[0]["unit_price_cents"], 0)

    def test_all_rows_kept_and_total(self):
        rows, total = self.run_import(ROWS)
        self.assertEqual(len(rows), 4)
        expected = 1235 * 1 + 0 * 3 + (-100) * 1 + 1111 * 2
        self.assertEqual(total, expected)

    def test_no_rows_dropped_flag_leaks(self):
        rows, _ = self.run_import(ROWS)
        self.assertFalse(any(r.get("_drop") for r in rows))


if __name__ == "__main__":
    unittest.main()
