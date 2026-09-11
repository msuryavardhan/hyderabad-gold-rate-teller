import os
import unittest
from unittest.mock import patch

import requests

from app.calculator import calculate_change
from app.telegram_bot import TelegramError, build_message, send_telegram_message


class TestBuildMessage22k(unittest.TestCase):
    """22K section: format, values, and rounding are exactly what the
    caller passed in -- nothing here re-derives or fabricates a number."""

    def test_message_shape_and_header(self):
        message = build_message(rate_per_gram=14015, date="2026-09-11", change=None)
        self.assertTrue(message.startswith("🪙 Hyderabad Gold Rate\n\n📅 11 September 2026\n\n"))
        self.assertIn("22K / 916 Gold", message)
        self.assertIn("Source: Goodreturns", message)
        self.assertIn("https://www.goodreturns.in/gold-rates/hyderabad.html", message)

    def test_rate_and_gram_values(self):
        message = build_message(rate_per_gram=14015, date="2026-09-11", change=None)
        self.assertIn("₹14,015 / gram", message)
        self.assertIn("8g: ₹1,12,120", message)  # 14015 * 8, Indian comma grouping
        self.assertIn("10g: ₹1,40,150", message)  # 14015 * 10

    def test_positive_change_shows_up_arrow(self):
        change = calculate_change(today_rate=14255, previous_rate=14100)
        message = build_message(rate_per_gram=14255, date="2026-09-11", change=change, previous_rate=14100)
        self.assertIn("Change: ↑ ₹155 (+1.10%)", message)
        self.assertIn("Previous: ₹14,100 / gram", message)

    def test_negative_change_shows_down_arrow(self):
        change = calculate_change(today_rate=14015, previous_rate=14255)
        message = build_message(rate_per_gram=14015, date="2026-09-11", change=change, previous_rate=14255)
        self.assertIn("Change: ↓ ₹240 (-1.68%)", message)
        self.assertIn("Previous: ₹14,255 / gram", message)

    def test_zero_change_shows_no_change(self):
        change = calculate_change(today_rate=14015, previous_rate=14015)
        message = build_message(rate_per_gram=14015, date="2026-09-11", change=change, previous_rate=14015)
        self.assertIn("Change: → No change", message)

    def test_missing_previous_rate_is_explicit_not_fabricated(self):
        message = build_message(rate_per_gram=14015, date="2026-09-11", change=None, previous_rate=None)
        self.assertIn("Previous: Not available", message)
        self.assertIn("Change: Not available", message)
        # Must never invent a rupee figure or a percentage when there's
        # nothing to compare against.
        self.assertNotIn("↑", message)
        self.assertNotIn("↓", message)


class TestBuildMessage24k(unittest.TestCase):
    def test_24k_omitted_by_default(self):
        message = build_message(rate_per_gram=14015, date="2026-09-11", change=None)
        self.assertNotIn("24K Gold", message)

    def test_24k_section_included_with_real_values(self):
        change_22k = calculate_change(today_rate=14015, previous_rate=14255)
        change_24k = calculate_change(today_rate=15289, previous_rate=15551)
        message = build_message(
            rate_per_gram=14015,
            date="2026-09-11",
            change=change_22k,
            previous_rate=14255,
            rate_24k_per_gram=15289,
            change_24k=change_24k,
            previous_rate_24k=15551,
        )
        self.assertIn("24K Gold", message)
        self.assertIn("₹15,289 / gram", message)
        self.assertIn("Previous: ₹15,551 / gram", message)
        self.assertIn("Change: ↓ ₹262 (-1.68%)", message)
        self.assertIn("8g: ₹1,22,312", message)
        self.assertIn("10g: ₹1,52,890", message)
        # The 24K block must come after the 22K block, before the Source line.
        self.assertLess(message.index("22K / 916 Gold"), message.index("24K Gold"))
        self.assertLess(message.index("24K Gold"), message.index("Source: Goodreturns"))

    def test_22k_and_24k_values_never_conflated(self):
        change_22k = calculate_change(today_rate=14015, previous_rate=14255)
        change_24k = calculate_change(today_rate=15289, previous_rate=15551)
        message = build_message(
            rate_per_gram=14015,
            date="2026-09-11",
            change=change_22k,
            previous_rate=14255,
            rate_24k_per_gram=15289,
            change_24k=change_24k,
            previous_rate_24k=15551,
        )
        # Both changes happen to round to the same percentage (-1.68%) but
        # must keep their own distinct absolute rupee amounts.
        self.assertIn("↓ ₹240 (-1.68%)", message)
        self.assertIn("↓ ₹262 (-1.68%)", message)
        self.assertNotIn("₹240", message.split("24K Gold")[1] if "24K Gold" in message else "")

    def test_24k_missing_previous_rate_independent_of_22k(self):
        change_22k = calculate_change(today_rate=14015, previous_rate=14255)
        message = build_message(
            rate_per_gram=14015,
            date="2026-09-11",
            change=change_22k,
            previous_rate=14255,
            rate_24k_per_gram=15289,
            change_24k=None,
            previous_rate_24k=None,
        )
        # 22K still has a real change...
        self.assertIn("Change: ↓ ₹240 (-1.68%)", message)
        # ...while 24K correctly reports unavailable, not a fabricated one.
        self.assertEqual(message.count("Not available"), 2)  # 24K's Previous + Change


