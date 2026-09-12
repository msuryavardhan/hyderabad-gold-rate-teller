import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from app.calculator import calculate_change
from app.data_export import (
    DataExportError,
    build_json_payload,
    find_previous_rate,
    load_existing_json,
    merge_history_records,
    upsert_history,
    write_json_atomic,
)
from app.scraper import GoldRate

SOURCE_URL = "https://www.goodreturns.in/gold-rates/hyderabad.html"


def make_rate(rate_per_gram=14015.0, date="2026-09-11", purity="22K"):
    return GoldRate(
        city="Hyderabad",
        purity=purity,
        rate_per_gram=rate_per_gram,
        date=date,
        source="Goodreturns",
    )


class TestBuildJsonPayload(unittest.TestCase):
    def test_valid_payload_shape(self):
        rate = make_rate()
        change = calculate_change(14015.0, 14100.0)
        payload = build_json_payload(
            rate=rate,
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=change,
            updated_at="2026-09-11T09:00:00+05:30",
            history=[{"date": "2026-09-11", "rate_per_gram": 14015.0}],
            source_url=SOURCE_URL,
        )
        self.assertEqual(payload["source"], "Goodreturns")
        self.assertEqual(payload["city"], "Hyderabad")
        self.assertEqual(payload["purity"], "22K")
        self.assertEqual(payload["current"]["rate_per_gram"], 14015.0)
        self.assertEqual(payload["current"]["rate_8g"], 112120.0)
        self.assertEqual(payload["current"]["rate_10g"], 140150.0)
        self.assertEqual(payload["change"]["absolute"], -85)
        self.assertEqual(payload["date"], "2026-09-11")
        self.assertEqual(payload["source_url"], SOURCE_URL)
        # Must be JSON-serializable (this is the point of the whole module).
        json.dumps(payload)

    def test_change_is_null_when_no_previous_rate(self):
        payload = build_json_payload(
            rate=make_rate(),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=None,
            updated_at="2026-09-11T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
        )
        self.assertIsNone(payload["change"]["absolute"])
        self.assertIsNone(payload["change"]["percentage"])

    def test_non_positive_rate_is_rejected(self):
        with self.assertRaises(DataExportError):
            build_json_payload(
                rate=make_rate(rate_per_gram=0),
                rate_8g=0,
                rate_10g=0,
                change=None,
                updated_at="2026-09-11T09:00:00+05:30",
                history=[],
                source_url=SOURCE_URL,
            )

    def test_negative_rate_is_rejected(self):
        with self.assertRaises(DataExportError):
            build_json_payload(
                rate=make_rate(rate_per_gram=-5),
                rate_8g=100,
                rate_10g=100,
                change=None,
                updated_at="2026-09-11T09:00:00+05:30",
                history=[],
                source_url=SOURCE_URL,
            )

    def test_invalid_date_is_rejected(self):
        with self.assertRaises(DataExportError):
            build_json_payload(
                rate=make_rate(date="11 September 2026"),
                rate_8g=112120.0,
                rate_10g=140150.0,
                change=None,
                updated_at="2026-09-11T09:00:00+05:30",
                history=[],
                source_url=SOURCE_URL,
            )


