"""
Builds and writes the public, browser-readable JSON data file consumed by
the GitHub Pages dashboard (web/data/gold_rates.json).

This module is intentionally independent of the SQLite database used by
app/database.py: SQLite is local-only storage on whichever machine runs
`python run.py`, but GitHub Actions checks out a fresh copy of the repo on
every run (no persisted local disk), so the *public* history has to live
somewhere that git actually tracks. This JSON file's own "history" array
is that persisted record -- each run reads the previously committed file,
appends/updates today's entry, and writes the result back.

Nothing here touches the network or re-implements scraping/calculation --
it only shapes and validates data that has already been fetched and
computed by app/scraper.py and app/calculator.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Iterable, Optional, Union

from app.calculator import RateChange
from app.scraper import GoldRate

HistoryRecord = Union[GoldRate, dict]

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_PATH = REPO_ROOT / "web" / "data" / "gold_rates.json"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_HISTORY_ENTRIES = 90  # comfortably covers the dashboard's 7d/30d views


class DataExportError(Exception):
    """Raised when data would be invalid to publish -- never written."""


def load_existing_json(path: Path = DEFAULT_JSON_PATH) -> Optional[dict]:
    """Reads the previously published JSON file, if any.

    Returns None if the file doesn't exist or is unreadable/corrupt --
    logged as a warning, never raised, so a corrupt file never blocks a
    fresh, valid publish (it just means history restarts from today).
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Existing data file %s is unreadable (%s); ignoring it", path, exc)
        return None

    if not isinstance(data, dict) or "history" not in data:
        logger.warning("Existing data file %s has an unexpected shape; ignoring it", path)
        return None
    return data


def find_previous_rate(existing: Optional[dict], today_date: str) -> Optional[float]:
    """Finds the most recent rate strictly before today_date in the
    existing file's history. Returns None if there is nothing earlier --
    callers should then report "Change: Not available" rather than
    inventing a comparison value."""
    if not existing:
        return None
    history = existing.get("history") or []
    candidates = [
        entry
        for entry in history
        if isinstance(entry, dict) and entry.get("date") and entry["date"] < today_date
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda entry: entry["date"])
    return latest.get("rate_per_gram")


def merge_history_records(
    history: list[dict],
    records: Iterable[HistoryRecord],
    max_entries: int = MAX_HISTORY_ENTRIES,
) -> list[dict]:
    """Merges new records (each a GoldRate or a {"date", "rate_per_gram"}
    dict) into an existing history list, keyed by date.

    This is the one place that ever changes the history array, and it only
    ever adds or updates entries by date -- it never removes a date that
    isn't being replaced, so a day where Goodreturns' "Last 10 Days" table
    happens to show fewer rows than usual can never delete history we
    already collected on an earlier run. Records are applied in the order
    given, so if two records share a date (e.g. the "current rate" card and
    the historical table's own row for today), the later one in `records`
    wins -- callers should pass the historical rows first and the
    authoritative "current" rate last.

    Invalid entries (non-positive rate, malformed date) are silently
    skipped rather than raised, since this is a merge of already-scraped
    data where a single bad row must not block publishing everything else;
    build_json_payload still guards the final "current" rate strictly.
    """
    by_date: dict[str, float] = {}
    for entry in history or []:
        if isinstance(entry, dict) and _DATE_RE.match(entry.get("date") or ""):
            rate = entry.get("rate_per_gram")
            if isinstance(rate, (int, float)) and rate > 0:
                by_date[entry["date"]] = round(rate, 2)

    for record in records:
        date = record.date if isinstance(record, GoldRate) else record.get("date")
        rate = record.rate_per_gram if isinstance(record, GoldRate) else record.get("rate_per_gram")
        if not date or not _DATE_RE.match(date):
            logger.warning("Skipping history record with invalid date: %r", date)
            continue
        if not isinstance(rate, (int, float)) or rate <= 0:
            logger.warning("Skipping history record for %s with invalid rate: %r", date, rate)
            continue
        by_date[date] = round(rate, 2)

    merged = [{"date": date, "rate_per_gram": rate} for date, rate in by_date.items()]
    merged.sort(key=lambda entry: entry["date"])
    return merged[-max_entries:]


def upsert_history(
    history: list[dict], date: str, rate_per_gram: float, max_entries: int = MAX_HISTORY_ENTRIES
) -> list[dict]:
    """Adds a single day's entry to the history list, replacing any existing
    entry for the same date. A thin convenience wrapper around
    merge_history_records for the common one-record case."""
    return merge_history_records(history, [{"date": date, "rate_per_gram": rate_per_gram}], max_entries)


