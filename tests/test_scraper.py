import unittest
from pathlib import Path

from app.scraper import (
    GoldRateScraperError,
    parse_hyderabad_22k,
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


if __name__ == "__main__":
    unittest.main()
