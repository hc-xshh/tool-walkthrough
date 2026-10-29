"""可见测试：小数据上的口径。"""

import unittest
from pathlib import Path

from reports.aggregate import aggregate, load_orders, load_rates

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


class AggregateTest(unittest.TestCase):
    def test_small_report(self):
        result = aggregate(
            load_orders(REPO / "data" / "orders.csv"),
            load_rates(REPO / "data" / "rates.csv"),
        )
        self.assertEqual(result["days"], {
            "2026-01-02": {"USD": "142.00"},
            "2026-01-03": {"USD": "35.50"},
            "2026-01-05": {"EUR": "46.92", "CNY": "1.00"},
        })
        self.assertEqual(result["top_customers"], [["alice", 2], ["bob", 1], ["carol", 1]])


if __name__ == "__main__":
    unittest.main()
