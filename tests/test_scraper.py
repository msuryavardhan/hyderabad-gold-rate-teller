import unittest
from pathlib import Path
from unittest.mock import patch

from app.scraper import (
    GoldRateScraperError,
    get_hyderabad_gold_rates,
    get_hyderabad_silver_with_history,
    parse_hyderabad_22k,
    parse_hyderabad_22k_history,
    parse_hyderabad_24k,
    parse_hyderabad_24k_history,
    parse_hyderabad_silver,
    parse_hyderabad_silver_history,
    parse_price_string,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# A real, saved copy of https://www.goodreturns.in/gold-rates/hyderabad.html
# (fetched 2026-09-11). Known values at capture time: 24K=₹15,289,
# 22K=₹14,015, 18K=₹11,467, date="11 September 2026".
LIVE_SAMPLE_HTML = (FIXTURES_DIR / "hyderabad_live_sample.html").read_text(encoding="utf-8")

# A real, saved copy of https://www.goodreturns.in/silver-rates/hyderabad.html
# (fetched 2026-09-12). Known values at capture time: Silver /g=₹250,
# Silver /kg=₹2,50,000, date="12 September 2026". Its "Last 10 Days" table
# has 10g/100g/1kg columns only (no raw per-gram column).
SILVER_LIVE_SAMPLE_HTML = (FIXTURES_DIR / "silver_hyderabad_live_sample.html").read_text(encoding="utf-8")

CARD_TEMPLATE = """
<div class="gr-price-cards">
  <div class="gr-price-card">
    <div class="gr-price-card-label"><p>24K&nbsp;Gold&nbsp;<span>/g</span></p></div>
    <div class="gr-price-card-row"><div class="gr-price-card-value"><span id="24K-price">{v24}</span></div></div>
  </div>
  {maybe_22k}
  <div class="gr-price-card">
    <div class="gr-price-card-label"><p>18K&nbsp;Gold&nbsp;<span>/g</span></p></div>
    <div class="gr-price-card-row"><div class="gr-price-card-value"><span id="18K-price">{v18}</span></div></div>
  </div>
</div>
<span id="metal-price-date">{date}</span>
"""

CARD_22K = """
  <div class="gr-price-card">
    <div class="gr-price-card-label"><p>22K&nbsp;Gold&nbsp;<span>/g</span></p></div>
    <div class="gr-price-card-row"><div class="gr-price-card-value"><span id="22K-price">{v22}</span></div></div>
  </div>
"""


def build_html(v24="₹15,289", v22="₹14,015", v18="₹11,467", date="11 September 2026", include_22k=True):
    return CARD_TEMPLATE.format(
        v24=v24,
        v18=v18,
        date=date,
        maybe_22k=CARD_22K.format(v22=v22) if include_22k else "",
    )


class TestParsePriceString(unittest.TestCase):
    def test_rupee_symbol_with_commas(self):
        self.assertEqual(parse_price_string("₹14,255"), 14255.0)

    def test_plain_number_with_commas(self):
        self.assertEqual(parse_price_string("14,255"), 14255.0)

    def test_rupee_symbol_with_space(self):
        self.assertEqual(parse_price_string("₹ 14,255"), 14255.0)

    def test_no_commas(self):
        self.assertEqual(parse_price_string("14255"), 14255.0)

    def test_decimal_value(self):
        self.assertEqual(parse_price_string("14255.50"), 14255.50)

    def test_invalid_string_raises(self):
        with self.assertRaises(ValueError):
            parse_price_string("N/A")

    def test_zero_or_negative_rejected(self):
        with self.assertRaises(ValueError):
            parse_price_string("₹0")
        with self.assertRaises(ValueError):
            parse_price_string("-100")


class TestParseHyderabad22k(unittest.TestCase):
    def test_parses_live_sample_page(self):
        rate = parse_hyderabad_22k(LIVE_SAMPLE_HTML)
        self.assertEqual(rate.city, "Hyderabad")
        self.assertEqual(rate.purity, "22K")
        self.assertEqual(rate.rate_per_gram, 14015.0)
        self.assertEqual(rate.date, "2026-09-11")
        self.assertEqual(rate.source, "Goodreturns")

    def test_parses_minimal_synthetic_html(self):
        html = build_html()
        rate = parse_hyderabad_22k(html)
        self.assertEqual(rate.rate_per_gram, 14015.0)
        self.assertEqual(rate.date, "2026-09-11")

    def test_missing_22k_card_raises(self):
        html = build_html(include_22k=False)
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_22k(html)

    def test_completely_invalid_html_raises(self):
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_22k("<html><body><p>Not a gold rate page</p></body></html>")

    def test_missing_date_falls_back_without_crashing(self):
        html = build_html(date="")
        # No exception -- falls back to today's local date rather than failing
        # the whole scrape over a cosmetic date-label change.
        rate = parse_hyderabad_22k(html)
        self.assertEqual(rate.rate_per_gram, 14015.0)

    def test_malformed_price_raises(self):
        html = build_html(v22="N/A")
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_22k(html)


class TestParseHyderabad24k(unittest.TestCase):
    def test_parses_live_sample_page(self):
        rate = parse_hyderabad_24k(LIVE_SAMPLE_HTML)
        self.assertEqual(rate.city, "Hyderabad")
        self.assertEqual(rate.purity, "24K")
        self.assertEqual(rate.rate_per_gram, 15289.0)
        self.assertEqual(rate.date, "2026-09-11")
        self.assertEqual(rate.source, "Goodreturns")

    def test_parses_minimal_synthetic_html(self):
        html = build_html(v24="₹15,289")
        rate = parse_hyderabad_24k(html)
        self.assertEqual(rate.rate_per_gram, 15289.0)
        self.assertEqual(rate.date, "2026-09-11")

    def test_missing_24k_card_raises(self):
        # build_html always includes a 24K card (it's the first one in the
        # template) -- simulate its removal directly.
        html = """
        <div class="gr-price-cards">
          <div class="gr-price-card">
            <div class="gr-price-card-label"><p>22K&nbsp;Gold&nbsp;<span>/g</span></p></div>
            <div class="gr-price-card-row"><div class="gr-price-card-value"><span id="22K-price">₹14,015</span></div></div>
          </div>
        </div>
        <span id="metal-price-date">11 September 2026</span>
        """
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_24k(html)

    def test_completely_invalid_html_raises(self):
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_24k("<html><body><p>Not a gold rate page</p></body></html>")

    def test_malformed_price_raises(self):
        html = build_html(v24="N/A")
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_24k(html)

    def test_22k_and_24k_are_independent_on_shared_html(self):
        # The exact same page/markup must yield the correct, DIFFERENT
        # value for each purity -- never the same number, never mixed up.
        html = build_html(v24="₹15,289", v22="₹14,015")
        rate_22k = parse_hyderabad_22k(html)
        rate_24k = parse_hyderabad_24k(html)
        self.assertEqual(rate_22k.rate_per_gram, 14015.0)
        self.assertEqual(rate_24k.rate_per_gram, 15289.0)
        self.assertNotEqual(rate_22k.rate_per_gram, rate_24k.rate_per_gram)
        self.assertEqual(rate_22k.purity, "22K")
        self.assertEqual(rate_24k.purity, "24K")


# --- "Last 10 Days" historical table fixtures ---

HISTORY_SECTION_TEMPLATE = """
<section class="gr-table-section">
  <h2 class="gr-section-title table-headLine">Gold Rate in Hyderabad for Last 10 Days (1 gram)</h2>
  <div class="gr-table-wrap">
    <table class="gr-table">
      <thead class="tabelhead"><tr>{header}</tr></thead>
      <tbody class="tablebody">{rows}</tbody>
    </table>
  </div>
</section>
"""

HISTORY_ROW_TEMPLATE = """
<tr>
  <td>{date}</td>
  <td>{v24}<span class="red-span gr-delta-down">({delta24})</span></td>
  <td>{v22}<span class="red-span gr-delta-down">({delta22})</span></td>
</tr>
"""


def build_history_html(rows, header="<th>Date</th><th>24K</th><th>22K</th>"):
    rows_html = "".join(
        HISTORY_ROW_TEMPLATE.format(
            date=r.get("date", "Sep 11, 2026"),
            v24=r.get("v24", "₹15,289"),
            v22=r.get("v22", "₹14,015"),
            delta24=r.get("delta24", "-262"),
            delta22=r.get("delta22", "-240"),
        )
        for r in rows
    )
    return HISTORY_SECTION_TEMPLATE.format(header=header, rows=rows_html)


class TestParseHyderabad22kHistory(unittest.TestCase):
    def test_parses_live_sample_history(self):
        records = parse_hyderabad_22k_history(LIVE_SAMPLE_HTML)
        self.assertEqual(len(records), 10)
        by_date = {r.date: r.rate_per_gram for r in records}
        # Known values from the saved page at capture time (2026-09-11),
        # matching what Goodreturns itself published in its "Last 10 Days"
        # table -- these are read from the fixture, never hardcoded as the
        # thing being asserted-into-existence.
        self.assertEqual(by_date["2026-09-11"], 14015.0)
        self.assertEqual(by_date["2026-09-10"], 14255.0)
        self.assertEqual(by_date["2026-09-09"], 14145.0)
        self.assertEqual(by_date["2026-09-08"], 14240.0)
        for record in records:
            self.assertEqual(record.city, "Hyderabad")
            self.assertEqual(record.purity, "22K")
            self.assertEqual(record.source, "Goodreturns")

    def test_parses_dates_correctly(self):
        html = build_history_html([{"date": "Sep 05, 2026", "v22": "₹14,190"}])
        records = parse_hyderabad_22k_history(html)
        self.assertEqual(records[0].date, "2026-09-05")

    def test_parses_22k_values_by_header_not_fixed_position(self):
        # 22K listed BEFORE 24K -- in both the header AND the row cells --
        # the parser must follow the header labels, not assume a fixed
        # column index.
        html = HISTORY_SECTION_TEMPLATE.format(
            header="<th>Date</th><th>22K</th><th>24K</th>",
            rows="""
            <tr>
              <td>Sep 05, 2026</td>
              <td>₹14,190<span class="red-span">(-170)</span></td>
              <td>₹15,480<span class="red-span">(-186)</span></td>
            </tr>
            """,
        )
        records = parse_hyderabad_22k_history(html)
        self.assertEqual(records[0].rate_per_gram, 14190.0)

    def test_handles_commas_rupee_symbol_and_nested_delta_span(self):
        html = build_history_html([{"date": "Sep 10, 2026", "v22": "₹14,255", "delta22": "+110"}])
        records = parse_hyderabad_22k_history(html)
        # Must read the price, not the "(+110)" delta shown alongside it.
        self.assertEqual(records[0].rate_per_gram, 14255.0)

    def test_missing_or_malformed_rows_are_skipped_not_fabricated(self):
        html = build_history_html(
            [
                {"date": "Sep 11, 2026", "v22": "₹14,015"},
                {"date": "not a date", "v22": "₹14,255"},
                {"date": "Sep 09, 2026", "v22": "N/A"},
                {"date": "Sep 08, 2026", "v22": "₹14,240"},
            ]
        )
        records = parse_hyderabad_22k_history(html)
        dates = [r.date for r in records]
        self.assertEqual(dates, ["2026-09-11", "2026-09-08"])

    def test_fewer_than_ten_rows_returns_only_those_provided(self):
        html = build_history_html(
            [
                {"date": "Sep 11, 2026", "v22": "₹14,015"},
                {"date": "Sep 10, 2026", "v22": "₹14,255"},
                {"date": "Sep 09, 2026", "v22": "₹14,145"},
            ]
        )
        records = parse_hyderabad_22k_history(html)
        self.assertEqual(len(records), 3)

    def test_no_history_section_raises(self):
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_22k_history("<html><body><p>No history here</p></body></html>")

    def test_table_with_no_22k_column_raises(self):
        html = build_history_html(
            [{"date": "Sep 05, 2026"}], header="<th>Date</th><th>24K</th><th>18K</th>"
        )
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_22k_history(html)

    def test_all_rows_invalid_raises(self):
        html = build_history_html(
            [
                {"date": "not a date", "v22": "₹14,015"},
                {"date": "Sep 10, 2026", "v22": "N/A"},
            ]
        )
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_22k_history(html)


class TestParseHyderabad24kHistory(unittest.TestCase):
    def test_parses_live_sample_history(self):
        records = parse_hyderabad_24k_history(LIVE_SAMPLE_HTML)
        self.assertEqual(len(records), 10)
        by_date = {r.date: r.rate_per_gram for r in records}
        # Known values from the saved page at capture time (2026-09-11) --
        # read from the fixture, never hardcoded as the thing being
        # asserted-into-existence.
        self.assertEqual(by_date["2026-09-11"], 15289.0)
        self.assertEqual(by_date["2026-09-10"], 15551.0)
        self.assertEqual(by_date["2026-09-09"], 15431.0)
        self.assertEqual(by_date["2026-09-08"], 15535.0)
        for record in records:
            self.assertEqual(record.city, "Hyderabad")
            self.assertEqual(record.purity, "24K")
            self.assertEqual(record.source, "Goodreturns")

    def test_parses_dates_correctly(self):
        html = build_history_html([{"date": "Sep 05, 2026", "v24": "₹15,480"}])
        records = parse_hyderabad_24k_history(html)
        self.assertEqual(records[0].date, "2026-09-05")

    def test_parses_24k_values_by_header_not_fixed_position(self):
        html = HISTORY_SECTION_TEMPLATE.format(
            header="<th>Date</th><th>22K</th><th>24K</th>",
            rows="""
            <tr>
              <td>Sep 05, 2026</td>
              <td>₹14,190<span class="red-span">(-170)</span></td>
              <td>₹15,480<span class="red-span">(-186)</span></td>
            </tr>
            """,
        )
        records = parse_hyderabad_24k_history(html)
        self.assertEqual(records[0].rate_per_gram, 15480.0)

    def test_handles_commas_rupee_symbol_and_nested_delta_span(self):
        html = build_history_html([{"date": "Sep 10, 2026", "v24": "₹15,551", "delta24": "+120"}])
        records = parse_hyderabad_24k_history(html)
        self.assertEqual(records[0].rate_per_gram, 15551.0)

    def test_missing_or_malformed_rows_are_skipped_not_fabricated(self):
        html = build_history_html(
            [
                {"date": "Sep 11, 2026", "v24": "₹15,289"},
                {"date": "not a date", "v24": "₹15,551"},
                {"date": "Sep 09, 2026", "v24": "N/A"},
                {"date": "Sep 08, 2026", "v24": "₹15,535"},
            ]
        )
        records = parse_hyderabad_24k_history(html)
        dates = [r.date for r in records]
        self.assertEqual(dates, ["2026-09-11", "2026-09-08"])

    def test_fewer_than_ten_rows_returns_only_those_provided(self):
        html = build_history_html(
            [
                {"date": "Sep 11, 2026", "v24": "₹15,289"},
                {"date": "Sep 10, 2026", "v24": "₹15,551"},
            ]
        )
        records = parse_hyderabad_24k_history(html)
        self.assertEqual(len(records), 2)

    def test_no_history_section_raises(self):
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_24k_history("<html><body><p>No history here</p></body></html>")

    def test_table_with_no_24k_column_raises(self):
        html = build_history_html(
            [{"date": "Sep 05, 2026"}], header="<th>Date</th><th>22K</th><th>18K</th>"
        )
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_24k_history(html)

    def test_all_rows_invalid_raises(self):
        html = build_history_html(
            [
                {"date": "not a date", "v24": "₹15,289"},
                {"date": "Sep 10, 2026", "v24": "N/A"},
            ]
        )
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_24k_history(html)


class TestMultiplePuritiesOnSameDate(unittest.TestCase):
    """Both purities must be extractable independently from the exact same
    row/date without one contaminating the other."""

    def test_same_row_yields_correct_independent_values_for_each_purity(self):
        html = build_history_html(
            [{"date": "Sep 10, 2026", "v22": "₹14,255", "v24": "₹15,551"}]
        )
        records_22k = parse_hyderabad_22k_history(html)
        records_24k = parse_hyderabad_24k_history(html)
        self.assertEqual(records_22k[0].date, "2026-09-10")
        self.assertEqual(records_24k[0].date, "2026-09-10")
        self.assertEqual(records_22k[0].rate_per_gram, 14255.0)
        self.assertEqual(records_24k[0].rate_per_gram, 15551.0)
        self.assertEqual(records_22k[0].purity, "22K")
        self.assertEqual(records_24k[0].purity, "24K")

    def test_live_sample_has_matching_dates_for_both_purities(self):
        dates_22k = {r.date for r in parse_hyderabad_22k_history(LIVE_SAMPLE_HTML)}
        dates_24k = {r.date for r in parse_hyderabad_24k_history(LIVE_SAMPLE_HTML)}
        self.assertEqual(dates_22k, dates_24k)
        self.assertEqual(len(dates_22k), 10)


class TestGetHyderabadGoldRates(unittest.TestCase):
    """The combined orchestrator: one fetch, both purities' current rate
    and history, with 24K treated as best-effort."""

    def test_returns_both_purities_from_live_sample(self):
        with patch("app.scraper.fetch_page", return_value=LIVE_SAMPLE_HTML):
            data = get_hyderabad_gold_rates()

        self.assertEqual(data["22K"]["current"].rate_per_gram, 14015.0)
        self.assertEqual(len(data["22K"]["history"]), 10)
        self.assertEqual(data["24K"]["current"].rate_per_gram, 15289.0)
        self.assertEqual(len(data["24K"]["history"]), 10)

    def test_24k_unavailable_does_not_fail_22k(self):
        # A page with a valid 22K card/table but no 24K column anywhere.
        html_no_24k = build_html(include_22k=True).replace("24K", "XX")
        history_html = build_history_html(
            [{"date": "Sep 11, 2026", "v22": "₹14,015"}],
            header="<th>Date</th><th>XX</th><th>22K</th>",
        )
        combined_html = html_no_24k + history_html

        with patch("app.scraper.fetch_page", return_value=combined_html):
            data = get_hyderabad_gold_rates()

        self.assertEqual(data["22K"]["current"].rate_per_gram, 14015.0)
        self.assertIsNone(data["24K"]["current"])
        self.assertEqual(data["24K"]["history"], [])

    def test_22k_failure_raises(self):
        with patch("app.scraper.fetch_page", return_value="<html><body>nothing here</body></html>"):
            with self.assertRaises(GoldRateScraperError):
                get_hyderabad_gold_rates()


# --- Silver ---

SILVER_CARD_TEMPLATE = """
<div class="gr-price-cards" style="display: grid;grid-template-columns: repeat(2, 1fr);">
  <div class="gr-price-card">
    <div class="gr-price-card-label"><p>Silver&nbsp;<span>/g</span></p></div>
    <div class="gr-price-card-row"><div class="gr-price-card-value"><span id="silver-1g-price">{v1g}</span></div></div>
  </div>
  <div class="gr-price-card">
    <div class="gr-price-card-label"><p>Silver&nbsp;<span>/kg</span></p></div>
    <div class="gr-price-card-row"><div class="gr-price-card-value"><span id="silver-1kg-price">{v1kg}</span></div></div>
  </div>
</div>
<span id="metal-price-date">{date}</span>
"""

SILVER_HISTORY_SECTION_TEMPLATE = """
<section class="gr-table-section">
  <h2 class="gr-section-title table-headLine">Silver Rate in Hyderabad for Last 10 Days </h2>
  <div class="gr-table-wrap">
    <table class="gr-table">
      <thead class="tabelhead"><tr>{header}</tr></thead>
      <tbody class="tablebody">{rows}</tbody>
    </table>
  </div>
</section>
"""

SILVER_HISTORY_ROW_TEMPLATE = """
<tr>
  <td>{date}</td>
  <td>{v10g}<span class="non-span">(0)</span></td>
  <td>{v100g}<span class="non-span">(0)</span></td>
  <td>{v1kg}<span class="non-span">(0)</span></td>
</tr>
"""


def build_silver_html(v1g="₹250", v1kg="₹2,50,000", date="12 September 2026"):
    return SILVER_CARD_TEMPLATE.format(v1g=v1g, v1kg=v1kg, date=date)


def build_silver_history_html(
    rows, header="<th>Date</th><th>10 gram</th><th>100 gram</th><th>1 Kg</th>"
):
    rows_html = "".join(
        SILVER_HISTORY_ROW_TEMPLATE.format(
            date=r.get("date", "Sep 12, 2026"),
            v10g=r.get("v10g", "₹2,500"),
            v100g=r.get("v100g", "₹25,000"),
            v1kg=r.get("v1kg", "₹2,50,000"),
        )
        for r in rows
    )
    return SILVER_HISTORY_SECTION_TEMPLATE.format(header=header, rows=rows_html)


class TestParseHyderabadSilver(unittest.TestCase):
    def test_parses_live_sample_page(self):
        rate = parse_hyderabad_silver(SILVER_LIVE_SAMPLE_HTML)
        self.assertEqual(rate.city, "Hyderabad")
        self.assertEqual(rate.purity, "Silver")
        self.assertEqual(rate.rate_per_gram, 250.0)
        self.assertEqual(rate.date, "2026-09-12")
        self.assertEqual(rate.source, "Goodreturns")

    def test_parses_minimal_synthetic_html(self):
        html = build_silver_html(v1g="₹250")
        rate = parse_hyderabad_silver(html)
        self.assertEqual(rate.rate_per_gram, 250.0)

    def test_does_not_pick_up_the_per_kg_card(self):
        # A silver-specific regression: "/g" must never accidentally match
        # the "/kg" card's trailing "g".
        html = build_silver_html(v1g="₹250", v1kg="₹9,99,999")
        rate = parse_hyderabad_silver(html)
        self.assertEqual(rate.rate_per_gram, 250.0)

    def test_missing_silver_card_raises(self):
        html = "<div class='gr-price-cards'></div><span id='metal-price-date'>12 September 2026</span>"
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_silver(html)

    def test_completely_invalid_html_raises(self):
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_silver("<html><body><p>Not a rate page</p></body></html>")

    def test_malformed_price_raises(self):
        html = build_silver_html(v1g="N/A")
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_silver(html)

    def test_never_derived_from_gold(self):
        # Silver and gold parsers must be fully independent -- a page with
        # both a gold card and a silver card must not let one leak into
        # the other's result.
        combined_html = build_html(v22="₹14,015", v24="₹15,289") + build_silver_html(v1g="₹250")
        silver_rate = parse_hyderabad_silver(combined_html)
        self.assertEqual(silver_rate.rate_per_gram, 250.0)


class TestParseHyderabadSilverHistory(unittest.TestCase):
    def test_parses_live_sample_history(self):
        records = parse_hyderabad_silver_history(SILVER_LIVE_SAMPLE_HTML)
        self.assertEqual(len(records), 10)
        by_date = {r.date: r.rate_per_gram for r in records}
        # Known values read from the fixture (2026-09-12 capture) --
        # derived by exact division of the published 1kg/100g/10g figures,
        # never estimated and never taken from gold.
        self.assertEqual(by_date["2026-09-12"], 250.0)
        self.assertEqual(by_date["2026-09-11"], 250.0)
        self.assertEqual(by_date["2026-09-10"], 255.0)
        for record in records:
            self.assertEqual(record.city, "Hyderabad")
            self.assertEqual(record.purity, "Silver")
            self.assertEqual(record.source, "Goodreturns")

    def test_parses_dates_correctly(self):
        html = build_silver_history_html([{"date": "Sep 05, 2026", "v1kg": "₹2,55,000"}])
        records = parse_hyderabad_silver_history(html)
        self.assertEqual(records[0].date, "2026-09-05")

    def test_derives_per_gram_from_1kg_column_exactly(self):
        html = build_silver_history_html([{"date": "Sep 12, 2026", "v1kg": "₹2,50,000"}])
        records = parse_hyderabad_silver_history(html)
        self.assertEqual(records[0].rate_per_gram, 250.0)

    def test_derives_per_gram_from_100g_when_1kg_column_absent(self):
        html = build_silver_history_html(
            [{"date": "Sep 12, 2026", "v100g": "₹25,000"}],
            header="<th>Date</th><th>10 gram</th><th>100 gram</th>",
        )
        records = parse_hyderabad_silver_history(html)
        self.assertEqual(records[0].rate_per_gram, 250.0)

    def test_derives_per_gram_from_10g_when_only_that_present(self):
        html = build_silver_history_html(
            [{"date": "Sep 12, 2026", "v10g": "₹2,500"}],
            header="<th>Date</th><th>10 gram</th>",
        )
        records = parse_hyderabad_silver_history(html)
        self.assertEqual(records[0].rate_per_gram, 250.0)

    def test_handles_commas_rupee_symbol_and_nested_delta_span(self):
        html = build_silver_history_html([{"date": "Sep 10, 2026", "v1kg": "₹2,55,000"}])
        records = parse_hyderabad_silver_history(html)
        self.assertEqual(records[0].rate_per_gram, 255.0)

    def test_missing_or_malformed_rows_are_skipped_not_fabricated(self):
        html = build_silver_history_html(
            [
                {"date": "Sep 12, 2026", "v1kg": "₹2,50,000"},
                {"date": "not a date", "v1kg": "₹2,55,000"},
                {"date": "Sep 10, 2026", "v1kg": "N/A"},
                {"date": "Sep 09, 2026", "v1kg": "₹2,55,000"},
            ]
        )
        records = parse_hyderabad_silver_history(html)
        dates = [r.date for r in records]
        self.assertEqual(dates, ["2026-09-12", "2026-09-09"])

    def test_fewer_than_ten_rows_returns_only_those_provided(self):
        html = build_silver_history_html(
            [
                {"date": "Sep 12, 2026", "v1kg": "₹2,50,000"},
                {"date": "Sep 11, 2026", "v1kg": "₹2,50,000"},
                {"date": "Sep 10, 2026", "v1kg": "₹2,55,000"},
            ]
        )
        records = parse_hyderabad_silver_history(html)
        self.assertEqual(len(records), 3)

    def test_no_history_section_raises(self):
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_silver_history("<html><body><p>No history here</p></body></html>")

    def test_table_with_no_recognised_unit_column_raises(self):
        html = build_silver_history_html(
            [{"date": "Sep 12, 2026"}], header="<th>Date</th><th>Some Other Column</th>"
        )
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_silver_history(html)

    def test_all_rows_invalid_raises(self):
        html = build_silver_history_html(
            [
                {"date": "not a date", "v1kg": "₹2,50,000"},
                {"date": "Sep 10, 2026", "v1kg": "N/A"},
            ]
        )
        with self.assertRaises(GoldRateScraperError):
            parse_hyderabad_silver_history(html)

    def test_chronological_sort_is_caller_responsibility_but_dates_are_exact(self):
        # The parser returns rows in page order (newest first here); exact
        # date correctness (not sorting) is what this parser guarantees --
        # merge_history_records (tested separately) handles sorting.
        html = build_silver_history_html(
            [
                {"date": "Sep 10, 2026", "v1kg": "₹2,55,000"},
                {"date": "Sep 12, 2026", "v1kg": "₹2,50,000"},
            ]
        )
        records = parse_hyderabad_silver_history(html)
        self.assertEqual([r.date for r in records], ["2026-09-10", "2026-09-12"])


class TestGetHyderabadSilverWithHistory(unittest.TestCase):
    def test_returns_current_and_history_from_live_sample(self):
        with patch("app.scraper.fetch_page", return_value=SILVER_LIVE_SAMPLE_HTML):
            rate, history = get_hyderabad_silver_with_history()
        self.assertEqual(rate.rate_per_gram, 250.0)
        self.assertEqual(rate.purity, "Silver")
        self.assertEqual(len(history), 10)

    def test_failure_raises_and_never_fabricates(self):
        with patch("app.scraper.fetch_page", return_value="<html><body>nothing</body></html>"):
            with self.assertRaises(GoldRateScraperError):
                get_hyderabad_silver_with_history()


if __name__ == "__main__":
    unittest.main()
