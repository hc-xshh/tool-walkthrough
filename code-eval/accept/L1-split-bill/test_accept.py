"""L1 隐藏验收：split_bill 的边界与不变量。"""

import unittest

from money import split_bill


class SplitBillAccept(unittest.TestCase):
    def assert_valid(self, parts, total, n):
        self.assertIsInstance(parts, list)
        self.assertEqual(len(parts), n)
        for p in parts:
            self.assertIsInstance(p, int)
        self.assertEqual(sum(parts), total)
        if n > 0:
            self.assertLessEqual(max(parts) - min(parts), 1)

    def test_uneven_split(self):
        self.assert_valid(split_bill(1000, 3), 1000, 3)

    def test_worst_case_remainder(self):
        amount = 10**9 + 7
        self.assert_valid(split_bill(amount, 7), amount, 7)

    def test_more_people_than_cents(self):
        self.assert_valid(split_bill(1, 3), 1, 3)

    def test_zero_amount_many_people(self):
        self.assert_valid(split_bill(0, 5), 0, 5)

    def test_single_person_keeps_everything(self):
        self.assertEqual(split_bill(123456, 1), [123456])

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValueError):
            split_bill(-1, 3)

    def test_non_positive_people_rejected(self):
        for people in (0, -1):
            with self.assertRaises(ValueError):
                split_bill(100, people)

    def test_deterministic(self):
        self.assertEqual(split_bill(997, 13), split_bill(997, 13))


if __name__ == "__main__":
    unittest.main()
