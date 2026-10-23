import unittest
from datetime import date
from pathlib import Path

from ledger.fx import load_rates, rate_for
from ledger.models import Entry
from ledger.parse import read_entries
from ledger.report import monthly_report

ROOT = Path(__file__).resolve().parents[1]


class LedgerTest(unittest.TestCase):
    def test_parse_plain_date(self):
        from ledger.parse import parse_timestamp

        self.assertEqual(parse_timestamp("2026-03-15"), date(2026, 3, 15))

    def test_cny_rate_is_one(self):
        self.assertEqual(rate_for({}, date(2026, 3, 6), "CNY"), 1.0)

    def test_report_all_cny(self):
        entries = [
            Entry(id="a", day=date(2026, 3, 6), amount=100.0, currency="CNY"),
            Entry(id="b", day=date(2026, 3, 9), amount=50.5, currency="CNY"),
        ]
        report = monthly_report(entries, "2026-03", {})
        self.assertEqual(report["count"], 2)
        self.assertEqual(report["total_cents"], 15050)

    def test_read_entries_one_file(self):
        rows = list(read_entries(ROOT / "data" / "2026-03.csv"))
        self.assertTrue(rows)
        self.assertEqual(rows[0].id, "e1")

    def test_rates_file_loads(self):
        rates = load_rates(ROOT / "data" / "rates.json")
        self.assertIn("USD", rates)


if __name__ == "__main__":
    unittest.main()