def _validate_current(rate: GoldRate, unit_a: Optional[float], unit_b: Optional[float], label: str) -> None:
    if rate.rate_per_gram is None or rate.rate_per_gram <= 0:
        raise DataExportError(f"Refusing to publish a non-positive {label} rate: {rate.rate_per_gram!r}")
    if unit_a is None or unit_b is None or unit_a <= 0 or unit_b <= 0:
        raise DataExportError(f"Refusing to publish non-positive {label} unit-quantity values")
    if not _DATE_RE.match(rate.date or ""):
        raise DataExportError(f"Refusing to publish an invalid {label} date: {rate.date!r}")


def _change_dict(change: Optional[RateChange]) -> dict:
    return {
        "absolute": change.absolute if change is not None else None,
        "percentage": change.percentage if change is not None else None,
    }


def build_json_payload(
    rate: GoldRate,
    rate_8g: float,
    rate_10g: float,
    change: Optional[RateChange],
    updated_at: str,
    history: list[dict],
    source_url: str,
    rate_24k: Optional[GoldRate] = None,
    rate_24k_8g: Optional[float] = None,
    rate_24k_10g: Optional[float] = None,
    change_24k: Optional[RateChange] = None,
    history_24k: Optional[list[dict]] = None,
    silver: Optional[GoldRate] = None,
    silver_100g: Optional[float] = None,
    silver_1kg: Optional[float] = None,
    change_silver: Optional[RateChange] = None,
    history_silver: Optional[list[dict]] = None,
    silver_source_url: Optional[str] = None,
) -> dict:
    """Shapes the public JSON payload. Raises DataExportError instead of
    returning a payload if the inputs look invalid -- this is the guard
    that prevents an invalid rate from ever overwriting the last known
    good data file.

    All top-level fields (source, city, purity, current, change, date,
    history, ...) describe the 22K gold rate exactly as before --
    unchanged, for backward compatibility with anything already reading
    this file. 24K gold is added under "gold_24k"; silver is added under
    a separate top-level "silver" key (a different asset, not a gold
    purity), with the same current/change/history shape but using
    silver's own units (rate_100g / rate_1kg instead of 8g/10g).

    rate_24k and silver are each optional and independent: when either is
    None (unavailable this run -- its own page/card/column couldn't be
    parsed, or its whole fetch failed), that section's "current"/"change"
    are emitted as null rather than fabricated or derived from the other
    asset, while its "history" (whatever was already collected, possibly
    extended by history_24k/history_silver) is preserved untouched. A
    22K failure is the only one that prevents this function from being
    called at all with real "today" data -- but even that case is handled
    by the caller refusing to call build_json_payload, not by this
    function fabricating a stand-in.
    """
    _validate_current(rate, rate_8g, rate_10g, "22K")

    gold_24k_current = None
    if rate_24k is not None:
        _validate_current(rate_24k, rate_24k_8g, rate_24k_10g, "24K")
        gold_24k_current = {
            "rate_per_gram": round(rate_24k.rate_per_gram, 2),
            "rate_8g": round(rate_24k_8g, 2),
            "rate_10g": round(rate_24k_10g, 2),
        }

    silver_current = None
    if silver is not None:
        _validate_current(silver, silver_100g, silver_1kg, "silver")
        silver_current = {
            "rate_per_gram": round(silver.rate_per_gram, 2),
            "rate_100g": round(silver_100g, 2),
            "rate_1kg": round(silver_1kg, 2),
        }

    return {
        "source": rate.source,
        "source_url": source_url,
        "city": rate.city,
        "purity": rate.purity,
        "current": {
            "rate_per_gram": round(rate.rate_per_gram, 2),
            "rate_8g": round(rate_8g, 2),
            "rate_10g": round(rate_10g, 2),
        },
        "change": _change_dict(change),
        "date": rate.date,
        "updated_at": updated_at,
        "history": history,
        "gold_24k": {
            "purity": "24K",
            "current": gold_24k_current,
            "change": _change_dict(change_24k),
            "date": rate_24k.date if rate_24k is not None else None,
            "history": history_24k if history_24k is not None else [],
        },
        "silver": {
            "asset": "Silver",
            "unit_note": "Per gram; also shown per 100g and per kg",
            "source": silver.source if silver is not None else "Goodreturns",
            "source_url": silver_source_url or "",
            "current": silver_current,
            "change": _change_dict(change_silver),
            "date": silver.date if silver is not None else None,
            "history": history_silver if history_silver is not None else [],
        },
    }


def write_json_atomic(payload: dict, path: Path = DEFAULT_JSON_PATH) -> None:
    """Writes the JSON file atomically (write to a temp file, then rename)
    so a crash or interrupted run can never leave a half-written, invalid
    file in place of the last known good one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)
    logger.info("Public data written to %s", path)
