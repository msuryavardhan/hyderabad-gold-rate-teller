"""
Entry point used by the GitHub Actions daily workflow (and runnable locally):

    fetch today's rate + Goodreturns' own "Last 10 Days" history
        -> validate
        -> merge into web/data/gold_rates.json
        -> notify Telegram

This intentionally does not modify run.py / app/main.py -- that CLI pipeline
(console output + local SQLite history) keeps working exactly as before.
This script adds the public-JSON side of Phase 2/3 as a separate, additive
entry point that reuses the same scraper/calculator/telegram modules.

Exit code 0 means the rate (and history) were fetched and the JSON file was
written successfully -- safe for the workflow to commit. Any other exit
code means nothing should be committed and the last published data must be
left untouched (this script never writes the JSON file unless the fetch,
history parsing, and validation all succeeded).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `python scripts/update_gold_rate_data.py` to be run directly (e.g.
# from GitHub Actions' working directory) by putting the repo root -- which
# contains the `app` package -- on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from app.calculator import calculate_change, price_for_grams
from app.data_export import (
    DEFAULT_JSON_PATH,
    DataExportError,
    build_json_payload,
    find_previous_rate,
    load_existing_json,
    merge_history_records,
    write_json_atomic,
)
from app.database import GoldRateDatabase
from app.scraper import SOURCE_URL, GoldRateScraperError, get_hyderabad_22k_with_history
from app.telegram_bot import TelegramError, build_message, send_telegram_message


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    logger = logging.getLogger(__name__)
    load_dotenv()

    logger.info("Fetching Goodreturns...")
    try:
        rate, history_rows = get_hyderabad_22k_with_history()
    except GoldRateScraperError as exc:
        logger.error("Failed to retrieve the gold rate / history: %s", exc)
        print(f"ERROR: Could not retrieve Hyderabad 22K data: {exc}", file=sys.stderr)
        print(f"Source attempted: {SOURCE_URL}", file=sys.stderr)
        print("Refusing to update the published data -- last known good data stays live.", file=sys.stderr)
        return 1

    logger.info("Extracted %d historical 22K record(s) from Goodreturns", len(history_rows))

    rate_8g = price_for_grams(rate.rate_per_gram, 8)
    rate_10g = price_for_grams(rate.rate_per_gram, 10)

    existing = load_existing_json(DEFAULT_JSON_PATH)

    # Merge Goodreturns' historical rows first, then the authoritative
    # "current" card last, so it wins if the two ever disagree for today's
    # date. This never deletes a date we've already collected on an
    # earlier run -- it only adds/updates by date (see merge_history_records).
    history = merge_history_records(
        (existing or {}).get("history", []),
        list(history_rows) + [rate],
    )

    # The immediately preceding *available* date, not an assumed "yesterday".
    previous_rate = find_previous_rate({"history": history}, rate.date)
    change = calculate_change(rate.rate_per_gram, previous_rate)

    updated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    try:
        payload = build_json_payload(
            rate=rate,
            rate_8g=rate_8g,
            rate_10g=rate_10g,
            change=change,
            updated_at=updated_at,
            history=history,
            source_url=SOURCE_URL,
        )
        write_json_atomic(payload, DEFAULT_JSON_PATH)
    except DataExportError as exc:
        logger.error("Refusing to publish invalid data: %s", exc)
        return 1

    logger.info(
        "Published Hyderabad 22K rate: Rs.%s/g (date=%s); history now has %d day(s)",
        f"{rate.rate_per_gram:,.2f}",
        rate.date,
        len(history),
    )

    # Keep the local SQLite history in sync too (best-effort). On GitHub
    # Actions this file is not persisted between runs -- that's fine, the
    # JSON file above is the durable, committed record for the pipeline.
    try:
        db = GoldRateDatabase()
        db.insert_many_rates(list(history_rows) + [rate])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Local database update skipped: %s", exc)

    # Telegram is best-effort: a notification failure must not undo the
    # successful data publish above, and must not be reported as a
    # pipeline failure (per spec, Telegram only fires "if configured").
    message = build_message(
        rate_per_gram=rate.rate_per_gram,
        date=rate.date,
        change=change,
        updated_time=datetime.now().strftime("%H:%M"),
        previous_rate=previous_rate,
    )
    try:
        send_telegram_message(message)
    except TelegramError as exc:
        logger.warning("Telegram notification not sent: %s", exc)

    return 0


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
