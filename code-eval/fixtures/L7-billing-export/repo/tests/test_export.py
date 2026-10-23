import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExportTest(unittest.TestCase):
    def test_exports_paid_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "orders.json"
            dst = tmp / "out.csv"
            src.write_text(
                json.dumps(
                    [
                        {"id": "o1", "created_at": "2026-03-01", "customer": "甲", "amount": 12.3, "status": "paid"},
                        {"id": "o2", "created_at": "2026-03-02", "customer": "乙", "amount": 5, "status": "pending"},
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
        self.assertEqual(rows[0], ["id", "created_at", "customer", "amount", "status", "voided"])
        self.assertEqual([r[0] for r in rows[1:]], ["o1", "o2"])
        self.assertEqual(rows[1][3], "12.30")


if __name__ == "__main__":
    unittest.main()
