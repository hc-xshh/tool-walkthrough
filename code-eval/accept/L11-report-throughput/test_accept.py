"""L11 隐藏验收：输出口径 + 8000 行吞吐预算。"""

import json
import random
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUDGET_S = 3.0
CURRENCIES = ["USD", "EUR", "JPY", "CNY"]


def business_days(start, count):
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def write_dataset(root, orders, rates):
    orders_path = root / "orders.csv"
    rates_path = root / "rates.csv"
    with orders_path.open("w", encoding="utf-8") as fh:
        fh.write("id,date,customer,currency,qty,price_cents\n")
        for order in orders:
            fh.write("{id},{date},{customer},{currency},{qty},{price_cents}\n".format(**order))
    with rates_path.open("w", encoding="utf-8") as fh:
        fh.write("date,currency,rate\n")
        for day, currency, rate in rates:
            fh.write(f"{day},{currency},{rate}\n")
    return orders_path, rates_path


def expected_report(orders, rates):
    index = {}
    for day, currency, rate in rates:
        key = (currency, day)
        if key not in index or day > index[key][0]:
            index[key] = (day, rate)
    by_currency = {}
    for currency, day in index:
        by_currency.setdefault(currency, []).append((day, index[(currency, day)][1]))
    for currency in by_currency:
        by_currency[currency].sort()

    days = {}
    counts = {}
    for order in orders:
        candidates = [item for item in by_currency.get(order["currency"], []) if item[0] <= order["date"]]
        if not candidates:
            raise KeyError(order["currency"])
        rate = candidates[-1][1]
        amount = (
            Decimal(order["price_cents"]) * order["qty"] * rate
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        days.setdefault(order["date"], {})
        days[order["date"]][order["currency"]] = (
            days[order["date"]].get(order["currency"], Decimal("0")) + amount
        )
        counts[order["customer"]] = counts.get(order["customer"], 0) + 1

    out = {
        "days": {
            day: {
                currency: str((total / 100).quantize(Decimal("0.01")))
                for currency, total in currencies.items()
            }
            for day, currencies in days.items()
        },
        "top_customers": [
            [name, count]
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
        ],
    }
    return out


class ReportAccept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        rng = random.Random(20261029)
        weekdays = business_days(date(2026, 1, 1), 40)
        rates = []
        for i, day in enumerate(weekdays):
            for j, currency in enumerate(CURRENCIES):
                base = Decimal("1.00") if currency == "CNY" else Decimal("7.00") + Decimal(j) / 10
                rate = (base + Decimal(i % 7) / 100).quantize(Decimal("0.0001"))
                rates.append((day.isoformat(), currency, rate))

        orders = []
        for i in range(8000):
            # 1/10 的订单落在周末，验证「用上一个工作日汇率」
            day = weekdays[rng.randrange(len(weekdays))]
            if i % 10 == 0:
                # 强制落在周六：汇率应回落到周五
                day = day + timedelta(days=(5 - day.weekday()))
            orders.append({
                "id": f"o{i}",
                "date": day.isoformat(),
                "customer": f"c{rng.randrange(400):03d}",
                "currency": CURRENCIES[rng.randrange(len(CURRENCIES))],
                "qty": rng.randrange(1, 6),
                "price_cents": rng.randrange(100, 5000),
            })
        cls.orders = orders
        cls.rates = rates
        cls.expected = expected_report(orders, rates)
        cls.orders_path, cls.rates_path = write_dataset(cls.tmp, orders, rates)

        started = time.time()
        proc = subprocess.run(
            [sys.executable, "-m", "reports.cli", "--input", str(cls.orders_path),
             "--rates", str(cls.rates_path), "--out", str(cls.tmp / "out.json")],
            cwd=str(REPO), capture_output=True, text=True, timeout=60,
        )
        cls.elapsed = time.time() - started
        cls.proc = proc
        cls.output = None
        if proc.returncode == 0 and (cls.tmp / "out.json").exists():
            cls.output = json.loads((cls.tmp / "out.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_large_report_matches_reference(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-1200:])
        self.assertIsNotNone(self.output, "CLI 没有写出 out.json")
        self.assertEqual(self.output, self.expected)

    def test_large_report_within_budget(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-1200:])
        self.assertLess(self.elapsed, BUDGET_S,
                        f"8000 行耗时 {self.elapsed:.2f}s，预算 {BUDGET_S}s")

    def test_weekend_uses_previous_business_day_and_half_up(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            orders = [
                {"id": "a", "date": "2026-01-03", "customer": "x", "currency": "USD",
                 "qty": 1, "price_cents": 1005},
                {"id": "b", "date": "2026-01-05", "customer": "y", "currency": "EUR",
                 "qty": 2, "price_cents": 333},
            ]
            rates = [
                ("2026-01-02", "USD", Decimal("7.1000")),
                ("2026-01-05", "USD", Decimal("7.2000")),
                ("2026-01-02", "EUR", Decimal("7.8000")),
            ]
            paths = write_dataset(tmp, orders, rates)
            out = tmp / "out.json"
            proc = subprocess.run(
                [sys.executable, "-m", "reports.cli", "--input", str(paths[0]),
                 "--rates", str(paths[1]), "--out", str(out)],
                cwd=str(REPO), capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), expected_report(orders, rates))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unknown_currency_exits_2(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            orders = [{"id": "a", "date": "2026-01-05", "customer": "x", "currency": "GBP",
                       "qty": 1, "price_cents": 100}]
            rates = [("2026-01-05", "USD", Decimal("7.10"))]
            paths = write_dataset(tmp, orders, rates)
            proc = subprocess.run(
                [sys.executable, "-m", "reports.cli", "--input", str(paths[0]),
                 "--rates", str(paths[1]), "--out", str(tmp / "out.json")],
                cwd=str(REPO), capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 2, proc.stdout[-400:] + proc.stderr[-400:])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
