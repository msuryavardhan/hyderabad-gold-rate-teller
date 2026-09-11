import unittest

from app.calculator import calculate_change, format_inr, price_for_grams


class TestPriceForGrams(unittest.TestCase):
    def test_8_and_10_grams(self):
        rate = 14015.0
        self.assertEqual(price_for_grams(rate, 8), 112120.0)
        self.assertEqual(price_for_grams(rate, 10), 140150.0)

    def test_zero_grams(self):
        self.assertEqual(price_for_grams(14015.0, 0), 0.0)

    def test_negative_inputs_rejected(self):
        with self.assertRaises(ValueError):
            price_for_grams(-1, 8)
        with self.assertRaises(ValueError):
            price_for_grams(14015.0, -8)


class TestCalculateChange(unittest.TestCase):
    def test_positive_change_matches_worked_example(self):
        change = calculate_change(today_rate=14255, previous_rate=14100)
        self.assertIsNotNone(change)
        self.assertEqual(change.absolute, 155)
        self.assertAlmostEqual(change.percentage, 1.10, places=2)
        self.assertEqual(change.formatted(), "+₹155 / gram (+1.10%)")

    def test_negative_change(self):
        change = calculate_change(today_rate=14015, previous_rate=14255)
        self.assertEqual(change.absolute, -240)
        self.assertTrue(change.percentage < 0)
        self.assertTrue(change.formatted().startswith("-"))

    def test_no_previous_rate_returns_none(self):
        self.assertIsNone(calculate_change(today_rate=14255, previous_rate=None))

    def test_zero_previous_rate_returns_none(self):
        # Avoid division by zero; a stored rate of 0 is itself invalid data.
        self.assertIsNone(calculate_change(today_rate=14255, previous_rate=0))


class TestFormatInr(unittest.TestCase):
    def test_small_number(self):
        self.assertEqual(format_inr(500), "500")

    def test_thousands(self):
        self.assertEqual(format_inr(14015), "14,015")

    def test_lakhs(self):
        self.assertEqual(format_inr(140150), "1,40,150")

    def test_negative(self):
        self.assertEqual(format_inr(-240), "-240")


if __name__ == "__main__":
    unittest.main()
