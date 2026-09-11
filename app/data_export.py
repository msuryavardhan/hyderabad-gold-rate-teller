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
from typing import Optional

from app.calculator import RateChange
from app.scraper import GoldRate

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


def upsert_history(
    history: list[dict], date: str, rate_per_gram: float, max_entries: int = MAX_HISTORY_ENTRIES
) -> list[dict]:
    """Adds today's entry to the history list, replacing any existing entry
    for the same date (so re-running the pipeline twice in one day updates
    that day's value instead of creating a duplicate). Keeps the list
    sorted ascending by date and trimmed to the most recent max_entries."""
    filtered = [
        entry
        for entry in (history or [])
        if isinstance(entry, dict) and entry.get("date") != date
    ]
    filtered.append({"date": date, "rate_per_gram": round(rate_per_gram, 2)})
    filtered.sort(key=lambda entry: entry["date"])
    return filtered[-max_entries:]


def build_json_payload(
    rate: GoldRate,
    rate_8g: float,
    rate_10g: float,
    change: Optional[RateChange],
    updated_at: str,
    history: list[dict],
    source_url: str,
) -> dict:
    """Shapes the public JSON payload. Raises DataExportError instead of
    returning a payload if the inputs look invalid -- this is the guard
    that prevents an invalid rate from ever overwriting the last known
    good data file."""
    if rate.rate_per_gram is None or rate.rate_per_gram <= 0:
        raise DataExportError(f"Refusing to publish a non-positive rate: {rate.rate_per_gram!r}")
    if rate_8g <= 0 or rate_10g <= 0:
        raise DataExportError("Refusing to publish non-positive 8g/10g values")
    if not _DATE_RE.match(rate.date or ""):
        raise DataExportError(f"Refusing to publish an invalid date: {rate.date!r}")

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
        "change": {
            "absolute": change.absolute if change is not None else None,
            "percentage": change.percentage if change is not None else None,
        },
        "date": rate.date,
        "updated_at": updated_at,
        "history": history,
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
