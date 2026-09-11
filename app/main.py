"""
Orchestrates one end-to-end run:

    fetch -> validate -> print -> store -> compare -> notify -> log

Designed to be invoked either manually (`python run.py`) or from Windows
Task Scheduler for the daily 9:00 AM IST job (see README.md).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

# Windows' legacy console codepage (cp1252) cannot encode the Rupee sign
# and crashes on print(). Force UTF-8 output so the CLI can print real
# rupee symbols regardless of which terminal launched it (works on
# Windows Terminal / PowerShell 7 / VS Code; on very old cmd.exe windows
# that don't understand UTF-8 the glyph may render as a placeholder box
# instead of crashing).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from dotenv import load_dotenv

from app.calculator import calculate_change, price_for_grams, format_inr
from app.database import GoldRateDatabase
from app.scraper import GoldRateScraperError, get_hyderabad_22k_rate, SOURCE_URL
from app.telegram_bot import TelegramError, build_message, send_telegram_message

LOG_PATH = Path(__file__).resolve().parent.parent / "gold_rate_teller.log"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def print_rate_box(
    rate_per_gram: float,
    rate_8g: float,
    rate_10g: float,
    date: str,
    updated_time: str,
) -> None:
    display_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    print("=" * 40)
    print("HYDERABAD GOLD RATE TELLER")
    print("Source       : Goodreturns")
    print("City         : Hyderabad")
    print("Purity       : 22K")
    print(f"Rate / gram  : ₹{format_inr(rate_per_gram)}")
    print(f"Rate / 8g    : ₹{format_inr(rate_8g)}")
    print(f"Rate / 10g   : ₹{format_inr(rate_10g)}")
    print(f"Date         : {display_date}")
    print(f"Updated      : {updated_time}")
    print("=" * 40)


def run(send_notification: bool = True) -> int:
    """Runs the full pipeline. Returns a process exit code (0 = success)."""
    logger = logging.getLogger(__name__)
    load_dotenv()

    logger.info("Fetching Goodreturns...")
    try:
        rate = get_hyderabad_22k_rate()
    except GoldRateScraperError as exc:
        logger.error("Failed to retrieve the gold rate: %s", exc)
        print("ERROR: Could not retrieve the Hyderabad 22K gold rate.")
        print(f"Reason: {exc}")
        print(f"Source attempted: {SOURCE_URL}")
        print("No rate has been stored or sent -- refusing to fabricate a value.")
        return 1

    rate_8g = price_for_grams(rate.rate_per_gram, 8)
    rate_10g = price_for_grams(rate.rate_per_gram, 10)
    updated_time = datetime.now().strftime("%H:%M")

    print_rate_box(rate.rate_per_gram, rate_8g, rate_10g, rate.date, updated_time)

    # --- Database ---
    try:
        db = GoldRateDatabase()
        db.insert_rate(
            city=rate.city,
            purity=rate.purity,
            rate_per_gram=rate.rate_per_gram,
            date=rate.date,
            source=rate.source,
        )
    except Exception as exc:  # noqa: BLE001 -- log any DB failure, don't crash the run
        logger.error("Database update failed: %s", exc)
        db = None

    # --- Historical comparison ---
    change = None
    previous_rate = None
    if db is not None:
        previous = db.get_latest_before(rate.date, rate.city, rate.purity)
        if previous is not None:
            previous_rate = previous.rate_per_gram
            change = calculate_change(rate.rate_per_gram, previous_rate)

    if change is not None:
        print("Change:")
        print(f"{change.formatted()}")
    else:
        print("Change: Not available")

    # --- Telegram ---
    if send_notification:
        message = build_message(
            rate_per_gram=rate.rate_per_gram,
            date=rate.date,
            change=change,
            previous_rate=previous_rate,
        )
        try:
            send_telegram_message(message)
        except TelegramError as exc:
            logger.warning("Telegram notification not sent: %s", exc)

    return 0


if __name__ == "__main__":
    setup_logging()
    sys.exit(run())
