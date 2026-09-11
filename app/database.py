"""
SQLite storage for historical gold rates.

Schema: one row per (date, city, purity), with an insert-or-update upsert so
re-running the app on the same day (e.g. testing, or a retry after a
transient failure) never creates duplicate rows.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "gold_rates.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gold_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    city TEXT NOT NULL,
    purity TEXT NOT NULL,
    rate_per_gram REAL NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(date, city, purity)
);
"""


@dataclass
class StoredRate:
    id: int
    date: str
    timestamp: str
    city: str
    purity: str
    rate_per_gram: float
    source: str


class GoldRateDatabase:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def insert_rate(
        self,
        city: str,
        purity: str,
        rate_per_gram: float,
        date: str,
        source: str,
    ) -> StoredRate:
        """Insert today's rate, or update it in place if a row for the same
        (date, city, purity) already exists -- this is a deliberate upsert,
        not a silent duplicate-avoidance no-op, so re-running the fetch on
        the same day always reflects the latest value."""
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gold_rates (date, timestamp, city, purity, rate_per_gram, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, city, purity) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    rate_per_gram = excluded.rate_per_gram,
                    source = excluded.source
                """,
                (date, timestamp, city, purity, rate_per_gram, source),
            )
            row = conn.execute(
                "SELECT * FROM gold_rates WHERE date = ? AND city = ? AND purity = ?",
                (date, city, purity),
            ).fetchone()

        logger.info("Database updated: %s %s %s -> Rs.%.2f/g", date, city, purity, rate_per_gram)
        return StoredRate(**dict(row))

    def get_rate_for_date(self, date: str, city: str, purity: str) -> Optional[StoredRate]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gold_rates WHERE date = ? AND city = ? AND purity = ?",
                (date, city, purity),
            ).fetchone()
        return StoredRate(**dict(row)) if row else None

    def get_latest_before(self, date: str, city: str, purity: str) -> Optional[StoredRate]:
        """Most recent stored rate strictly before the given date -- used as
        "yesterday's rate" even if yesterday itself has no row (e.g. a
        weekend gap or a missed run)."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM gold_rates
                WHERE date < ? AND city = ? AND purity = ?
                ORDER BY date DESC
                LIMIT 1
                """,
                (date, city, purity),
            ).fetchone()
        return StoredRate(**dict(row)) if row else None

    def get_last_n_rates(self, n: int, city: str, purity: str) -> list[StoredRate]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gold_rates
                WHERE city = ? AND purity = ?
                ORDER BY date DESC
                LIMIT ?
                """,
                (city, purity, n),
            ).fetchall()
        return [StoredRate(**dict(row)) for row in rows]