class TestBuildJsonPayload24k(unittest.TestCase):
    """The 22K fields above must stay exactly as they were -- these tests
    cover the additive "gold_24k" section only."""

    def test_existing_22k_structure_is_unchanged_when_24k_included(self):
        payload = build_json_payload(
            rate=make_rate(),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=calculate_change(14015.0, 14255.0),
            updated_at="2026-09-11T09:00:00+05:30",
            history=[{"date": "2026-09-11", "rate_per_gram": 14015.0}],
            source_url=SOURCE_URL,
            rate_24k=make_rate(rate_per_gram=15289.0, purity="24K"),
            rate_24k_8g=122312.0,
            rate_24k_10g=152890.0,
            change_24k=calculate_change(15289.0, 15551.0),
            history_24k=[{"date": "2026-09-11", "rate_per_gram": 15289.0}],
        )
        # Top-level 22K fields: same shape/values as before this feature.
        self.assertEqual(payload["purity"], "22K")
        self.assertEqual(payload["current"]["rate_per_gram"], 14015.0)
        self.assertEqual(payload["change"]["absolute"], -240)

    def test_gold_24k_section_populated_with_real_values(self):
        payload = build_json_payload(
            rate=make_rate(),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=None,
            updated_at="2026-09-11T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
            rate_24k=make_rate(rate_per_gram=15289.0, purity="24K"),
            rate_24k_8g=122312.0,
            rate_24k_10g=152890.0,
            change_24k=calculate_change(15289.0, 15551.0),
            history_24k=[
                {"date": "2026-09-10", "rate_per_gram": 15551.0},
                {"date": "2026-09-11", "rate_per_gram": 15289.0},
            ],
        )
        gold_24k = payload["gold_24k"]
        self.assertEqual(gold_24k["purity"], "24K")
        self.assertEqual(gold_24k["current"]["rate_per_gram"], 15289.0)
        self.assertEqual(gold_24k["current"]["rate_8g"], 122312.0)
        self.assertEqual(gold_24k["current"]["rate_10g"], 152890.0)
        self.assertEqual(gold_24k["change"]["absolute"], -262)
        self.assertEqual(len(gold_24k["history"]), 2)
        json.dumps(payload)  # must stay serializable

    def test_24k_omitted_by_default_is_null_not_fabricated(self):
        payload = build_json_payload(
            rate=make_rate(),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=None,
            updated_at="2026-09-11T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
        )
        gold_24k = payload["gold_24k"]
        self.assertIsNone(gold_24k["current"])
        self.assertIsNone(gold_24k["change"]["absolute"])
        self.assertIsNone(gold_24k["change"]["percentage"])
        self.assertEqual(gold_24k["history"], [])

    def test_24k_unavailable_preserves_prior_24k_history(self):
        # 24K's current rate is unavailable this run, but history collected
        # on earlier runs must still be published, not wiped.
        payload = build_json_payload(
            rate=make_rate(),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=None,
            updated_at="2026-09-11T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
            rate_24k=None,
            history_24k=[{"date": "2026-09-10", "rate_per_gram": 15551.0}],
        )
        gold_24k = payload["gold_24k"]
        self.assertIsNone(gold_24k["current"])
        self.assertEqual(gold_24k["history"], [{"date": "2026-09-10", "rate_per_gram": 15551.0}])

    def test_non_positive_24k_rate_is_rejected(self):
        with self.assertRaises(DataExportError):
            build_json_payload(
                rate=make_rate(),
                rate_8g=112120.0,
                rate_10g=140150.0,
                change=None,
                updated_at="2026-09-11T09:00:00+05:30",
                history=[],
                source_url=SOURCE_URL,
                rate_24k=make_rate(rate_per_gram=0, purity="24K"),
                rate_24k_8g=0,
                rate_24k_10g=0,
            )

    def test_missing_24k_gram_values_rejected(self):
        with self.assertRaises(DataExportError):
            build_json_payload(
                rate=make_rate(),
                rate_8g=112120.0,
                rate_10g=140150.0,
                change=None,
                updated_at="2026-09-11T09:00:00+05:30",
                history=[],
                source_url=SOURCE_URL,
                rate_24k=make_rate(rate_per_gram=15289.0, purity="24K"),
                # rate_24k_8g / rate_24k_10g omitted -- must not proceed with
                # a partially-fabricated 24K entry.
            )

    def test_22k_and_24k_changes_are_never_conflated(self):
        payload = build_json_payload(
            rate=make_rate(rate_per_gram=14015.0),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=calculate_change(14015.0, 14255.0),
            updated_at="2026-09-11T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
            rate_24k=make_rate(rate_per_gram=15289.0, purity="24K"),
            rate_24k_8g=122312.0,
            rate_24k_10g=152890.0,
            change_24k=calculate_change(15289.0, 15551.0),
            history_24k=[],
        )
        self.assertEqual(payload["change"]["absolute"], -240)
        self.assertEqual(payload["gold_24k"]["change"]["absolute"], -262)
        self.assertNotEqual(payload["change"]["absolute"], payload["gold_24k"]["change"]["absolute"])


