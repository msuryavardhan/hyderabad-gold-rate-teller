"""
Telegram notification via the Bot API's sendMessage endpoint.

Credentials come from environment variables (loaded from .env by main.py),
never from source code.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

import requests

from app.calculator import RateChange, format_inr
from app.scraper import SOURCE_URL

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 10


class TelegramError(Exception):
    """Raised when a Telegram notification cannot be sent."""


def _display_date(iso_date: str) -> str:
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d %B %Y")
    except ValueError:
        return iso_date


def _rate_block(rate_per_gram: float, change: Optional[RateChange], previous_rate: Optional[float]) -> tuple:
    """Shared piece of the message: rate / 8g / 10g / change / previous
    lines for one purity. Returns (rate_8g, rate_10g, change_line,
    previous_line) so build_message can assemble the 22K block exactly as
    before and, optionally, an equivalent 24K block."""
    rate_8g = rate_per_gram * 8
    rate_10g = rate_per_gram * 10
    change_line = change.formatted() if change is not None else "Not available"
    previous_line = (
        f"Previous:\n₹{format_inr(previous_rate)} / gram\n" if previous_rate is not None else ""
    )
    return rate_8g, rate_10g, change_line, previous_line


def build_message(
    rate_per_gram: float,
    date: str,
    change: Optional[RateChange],
    updated_time: str,
    previous_rate: Optional[float] = None,
    rate_24k_per_gram: Optional[float] = None,
    change_24k: Optional[RateChange] = None,
    previous_rate_24k: Optional[float] = None,
) -> str:
    """previous_rate is optional and additive: when given (the immediately
    preceding date's actual rate from history, not "yesterday" assumed),
    an extra "Previous: ₹X / gram" line is included so the comparison in
    `change` has a concrete rate to reference, not just a delta.

    rate_24k_per_gram is likewise optional and additive: when given (24K
    was available this run), a second "24K Gold" block is appended with
    the same rate/8g/10g/change/previous shape as the 22K section above
    it. When omitted (the default -- also what happens when 24K was
    unavailable this run), the message is byte-for-byte identical to the
    22K-only version, so existing callers/tests are unaffected."""
    rate_8g, rate_10g, change_line, previous_line = _rate_block(rate_per_gram, change, previous_rate)

    rate_24k_block = ""
    if rate_24k_per_gram is not None:
        rate_24k_8g, rate_24k_10g, change_24k_line, previous_24k_line = _rate_block(
            rate_24k_per_gram, change_24k, previous_rate_24k
        )
        rate_24k_block = (
            "\n24K Gold\n"
            f"₹{format_inr(rate_24k_per_gram)} / gram\n"
            f"8 grams: ₹{format_inr(rate_24k_8g)}\n"
            f"10 grams: ₹{format_inr(rate_24k_10g)}\n"
            "Change:\n"
            f"{change_24k_line}\n"
            f"{previous_24k_line}"
        )

    return (
        "🪙 HYDERABAD GOLD RATE\n"
        "22K / 916 Gold\n"
        f"₹{format_inr(rate_per_gram)} / gram\n"
        f"8 grams: ₹{format_inr(rate_8g)}\n"
        f"10 grams: ₹{format_inr(rate_10g)}\n"
        "Change:\n"
        f"{change_line}\n"
        f"{previous_line}"
        f"{rate_24k_block}"
        f"📅 {_display_date(date)}\n"
        f"🕘 Updated: {updated_time}\n"
        "Source: Goodreturns\n"
        f"{SOURCE_URL}"
    )


def send_telegram_message(
    message: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> None:
    """Send a message via the Telegram Bot API.

    Raises TelegramError if credentials are missing or the send fails --
    callers should treat this as a non-fatal warning for the rest of the
    pipeline (the rate was still fetched and stored) but must log it clearly.
    """
    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        raise TelegramError(
            "TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID are not set. "
            "Add them to your .env file (see .env.example)."
        )

    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        response = requests.post(url, data=payload, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise TelegramError(f"Failed to reach Telegram API: {exc}") from exc

    if response.status_code != 200:
        raise TelegramError(
            f"Telegram API returned HTTP {response.status_code}: {response.text}"
        )

    body = response.json()
    if not body.get("ok"):
        raise TelegramError(f"Telegram API reported failure: {body}")

    logger.info("Telegram notification sent")
