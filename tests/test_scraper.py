import unittest
from pathlib import Path

from app.scraper import (
    GoldRateScraperError,
    parse_hyderabad_22k,
    parse_hyderabad_22k_history,
    parse_price_string,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# A real, saved copy of https://www.goodreturns.in/gold-rates/hyderabad.html
# (fetched 2026-09-11). Known values at capture time: 24K=₹15,289,
# 22K=₹14,015, 18K=₹11,467, date="11 September 2026".
LIVE_SAMPLE_HTML = (FIXTURES_DIR / "hyderabad_live_sample.html").read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
