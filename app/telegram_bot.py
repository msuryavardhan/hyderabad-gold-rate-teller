"""
Telegram notification via the Bot API's sendMessage endpoint.

Credentials come from environment variables (TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID) -- read via os.environ in send_telegram_message, never
hardcoded, never logged. Locally these are loaded from a git-ignored .env
file by main.py / scripts/update_gold_rate_data.py (via python-dotenv);
in GitHub Actions they come from repository secrets injected as env vars.
If either is missing, TelegramError is raised with a message that says
*that a value is missing*, never what the values are.
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


def _change_line(change: Optional[RateChange]) -> str:
    """Renders the one-line change summary: an arrow for direction, the
    absolute rupee amount, and the signed percentage in parentheses.
    Never fabricates a change when none is available."""
    if change is None:
        return "Not available"
    if change.absolute == 0:
        return "→ No change"
    arrow = "↑" if change.absolute > 0 else "↓"
    percentage_sign = "+" if change.percentage > 0 else ""  # negative already carries "-"
    return f"{arrow} ₹{format_inr(abs(change.absolute))} ({percentage_sign}{change.percentage:.2f}%)"


def _previous_line(previous_rate: Optional[float]) -> str:
    if previous_rate is None:
        return "Not available"
    return f"₹{format_inr(previous_rate)} / gram"


def _purity_block(heading: str, rate_per_gram: float, change: Optional[RateChange], previous_rate: Optional[float]) -> str:
    """One purity's section of the message: heading, rate, previous rate,
    change, and 8g/10g -- all derived from real, already-computed values
    (never re-fetched or estimated here)."""
    rate_8g = rate_per_gram * 8
    rate_10g = rate_per_gram * 10
    return (
        f"{heading}\n"
        f"₹{format_inr(rate_per_gram)} / gram\n"
        f"Previous: {_previous_line(previous_rate)}\n"
        f"Change: {_change_line(change)}\n"
        f"8g: ₹{format_inr(rate_8g)}\n"
        f"10g: ₹{format_inr(rate_10g)}"
    )


def build_message(
    rate_per_gram: float,
    date: str,
    change: Optional[RateChange],
    previous_rate: Optional[float] = None,
    rate_24k_per_gram: Optional[float] = None,
    change_24k: Optional[RateChange] = None,
    previous_rate_24k: Optional[float] = None,
) -> str:
    """Builds the daily Telegram notification for the Hyderabad 22K rate,
    and -- when 24K data is available this run -- the 24K rate too.

    All values are whatever the caller already computed from the live
    Goodreturns scrape / JSON history; nothing here fetches, estimates, or
    fabricates a number. previous_rate/previous_rate_24k should be the
    immediately preceding *available* historical date for that purity
    (never an assumed "yesterday"); when None, the message says
    "Previous: Not available" and the corresponding change is not shown
    as a real number either (it must itself be None in that case).

    rate_24k_per_gram is optional: when None (24K unavailable this run),
    the message contains only the 22K section -- no 24K block is
    fabricated or shown as zero.
    """
    block_22k = _purity_block("22K / 916 Gold", rate_per_gram, change, previous_rate)

    lines = [
        "🪙 Hyderabad Gold Rate",
        "",
        f"📅 {_display_date(date)}",
        "",
        block_22k,
    ]

    if rate_24k_per_gram is not None:
        block_24k = _purity_block("24K Gold", rate_24k_per_gram, change_24k, previous_rate_24k)
        lines.append("")
        lines.append(block_24k)

    lines.append("")
    lines.append("Source: Goodreturns")
    lines.append(SOURCE_URL)

    return "\n".join(lines)


def send_telegram_message(
    message: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> None:
    """Send a message via the Telegram Bot API.

    Credentials come from the bot_token/chat_id arguments if given,
    otherwise from the TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID environment
    variables. Raises TelegramError if credentials are missing or the send
    fails -- callers should treat this as a non-fatal warning for the rest
    of the pipeline (the rate was still fetched and stored) but must log
    it clearly. The error message itself never includes the token or chat
    ID: on a missing-config error it only says that they're unset, and on
    a network-level failure it deliberately does not include requests'
    exception text, because that text can embed the full request URL --
    which contains the bot token -- and must never reach logs.
    """
    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        raise TelegramError(
            "TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID are not set. "
            "Add them to your .env file (see .env.example), or as GitHub "
            "Actions secrets for the scheduled workflow."
        )

    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        response = requests.post(url, data=payload, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        # Deliberately not f"...: {exc}" -- requests' exception messages
        # for connection-level failures can include the full request URL,
        # which embeds bot_token. Only the exception *type* is reported.
        raise TelegramError(
            f"Failed to reach Telegram API ({type(exc).__name__})"
        ) from exc

    if response.status_code != 200:
        raise TelegramError(
            f"Telegram API returned HTTP {response.status_code}: {response.text}"
        )

    body = response.json()
    if not body.get("ok"):
        raise TelegramError(f"Telegram API reported failure: {body}")

    logger.info("Telegram notification sent")
