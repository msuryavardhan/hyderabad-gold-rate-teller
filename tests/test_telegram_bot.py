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

    def test_24k_section_omitted_by_default(self):
        message = build_message(
            rate_per_gram=14015,
            date="2026-09-11",
            change=None,
            updated_time="09:00",
        )
        self.assertNotIn("24K Gold", message)

    def test_message_includes_both_purities_when_given(self):
        change_22k = calculate_change(today_rate=14015, previous_rate=14255)
        change_24k = calculate_change(today_rate=15289, previous_rate=15551)
        message = build_message(
            rate_per_gram=14015,
            date="2026-09-11",
            change=change_22k,
            updated_time="09:00",
            previous_rate=14255,
            rate_24k_per_gram=15289,
            change_24k=change_24k,
            previous_rate_24k=15551,
        )
        # 22K section (unchanged, exactly as before)
        self.assertIn("22K / 916 Gold", message)
        self.assertIn("₹14,015 / gram", message)
        self.assertIn("-₹240 / gram (-1.68%)", message)
        # 24K section (new, additive)
        self.assertIn("24K Gold", message)
        self.assertIn("₹15,289 / gram", message)
        self.assertIn("8 grams: ₹1,22,312", message)
        self.assertIn("10 grams: ₹1,52,890", message)
        self.assertIn("-₹262 / gram (-1.68%)", message)
        # 24K's "Previous" (₹15,551) must appear distinctly from 22K's (₹14,255)
        self.assertIn("₹15,551 / gram", message)
        # The 24K block should come after the 22K block, before the date line.
        self.assertLess(message.index("24K Gold"), message.index("📅"))
        self.assertGreater(message.index("24K Gold"), message.index("22K / 916 Gold"))

    def test_24k_change_not_available_shown_independently(self):
        change_22k = calculate_change(today_rate=14015, previous_rate=14255)
        message = build_message(
            rate_per_gram=14015,
            date="2026-09-11",
            change=change_22k,
            updated_time="09:00",
            rate_24k_per_gram=15289,
            change_24k=None,  # e.g. no previous 24K rate available yet
        )
        self.assertIn("24K Gold", message)
        # Both a 22K change value AND a 24K "Not available" must appear
        # without being conflated.
        self.assertIn("-₹240 / gram (-1.68%)", message)
        occurrences = message.count("Not available")
        self.assertEqual(occurrences, 1)


if __name__ == "__main__":
    unittest.main()