class TestIndianRupeeFormatting(unittest.TestCase):
    def test_lakh_grouping(self):
        message = build_message(rate_per_gram=140150, date="2026-09-11", change=None)
        self.assertIn("₹1,40,150 / gram", message)

    def test_ten_lakh_grouping_in_8g_10g(self):
        message = build_message(rate_per_gram=152890, date="2026-09-11", change=None)
        self.assertIn("8g: ₹12,23,120", message)
        self.assertIn("10g: ₹15,28,900", message)


class TestTelegramSecretsFromEnvironment(unittest.TestCase):
    """send_telegram_message must read credentials only from environment
    variables (or explicit arguments for testing), never from source, and
    must never leak their values into any exception message."""

    def test_reads_bot_token_and_chat_id_from_environment(self):
        fake_response = type(
            "Resp", (), {"status_code": 200, "json": lambda self: {"ok": True}, "text": ""}
        )()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env-token-123", "TELEGRAM_CHAT_ID": "999"}):
            with patch("app.telegram_bot.requests.post", return_value=fake_response) as mock_post:
                send_telegram_message("hello")
        called_url = mock_post.call_args.args[0]
        self.assertIn("env-token-123", called_url)  # used correctly...
        called_payload = mock_post.call_args.kwargs["data"]
        self.assertEqual(called_payload["chat_id"], "999")

    def test_explicit_arguments_override_environment(self):
        fake_response = type(
            "Resp", (), {"status_code": 200, "json": lambda self: {"ok": True}, "text": ""}
        )()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env-token", "TELEGRAM_CHAT_ID": "111"}):
            with patch("app.telegram_bot.requests.post", return_value=fake_response) as mock_post:
                send_telegram_message("hello", bot_token="explicit-token", chat_id="222")
        called_url = mock_post.call_args.args[0]
        self.assertIn("explicit-token", called_url)
        self.assertNotIn("env-token", called_url)

    def test_missing_configuration_raises_without_exposing_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TelegramError) as ctx:
                send_telegram_message("hello")
        error_text = str(ctx.exception)
        self.assertIn("not set", error_text)
        # The error must describe the *absence* of config, never echo a value.
        self.assertNotIn("None", error_text)

    def test_missing_bot_token_only(self):
        with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "123"}, clear=True):
            with self.assertRaises(TelegramError):
                send_telegram_message("hello")

    def test_missing_chat_id_only(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "some-token"}, clear=True):
            with self.assertRaises(TelegramError):
                send_telegram_message("hello")


class TestNoSecretsLeakOnFailure(unittest.TestCase):
    """A network-level failure must never surface the bot token, even
    though the token is embedded in the request URL requests would
    otherwise include in its own exception message."""

    def test_connection_error_message_never_contains_the_token(self):
        secret_token = "123456789:AAFakeSecretTokenForTestingOnly"
        underlying_exc = requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool(host='api.telegram.org', port=443): "
            f"Max retries exceeded with url: /bot{secret_token}/sendMessage"
        )
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": secret_token, "TELEGRAM_CHAT_ID": "123"}):
            with patch("app.telegram_bot.requests.post", side_effect=underlying_exc):
                with self.assertRaises(TelegramError) as ctx:
                    send_telegram_message("hello")
        self.assertNotIn(secret_token, str(ctx.exception))

    def test_http_error_response_body_is_not_a_token_leak_vector(self):
        # Telegram's own error responses (unlike a raw connection error)
        # don't echo the request URL/token -- just confirm our error
        # message is built from the response body, not the request URL.
        fake_response = type(
            "Resp",
            (),
            {"status_code": 401, "text": '{"ok":false,"description":"Unauthorized"}'},
        )()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "some-token", "TELEGRAM_CHAT_ID": "123"}):
            with patch("app.telegram_bot.requests.post", return_value=fake_response):
                with self.assertRaises(TelegramError) as ctx:
                    send_telegram_message("hello")
        self.assertNotIn("some-token", str(ctx.exception))
        self.assertIn("Unauthorized", str(ctx.exception))

    def test_api_reported_failure_does_not_include_token(self):
        fake_response = type(
            "Resp",
            (),
            {
                "status_code": 200,
                "text": '{"ok":false,"description":"chat not found"}',
                "json": lambda self: {"ok": False, "description": "chat not found"},
            },
        )()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "some-token", "TELEGRAM_CHAT_ID": "123"}):
            with patch("app.telegram_bot.requests.post", return_value=fake_response):
                with self.assertRaises(TelegramError) as ctx:
                    send_telegram_message("hello")
        self.assertNotIn("some-token", str(ctx.exception))


class TestSendTelegramMessageSuccess(unittest.TestCase):
    def test_successful_send_logs_without_secrets(self):
        fake_response = type(
            "Resp", (), {"status_code": 200, "json": lambda self: {"ok": True}, "text": ""}
        )()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "some-token", "TELEGRAM_CHAT_ID": "123"}):
            with patch("app.telegram_bot.requests.post", return_value=fake_response):
                with self.assertLogs("app.telegram_bot", level="INFO") as log_ctx:
                    send_telegram_message("hello")
        joined_logs = "\n".join(log_ctx.output)
        self.assertIn("Telegram notification sent", joined_logs)
        self.assertNotIn("some-token", joined_logs)


if __name__ == "__main__":
    unittest.main()