class TestBuildJsonPayloadSilver(unittest.TestCase):
    """Silver lives in its own top-level "silver" key with its own units
    (100g/1kg, not gold's 8g/10g) -- these tests cover that section only;
    the 22K fields are asserted unaffected."""

    def test_silver_section_populated_with_real_values(self):
        payload = build_json_payload(
            rate=make_rate(),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=None,
            updated_at="2026-09-12T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
            silver=make_rate(rate_per_gram=250.0, date="2026-09-12", purity="Silver"),
            silver_100g=25000.0,
            silver_1kg=250000.0,
            change_silver=calculate_change(250.0, 255.0),
            history_silver=[
                {"date": "2026-09-11", "rate_per_gram": 255.0},
                {"date": "2026-09-12", "rate_per_gram": 250.0},
            ],
            silver_source_url="https://www.goodreturns.in/silver-rates/hyderabad.html",
        )
        silver = payload["silver"]
        self.assertEqual(silver["current"]["rate_per_gram"], 250.0)
        self.assertEqual(silver["current"]["rate_100g"], 25000.0)
        self.assertEqual(silver["current"]["rate_1kg"], 250000.0)
        self.assertEqual(silver["change"]["absolute"], -5)
        self.assertEqual(len(silver["history"]), 2)
        self.assertEqual(silver["source_url"], "https://www.goodreturns.in/silver-rates/hyderabad.html")
        self.assertEqual(silver["asset"], "Silver")
        # 22K's own fields are untouched by adding silver.
        self.assertEqual(payload["current"]["rate_per_gram"], 14015.0)
        json.dumps(payload)  # must stay serializable

    def test_silver_omitted_by_default_is_null_not_fabricated(self):
        payload = build_json_payload(
            rate=make_rate(),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=None,
            updated_at="2026-09-12T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
        )
        silver = payload["silver"]
        self.assertIsNone(silver["current"])
        self.assertIsNone(silver["change"]["absolute"])
        self.assertEqual(silver["history"], [])

    def test_silver_unavailable_preserves_prior_silver_history(self):
        payload = build_json_payload(
            rate=make_rate(),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=None,
            updated_at="2026-09-12T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
            silver=None,
            history_silver=[{"date": "2026-09-11", "rate_per_gram": 255.0}],
        )
        self.assertIsNone(payload["silver"]["current"])
        self.assertEqual(payload["silver"]["history"], [{"date": "2026-09-11", "rate_per_gram": 255.0}])

    def test_non_positive_silver_rate_is_rejected(self):
        with self.assertRaises(DataExportError):
            build_json_payload(
                rate=make_rate(),
                rate_8g=112120.0,
                rate_10g=140150.0,
                change=None,
                updated_at="2026-09-12T09:00:00+05:30",
                history=[],
                source_url=SOURCE_URL,
                silver=make_rate(rate_per_gram=0, purity="Silver"),
                silver_100g=0,
                silver_1kg=0,
            )

    def test_missing_silver_unit_values_rejected(self):
        with self.assertRaises(DataExportError):
            build_json_payload(
                rate=make_rate(),
                rate_8g=112120.0,
                rate_10g=140150.0,
                change=None,
                updated_at="2026-09-12T09:00:00+05:30",
                history=[],
                source_url=SOURCE_URL,
                silver=make_rate(rate_per_gram=250.0, purity="Silver"),
                # silver_100g / silver_1kg omitted -- must not proceed with
                # a partially-fabricated silver entry.
            )

    def test_silver_never_derived_from_gold(self):
        payload = build_json_payload(
            rate=make_rate(rate_per_gram=14015.0),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=None,
            updated_at="2026-09-12T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
            silver=make_rate(rate_per_gram=250.0, purity="Silver"),
            silver_100g=25000.0,
            silver_1kg=250000.0,
        )
        # Silver's rate must be exactly what was passed in -- nothing
        # computed from the gold rate 14015.0.
        self.assertEqual(payload["silver"]["current"]["rate_per_gram"], 250.0)
        self.assertNotEqual(payload["silver"]["current"]["rate_per_gram"], payload["current"]["rate_per_gram"])

    def test_gold_and_silver_changes_never_conflated(self):
        payload = build_json_payload(
            rate=make_rate(rate_per_gram=14015.0),
            rate_8g=112120.0,
            rate_10g=140150.0,
            change=calculate_change(14015.0, 14255.0),
            updated_at="2026-09-12T09:00:00+05:30",
            history=[],
            source_url=SOURCE_URL,
            silver=make_rate(rate_per_gram=250.0, purity="Silver"),
            silver_100g=25000.0,
            silver_1kg=250000.0,
            change_silver=calculate_change(250.0, 255.0),
        )
        self.assertEqual(payload["change"]["absolute"], -240)
        self.assertEqual(payload["silver"]["change"]["absolute"], -5)


