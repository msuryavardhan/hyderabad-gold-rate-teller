"""
Entry point used by the GitHub Actions daily workflow (and runnable locally):

    fetch Gold (22K + 24K) and Silver, each independently
        -> validate
        -> merge into web/data/gold_rates.json
        -> notify Telegram

This intentionally does not modify run.py / app/main.py -- that CLI pipeline
(console output + local SQLite history, gold-only) keeps working exactly as
before. This script is the public-JSON side of the pipeline, reusing the
same scraper/calculator/data_export/telegram modules.

Gold and Silver are fetched from two different Goodreturns pages and are
handled as fully independent operations: a failure in one must never
corrupt or discard the other's data, in either direction --

- Gold succeeds, Silver fails: Gold publishes fresh; Silver's last
  published rate/change/history is carried forward untouched (not nulled,
  not fabricated) so the site never abruptly shows "unavailable" for a
  purely transient scrape hiccup.
- Silver succeeds, Gold fails: Silver publishes fresh; Gold's entire
  previous published section (22K, 24K, history) is carried forward
  untouched.
- Both fail: nothing is written at all -- the previously published file
  stays exactly as it was. Exit code 1.
- Either succeeds: exit code 0, safe for the workflow to commit.
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
from app.scraper import (
    CITY,
    SILVER_SOURCE_URL,
    SOURCE_NAME,
    SOURCE_URL,
    GoldRate,
    GoldRateScraperError,
    get_hyderabad_gold_rates,
    get_hyderabad_silver_with_history,
)
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

    logger.info("Fetching Goodreturns (gold)...")
    gold_data = None
    try:
        gold_data = get_hyderabad_gold_rates()
    except GoldRateScraperError as exc:
        logger.error("Gold fetch failed: %s", exc)
        print(f"ERROR: Could not retrieve Hyderabad gold rate data: {exc}", file=sys.stderr)
        print(f"Source attempted: {SOURCE_URL}", file=sys.stderr)

    logger.info("Fetching Goodreturns (silver)...")
    silver_current = None
    silver_history_rows: list = []
    try:
        silver_current, silver_history_rows = get_hyderabad_silver_with_history()
    except GoldRateScraperError as exc:
        logger.error("Silver fetch failed: %s", exc)
        print(f"ERROR: Could not retrieve Hyderabad silver rate data: {exc}", file=sys.stderr)
        print(f"Source attempted: {SILVER_SOURCE_URL}", file=sys.stderr)

    gold_ok = gold_data is not None
    silver_ok = silver_current is not None

    if not gold_ok and not silver_ok:
        logger.error("Both gold and silver fetches failed -- nothing to publish.")
        print("Refusing to update the published data -- last known good data stays live.", file=sys.stderr)
        return 1

    existing = load_existing_json(DEFAULT_JSON_PATH)
    existing_silver = (existing or {}).get("silver") or {}

    updated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    # ---------------- GOLD (22K required within this branch, 24K best-effort) ----------------
    rate = rate_8g = rate_10g = change = history = None
    rate_24k = rate_24k_8g = rate_24k_10g = change_24k = history_24k = None
    previous_rate = previous_rate_24k = None

    if gold_ok:
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

        existing_24k = (existing or {}).get("gold_24k") or {}

        # Merge Goodreturns' historical rows first, then the authoritative
        # "current" card last, so it wins if the two ever disagree for
        # today's date. This never deletes a date already collected on an
        # earlier run -- it only adds/updates by date.
        history = merge_history_records(
            (existing or {}).get("history", []),
            list(history_rows) + [rate],
        )
        history_24k = merge_history_records(
            existing_24k.get("history", []),
            list(history_rows_24k) + ([rate_24k] if rate_24k is not None else []),
        )

        previous_rate = find_previous_rate({"history": history}, rate.date)
        change = calculate_change(rate.rate_per_gram, previous_rate)

        if rate_24k is not None:
            rate_24k_8g = price_for_grams(rate_24k.rate_per_gram, 8)
            rate_24k_10g = price_for_grams(rate_24k.rate_per_gram, 10)
            previous_rate_24k = find_previous_rate({"history": history_24k}, rate_24k.date)
            change_24k = calculate_change(rate_24k.rate_per_gram, previous_rate_24k)
    else:
        if existing is None:
            logger.error("Gold fetch failed and there is no existing published data to fall back on.")
            return 1
        logger.warning("Preserving previous Gold data -- Gold fetch failed this run.")

    # ---------------- SILVER (independent of Gold) ----------------
    silver_100g = silver_1kg = change_silver = previous_rate_silver = None
    history_silver = None

    if silver_ok:
        logger.info("Extracted %d historical silver record(s) from Goodreturns", len(silver_history_rows))
        silver_100g = price_for_grams(silver_current.rate_per_gram, 100)
        silver_1kg = price_for_grams(silver_current.rate_per_gram, 1000)
        history_silver = merge_history_records(
            existing_silver.get("history", []),
            list(silver_history_rows) + [silver_current],
        )
        previous_rate_silver = find_previous_rate({"history": history_silver}, silver_current.date)
        change_silver = calculate_change(silver_current.rate_per_gram, previous_rate_silver)
    else:
        logger.warning("Preserving previous Silver data (if any) -- Silver fetch failed this run.")
        history_silver = existing_silver.get("history", [])

    # ---------------- Build and write the payload ----------------
    # build_json_payload always requires a valid 22K "rate" to validate
    # against. When Gold failed this run, we reconstruct one from the
    # last published values purely to satisfy that contract -- every
    # gold-describing field in the final payload is then overwritten
    # verbatim from `existing` immediately below, so nothing about this
    # placeholder is actually published.
    payload_rate = rate if gold_ok else GoldRate(
        city=existing.get("city", CITY),
        purity=existing.get("purity", "22K"),
        rate_per_gram=existing["current"]["rate_per_gram"],
        date=existing["date"],
        source=existing.get("source", SOURCE_NAME),
    )
    payload_rate_8g = rate_8g if gold_ok else existing["current"]["rate_8g"]
    payload_rate_10g = rate_10g if gold_ok else existing["current"]["rate_10g"]

    try:
        payload = build_json_payload(
            rate=payload_rate,
            rate_8g=payload_rate_8g,
            rate_10g=payload_rate_10g,
            change=change,  # None when gold_ok is False -- overwritten below anyway
            updated_at=updated_at,
            history=history if gold_ok else (existing or {}).get("history", []),
            source_url=SOURCE_URL,
            rate_24k=rate_24k,
            rate_24k_8g=rate_24k_8g,
            rate_24k_10g=rate_24k_10g,
            change_24k=change_24k,
            history_24k=history_24k if gold_ok else ((existing or {}).get("gold_24k") or {}).get("history", []),
            silver=silver_current,
            silver_100g=silver_100g,
            silver_1kg=silver_1kg,
            change_silver=change_silver,
            history_silver=history_silver,
            silver_source_url=SILVER_SOURCE_URL,
        )
    except DataExportError as exc:
        logger.error("Refusing to publish invalid data: %s", exc)
        return 1

    if not gold_ok:
        # Restore every gold-describing field verbatim from the last
        # publish -- only "silver" and "updated_at" are allowed to be
        # fresh in this branch.
        for key in ("source", "city", "purity", "current", "change", "date", "history", "gold_24k"):
            payload[key] = existing.get(key, payload.get(key))

    if not silver_ok and existing_silver.get("current") is not None:
        # Preserve the last known good silver section verbatim (current,
        # change, date, history) rather than publishing nulls for a
        # purely transient failure.
        payload["silver"] = existing_silver

    write_json_atomic(payload, DEFAULT_JSON_PATH)

    logger.info(
        "Published: Gold %s; Silver %s",
        f"22K ₹{rate.rate_per_gram:,.2f}/g" if gold_ok else "preserved from last publish",
        f"₹{silver_current.rate_per_gram:,.2f}/g" if silver_ok else "preserved from last publish",
    )

    # Keep the local SQLite history in sync too (best-effort). On GitHub
    # Actions this file is not persisted between runs -- that's fine, the
    # JSON file above is the durable, committed record for the pipeline.
    try:
        db = GoldRateDatabase()
        all_rows = []
        if gold_ok:
            all_rows += list(history_rows) + [rate] + list(history_rows_24k)
            if rate_24k is not None:
                all_rows.append(rate_24k)
        if silver_ok:
            all_rows += list(silver_history_rows) + [silver_current]
        if all_rows:
            db.insert_many_rates(all_rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Local database update skipped: %s", exc)

    # Telegram is best-effort: a notification failure must not undo the
    # successful data publish above, and must not be reported as a
    # pipeline failure (per spec, Telegram only fires "if configured").
    # Uses the *displayed* payload values (fresh-or-preserved) so the
    # message always matches what the website currently shows.
    message = build_message(
        rate_per_gram=payload["current"]["rate_per_gram"],
        date=payload["date"],
        change=change if gold_ok else None,
        previous_rate=previous_rate if gold_ok else None,
        rate_24k_per_gram=(payload.get("gold_24k") or {}).get("current", {}).get("rate_per_gram")
        if (payload.get("gold_24k") or {}).get("current")
        else None,
        change_24k=change_24k if gold_ok else None,
        previous_rate_24k=previous_rate_24k if gold_ok else None,
        rate_silver_per_gram=(payload.get("silver") or {}).get("current", {}).get("rate_per_gram")
        if (payload.get("silver") or {}).get("current")
        else None,
        change_silver=change_silver if silver_ok else None,
        previous_rate_silver=previous_rate_silver if silver_ok else None,
    )
    try:
        send_telegram_message(message)
    except TelegramError as exc:
        logger.warning("Telegram notification not sent: %s", exc)

    return 0


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
