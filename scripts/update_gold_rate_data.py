"""
Entry point used by the GitHub Actions daily workflow (and runnable locally):

    fetch today's 22K + 24K rates and Goodreturns' "Last 10 Days" history
        -> validate
        -> merge into web/data/gold_rates.json
        -> notify Telegram

This intentionally does not modify run.py / app/main.py -- that CLI pipeline
(console output + local SQLite history) keeps working exactly as before.
This script adds the public-JSON side of Phase 2/3/4 as a separate,
additive entry point that reuses the same scraper/calculator/telegram
modules.

Exit code 0 means the 22K rate (and history) were fetched and the JSON
file was written successfully -- safe for the workflow to commit. Any
other exit code means nothing should be committed and the last published
data must be left untouched (this script never writes the JSON file
unless the fetch, history parsing, and validation all succeeded).

24K is treated as best-effort throughout: if it's unavailable this run,
22K still publishes normally and 24K's fields are published as null
(never fabricated), with any already-collected 24K history preserved.
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
from app.scraper import SOURCE_URL, GoldRateScraperError, get_hyderabad_gold_rates
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
        gold_data = get_hyderabad_gold_rates()
    except GoldRateScraperError as exc:
        logger.error("Failed to retrieve the gold rate / history: %s", exc)
        print(f"ERROR: Could not retrieve Hyderabad gold rate data: {exc}", file=sys.stderr)
        print(f"Source attempted: {SOURCE_URL}", file=sys.stderr)
        print("Refusing to update the published data -- last known good data stays live.", file=sys.stderr)
        return 1

    rate = gold_data["22K"]["current"]
    history_rows = gold_data["22K"]["history"]
    rate_24k = gold_data["24K"]["current"]
    history_rows_24k = gold_data["24K"]["history"]

    logger.info("Extracted %d historical 22K record(s) from Goodreturns", len(history_rows))
    logger.info(
        "24K: %s, %d historical record(s)",
        f"₹{rate_24k.rate_per_gram:,.2f}/g" if rate_24k else "unavailable this run",
        len(history_rows_24k),
    )

    rate_8g = price_for_grams(rate.rate_per_gram, 8)
    rate_10g = price_for_grams(rate.rate_per_gram, 10)

    existing = load_existing_json(DEFAULT_JSON_PATH)
    existing_24k = (existing or {}).get("gold_24k") or {}

    # Merge Goodreturns' historical rows first, then the authoritative
    # "current" card last, so it wins if the two ever disagree for today's
    # date. This never deletes a date we've already collected on an
    # earlier run -- it only adds/updates by date (see merge_history_records).
    history = merge_history_records(
        (existing or {}).get("history", []),
        list(history_rows) + [rate],
    )

    # 24K history is merged the same way, but only append today's "current"
    # 24K record if it was actually available this run -- if not, the
    # freshly scraped 24K historical rows (which may be empty too) are
    # still merged in, and nothing already collected is ever deleted.
    history_24k = merge_history_records(
        existing_24k.get("history", []),
        list(history_rows_24k) + ([rate_24k] if rate_24k is not None else []),
    )

    # The immediately preceding *available* date for each purity, not an
    # assumed "yesterday" -- and never a 22K rate compared against a 24K one.
    previous_rate = find_previous_rate({"history": history}, rate.date)
    change = calculate_change(rate.rate_per_gram, previous_rate)

    rate_24k_8g = rate_24k_10g = None
    previous_rate_24k = None
    change_24k = None
    if rate_24k is not None:
        rate_24k_8g = price_for_grams(rate_24k.rate_per_gram, 8)
        rate_24k_10g = price_for_grams(rate_24k.rate_per_gram, 10)
        previous_rate_24k = find_previous_rate({"history": history_24k}, rate_24k.date)
        change_24k = calculate_change(rate_24k.rate_per_gram, previous_rate_24k)

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
            rate_24k=rate_24k,
            rate_24k_8g=rate_24k_8g,
            rate_24k_10g=rate_24k_10g,
            change_24k=change_24k,
            history_24k=history_24k,
        )
        write_json_atomic(payload, DEFAULT_JSON_PATH)
    except DataExportError as exc:
        logger.error("Refusing to publish invalid data: %s", exc)
        return 1

    logger.info(
        "Published Hyderabad 22K rate: Rs.%s/g (date=%s); 22K history now has %d day(s); "
        "24K history now has %d day(s)",
        f"{rate.rate_per_gram:,.2f}",
        rate.date,
        len(history),
        len(history_24k),
    )

    # Keep the local SQLite history in sync too (best-effort). On GitHub
    # Actions this file is not persisted between runs -- that's fine, the
    # JSON file above is the durable, committed record for the pipeline.
    try:
        db = GoldRateDatabase()
        all_rows = list(history_rows) + [rate] + list(history_rows_24k)
        if rate_24k is not None:
            all_rows.append(rate_24k)
        db.insert_many_rates(all_rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Local database update skipped: %s", exc)

    # Telegram is best-effort: a notification failure must not undo the
    # successful data publish above, and must not be reported as a
    # pipeline failure (per spec, Telegram only fires "if configured").
    message = build_message(
        rate_per_gram=rate.rate_per_gram,
        date=rate.date,
        change=change,
        previous_rate=previous_rate,
        rate_24k_per_gram=rate_24k.rate_per_gram if rate_24k is not None else None,
        change_24k=change_24k,
        previous_rate_24k=previous_rate_24k,
    )
    try:
        send_telegram_message(message)
    except TelegramError as exc:
        logger.warning("Telegram notification not sent: %s", exc)

    return 0


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