class TestUpsertHistory(unittest.TestCase):
    def test_adds_new_entry_sorted(self):
        history = [{"date": "2026-09-09", "rate_per_gram": 13900.0}]
        result = upsert_history(history, "2026-09-10", 13950.0)
        self.assertEqual([h["date"] for h in result], ["2026-09-09", "2026-09-10"])

    def test_updates_existing_same_date_without_duplicating(self):
        history = [
            {"date": "2026-09-10", "rate_per_gram": 13950.0},
            {"date": "2026-09-11", "rate_per_gram": 14015.0},
        ]
        result = upsert_history(history, "2026-09-11", 14100.0)
        self.assertEqual(len(result), 2)
        today_entry = next(h for h in result if h["date"] == "2026-09-11")
        self.assertEqual(today_entry["rate_per_gram"], 14100.0)

    def test_trims_to_max_entries(self):
        history = [{"date": f"2026-01-{d:02d}", "rate_per_gram": 10000 + d} for d in range(1, 11)]
        result = upsert_history(history, "2026-01-11", 10011, max_entries=5)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[-1]["date"], "2026-01-11")
        self.assertEqual(result[0]["date"], "2026-01-07")


class TestFindPreviousRate(unittest.TestCase):
    def test_no_existing_data_returns_none(self):
        self.assertIsNone(find_previous_rate(None, "2026-09-11"))

    def test_finds_latest_before_today(self):
        existing = {
            "history": [
                {"date": "2026-09-09", "rate_per_gram": 13900.0},
                {"date": "2026-09-10", "rate_per_gram": 13950.0},
            ]
        }
        self.assertEqual(find_previous_rate(existing, "2026-09-11"), 13950.0)

    def test_ignores_entries_on_or_after_today(self):
        existing = {"history": [{"date": "2026-09-11", "rate_per_gram": 14015.0}]}
        self.assertIsNone(find_previous_rate(existing, "2026-09-11"))

    def test_empty_history_returns_none(self):
        self.assertIsNone(find_previous_rate({"history": []}, "2026-09-11"))


