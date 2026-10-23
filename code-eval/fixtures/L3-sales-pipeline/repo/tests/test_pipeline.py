import unittest

from pipeline.importer import import_rows
from pipeline.transforms import apply_discount, mark_refund, to_money


def make_input():
    return [
        {"sku": "A-1", "unit_price": "19.99", "discount": "", "qty": "2"},
        {"sku": "A-2", "unit_price": "5.00", "discount": "10", "qty": "1"},
    ]


class PipelineTest(unittest.TestCase):
    def test_to_money_basic(self):
        row = to_money({"unit_price": "19.99"})
        self.assertEqual(row["unit_price_cents"], 1999)

    def test_discount_basic(self):
        row = apply_discount({"unit_price": "5.00", "discount": "10"})
        self.assertEqual(row["unit_price_cents"], 450)

    def test_mark_refund_basic(self):
        self.assertTrue(mark_refund({"unit_price_cents": -100})["is_refund"])
        self.assertFalse(mark_refund({"unit_price_cents": 100})["is_refund"])

    def test_import_happy_path(self):
        import tempfile
        from pathlib import Path

        csv_text = (
            "sku,unit_price,discount,qty\n"
            "A-1,19.99,,2\n"
            "A-2,5.00,10,1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text(csv_text, encoding="utf-8")
            rows, total = import_rows(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["unit_price_cents"], 1999)
        self.assertEqual(rows[1]["unit_price_cents"], 450)
        self.assertEqual(total, 1999 * 2 + 450)


if __name__ == "__main__":
    unittest.main()
