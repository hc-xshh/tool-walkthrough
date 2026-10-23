import unittest

from money import split_bill


class SplitBillTest(unittest.TestCase):
    def test_split_evenly(self):
        self.assertEqual(split_bill(1000, 4), [250, 250, 250, 250])

    def test_single_person(self):
        self.assertEqual(split_bill(999, 1), [999])

    def test_zero_amount(self):
        self.assertEqual(split_bill(0, 3), [0, 0, 0])

    def test_returns_ints(self):
        for part in split_bill(1000, 3):
            self.assertIsInstance(part, int)

    def test_sum_is_preserved(self):
        self.assertEqual(sum(split_bill(1000, 3)), 1000)


if __name__ == "__main__":
    unittest.main()