class TestLoadExistingJson(unittest.TestCase):
    def test_missing_file_returns_none(self):
        with TemporaryDirectory() as tmp:
            self.assertIsNone(load_existing_json(Path(tmp) / "missing.json"))

    def test_corrupt_file_returns_none_without_raising(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrupt.json"
            path.write_text("{not valid json", encoding="utf-8")
            self.assertIsNone(load_existing_json(path))

    def test_unexpected_shape_returns_none(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "shape.json"
            path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
            self.assertIsNone(load_existing_json(path))

    def test_valid_file_round_trips(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.json"
            payload = {"history": [{"date": "2026-09-10", "rate_per_gram": 13950.0}]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_existing_json(path)
            self.assertEqual(loaded, payload)


class TestWriteJsonAtomic(unittest.TestCase):
    def test_writes_valid_json_and_no_leftover_temp_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "gold_rates.json"
            payload = {"city": "Hyderabad", "history": []}
            write_json_atomic(payload, path)

            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)

            tmp_path = path.with_suffix(path.suffix + ".tmp")
            self.assertFalse(tmp_path.exists())

    def test_overwrites_previous_content(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold_rates.json"
            write_json_atomic({"version": 1}, path)
            write_json_atomic({"version": 2}, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 2)


class TestMergeHistoryRecords(unittest.TestCase):
    def test_merges_goldrate_objects(self):
        records = [
            make_rate(rate_per_gram=14255.0, date="2026-09-10"),
            make_rate(rate_per_gram=14015.0, date="2026-09-11"),
        ]
        result = merge_history_records([], records)
        self.assertEqual(
            result,
            [
                {"date": "2026-09-10", "rate_per_gram": 14255.0},
                {"date": "2026-09-11", "rate_per_gram": 14015.0},
            ],
        )

    def test_duplicate_dates_collapse_to_one_entry(self):
        existing = [{"date": "2026-09-11", "rate_per_gram": 14000.0}]
        records = [
            make_rate(rate_per_gram=14010.0, date="2026-09-11"),
            make_rate(rate_per_gram=14015.0, date="2026-09-11"),  # same date again
        ]
        result = merge_history_records(existing, records)
        self.assertEqual(len(result), 1)
        # Later record in the list wins -- callers rely on this to let the
        # authoritative "current" rate override a same-day historical row.
        self.assertEqual(result[0]["rate_per_gram"], 14015.0)

    def test_sorts_chronologically_regardless_of_input_order(self):
        records = [
            make_rate(rate_per_gram=14015.0, date="2026-09-11"),
            make_rate(rate_per_gram=13935.0, date="2026-09-02"),
            make_rate(rate_per_gram=14360.0, date="2026-09-04"),
        ]
        result = merge_history_records([], records)
        self.assertEqual([r["date"] for r in result], ["2026-09-02", "2026-09-04", "2026-09-11"])

    def test_never_deletes_existing_dates_not_mentioned_again(self):
        # Simulates Goodreturns temporarily showing fewer rows than a
        # previous run already collected -- old dates must survive.
        existing = [
            {"date": "2026-08-01", "rate_per_gram": 13500.0},
            {"date": "2026-08-02", "rate_per_gram": 13520.0},
        ]
        new_records = [make_rate(rate_per_gram=14015.0, date="2026-09-11")]
        result = merge_history_records(existing, new_records)
        dates = [r["date"] for r in result]
        self.assertIn("2026-08-01", dates)
        self.assertIn("2026-08-02", dates)
        self.assertIn("2026-09-11", dates)

    def test_invalid_records_are_skipped_not_fabricated(self):
        records = [
            make_rate(rate_per_gram=0, date="2026-09-11"),  # non-positive
            make_rate(rate_per_gram=14015.0, date="not-a-date"),  # bad date
        ]
        result = merge_history_records([], records)
        self.assertEqual(result, [])

    def test_accepts_plain_dicts_too(self):
        result = merge_history_records([], [{"date": "2026-09-11", "rate_per_gram": 14015.0}])
        self.assertEqual(result, [{"date": "2026-09-11", "rate_per_gram": 14015.0}])


class TestChangeAgainstPreviousAvailableDate(unittest.TestCase):
    """The user's worked example: today ₹14,015 vs the immediately
    preceding *available* date (not an assumed "yesterday")."""

    def test_matches_worked_example(self):
        history = merge_history_records(
            [],
            [
                make_rate(rate_per_gram=14255.0, date="2026-09-10"),
                make_rate(rate_per_gram=14015.0, date="2026-09-11"),
            ],
        )
        previous = find_previous_rate({"history": history}, "2026-09-11")
        self.assertEqual(previous, 14255.0)
        change = calculate_change(14015.0, previous)
        self.assertEqual(change.absolute, -240)
        self.assertAlmostEqual(change.percentage, -1.68, places=2)

    def test_skips_gap_to_find_previous_available_date(self):
        # No entry for "yesterday" (2026-09-10) -- must not assume it was
        # equal to today or invent a value; must fall back to the actual
        # most recent earlier date.
        history = merge_history_records(
            [],
            [
                make_rate(rate_per_gram=13935.0, date="2026-09-02"),
                make_rate(rate_per_gram=14015.0, date="2026-09-11"),
            ],
        )
        previous = find_previous_rate({"history": history}, "2026-09-11")
        self.assertEqual(previous, 13935.0)


class TestDashboardRangeData(unittest.TestCase):
    """The exported history array must be directly usable for the
    dashboard's 7D/30D slicing: sorted ascending, real dates only, and
    simply sliceable from the end -- no fabricated padding when fewer
    records exist than the requested window."""

    def _history_for(self, n_days):
        base = date(2026, 8, 1)
        records = [
            make_rate(rate_per_gram=14000.0 + i, date=(base + timedelta(days=i)).isoformat())
            for i in range(n_days)
        ]
        return merge_history_records([], records)

    def test_7_day_window_with_full_history(self):
        history = self._history_for(30)
        last_7 = history[-7:]
        self.assertEqual(len(last_7), 7)
        self.assertEqual(last_7[-1]["date"], history[-1]["date"])
        expected_first = (date(2026, 8, 1) + timedelta(days=29 - 6)).isoformat()
        self.assertEqual(last_7[0]["date"], expected_first)

    def test_30_day_window_with_full_history(self):
        history = self._history_for(45)
        last_30 = history[-30:]
        self.assertEqual(len(last_30), 30)
        self.assertEqual(last_30[-1]["date"], history[-1]["date"])

    def test_7_day_window_with_fewer_records_shows_only_real_ones(self):
        history = self._history_for(3)
        last_7 = history[-7:]
        # Must not be padded out to 7 -- only the 3 real days exist.
        self.assertEqual(len(last_7), 3)

    def test_30_day_window_with_fewer_records_shows_only_real_ones(self):
        history = self._history_for(10)
        last_30 = history[-30:]
        self.assertEqual(len(last_30), 10)


if __name__ == "__main__":
    unittest.main()
