"""L4 隐藏验收：跨时区归月、非交易日汇率、重复 id 去重、月度总额。"""

import unittest
from datetime import date
from pathlib import Path

from ledger.fx import load_rates, rate_for
from ledger.load import read_dir
from ledger.parse import parse_timestamp
from ledger.report import monthly_report

DATA = Path(__file__).resolve().parents[1] / "data"
RATES = load_rates(DATA / "rates.json")


class LedgerAccept(unittest.TestCase):
    def test_month_uses_record_local_date(self):
        self.assertEqual(parse_timestamp("2026-03-31T20:30:00-05:00"), date(2026, 3, 31))
        self.assertEqual(parse_timestamp("2026-04-01T02:00:00+08:00"), date(2026, 4, 1))
        self.assertEqual(parse_timestamp("2026-03-31"), date(2026, 3, 31))

    def test_weekend_uses_previous_business_day_rate(self):
        self.assertEqual(rate_for(RATES, date(2026, 3, 7), "USD"), 7.12)
        self.assertEqual(rate_for(RATES, date(2026, 3, 8), "USD"), 7.12)
        self.assertEqual(rate_for(RATES, date(2026, 3, 9), "USD"), 7.15)

    def test_cny_is_one(self):
        self.assertEqual(rate_for(RATES, date(2026, 3, 7), "CNY"), 1.0)

    def test_duplicate_ids_collapse_and_amend_wins(self):
        entries = read_dir(DATA)
        ids = [e.id for e in entries]
        self.assertEqual(len(ids), len(set(ids)), f"重复 id: {ids}")
        amended = next(e for e in entries if e.id == "e4")
        self.assertEqual(amended.amount, 120.0)

    def test_entries_land_in_the_right_month(self):
        entries = read_dir(DATA)
        by_id = {e.id: e for e in entries}
        self.assertEqual(by_id["e3"].day, date(2026, 3, 31))
        self.assertEqual(by_id["e5"].day, date(2026, 4, 1))

    def test_march_total(self):
        report = monthly_report(read_dir(DATA), "2026-03", RATES)
        self.assertEqual(report["count"], 4)
        self.assertEqual(report["total_cents"], 64800)

    def test_april_total(self):
        report = monthly_report(read_dir(DATA), "2026-04", RATES)
        self.assertEqual(report["count"], 2)
        self.assertEqual(report["total_cents"], 115700)

    def test_by_currency(self):
        report = monthly_report(read_dir(DATA), "2026-03", RATES)
        self.assertEqual(report["by_currency"], {"CNY": 220.0, "USD": 60.0})


if __name__ == "__main__":
    unittest.main()
