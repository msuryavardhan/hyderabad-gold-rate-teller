import unittest

from app.calculator import calculate_change
from app.telegram_bot import build_message


class TestBuildMessage(unittest.TestCase):
    def test_message_with_change(self):
        change = calculate_change(today_rate=14255, previous_rate=14100)
        message = build_message(
            rate_per_gram=14255,
            date="2026-09-11",
            change=change,
            updated_time="09:00",
        )
        self.assertIn("HYDERABAD GOLD RATE", message)
        self.assertIn("22K / 916 Gold", message)
        self.assertIn("₹14,255 / gram", message)
        self.assertIn("8 grams: ₹1,14,040", message)
        self.assertIn("10 grams: ₹1,42,550", message)
        self.assertIn("+₹155 / gram (+1.10%)", message)
        self.assertIn("📅 11 September 2026", message)
        self.assertIn("🕘 Updated: 09:00", message)
        self.assertIn("Source: Goodreturns", message)
        self.assertIn("https://www.goodreturns.in/gold-rates/hyderabad.html", message)

    def test_message_without_previous_rate(self):
        message = build_message(
            rate_per_gram=14255,
            date="2026-09-11",
            change=None,
            updated_time="09:00",
        )
        self.assertIn("Not available", message)
        self.assertNotIn("Previous:", message)

    def test_message_includes_previous_rate_when_given(self):
        change = calculate_change(today_rate=14015, previous_rate=14255)
        message = build_message(
            rate_per_gram=14015,
            date="2026-09-11",
            change=change,
            updated_time="09:00",
            previous_rate=14255,
        )
        self.assertIn("-₹240 / gram (-1.68%)", message)
        self.assertIn("Previous:", message)
        self.assertIn("₹14,255 / gram", message)


if __name__ == "__main__":
    unittest.main()
