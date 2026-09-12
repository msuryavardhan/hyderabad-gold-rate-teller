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


def _asset_block(
    heading: str,
    rate_per_gram: float,
    change: Optional[RateChange],
    previous_rate: Optional[float],
    qty_a: float,
    qty_a_label: str,
    qty_b: float,
    qty_b_label: str,
) -> str:
    """One asset's section of the message: heading, rate, previous rate,
    change, and two quantity lines -- all derived from real, already-
    computed values (never re-fetched or estimated here). Gold passes
    (8, "8g", 10, "10g"); silver passes (100, "100g", 1000, "1kg") -- its
    own sensible units, never gold's."""
    value_a = rate_per_gram * qty_a
    value_b = rate_per_gram * qty_b
    return (
        f"{heading}\n"
        f"₹{format_inr(rate_per_gram)} / gram\n"
        f"Previous: {_previous_line(previous_rate)}\n"
        f"Change: {_change_line(change)}\n"
        f"{qty_a_label}: ₹{format_inr(value_a)}\n"
        f"{qty_b_label}: ₹{format_inr(value_b)}"
    )


def build_message(
    rate_per_gram: float,
    date: str,
    change: Optional[RateChange],
    previous_rate: Optional[float] = None,
    rate_24k_per_gram: Optional[float] = None,
    change_24k: Optional[RateChange] = None,
    previous_rate_24k: Optional[float] = None,
    rate_silver_per_gram: Optional[float] = None,
    change_silver: Optional[RateChange] = None,
    previous_rate_silver: Optional[float] = None,
) -> str:
    """Builds the daily Telegram notification: the Hyderabad 22K gold rate
    (always), 24K gold and silver when available this run.

    All values are whatever the caller already computed from the live
    Goodreturns scrape / JSON history; nothing here fetches, estimates, or
    fabricates a number. Each asset's previous_rate should be the
    immediately preceding *available* historical date for that specific
    asset (never an assumed "yesterday", and never one asset's previous
    rate used for another's change); when None, the message says
    "Previous: Not available" and the corresponding change is not shown
    as a real number either (it must itself be None in that case).

    rate_24k_per_gram / rate_silver_per_gram are each optional and
    independent: when either is None (unavailable this run), that asset's
    block is omitted entirely -- never fabricated or shown as zero.
    """
    block_22k = _asset_block("22K / 916 Gold", rate_per_gram, change, previous_rate, 8, "8g", 10, "10g")

    lines = [
        "🪙 Hyderabad Gold & Silver Rate",
        "",
        f"📅 {_display_date(date)}",
        "",
        "GOLD",
        "",
        block_22k,
    ]

    if rate_24k_per_gram is not None:
        block_24k = _asset_block("24K Gold", rate_24k_per_gram, change_24k, previous_rate_24k, 8, "8g", 10, "10g")
        lines.append("")
        lines.append(block_24k)

    if rate_silver_per_gram is not None:
        block_silver = _asset_block(
            "Silver", rate_silver_per_gram, change_silver, previous_rate_silver, 100, "100g", 1000, "1kg"
        )
        lines.append("")
        lines.append("SILVER")
        lines.append("")
        lines.append(block_silver)

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
