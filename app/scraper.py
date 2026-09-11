"""
Scraper for the Goodreturns Hyderabad gold-rate page.

Source: https://www.goodreturns.in/gold-rates/hyderabad.html

The page server-renders three "price cards" (24K, 22K, 18K) each containing
a label paragraph (e.g. "22K Gold /g") and a value span whose id follows the
pattern "<purity>K-price" (e.g. id="22K-price", text "₹14,015"). The current
date is shown separately in a <span id="metal-price-date"> element
(e.g. "11 September 2026"). None of this requires JavaScript execution --
it is present in the initial HTML response, so a plain HTTP GET + BeautifulSoup
parse is sufficient. (Verified by fetching the live page and inspecting its
HTML on 2026-09-11.)

This module intentionally does NOT depend on brittle single-point selectors
like "grab whatever is inside id=22K-price". Instead it scans every price
card, reads its label text, and only accepts the value whose label mentions
"22K" (or "22 K" / "22 Karat" / "22 Carat") -- so if Goodreturns reorders the
cards, or changes ids, extraction still works as long as the label wording
and general card structure stay recognisable. If that structure changes
enough that no 22K card can be found, this module fails loudly rather than
guessing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from datetime import date as date_type, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SOURCE_URL = "https://www.goodreturns.in/gold-rates/hyderabad.html"
SOURCE_NAME = "Goodreturns"
CITY = "Hyderabad"
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Matches "22K", "22 K", "22 Karat", "22 Carat", "22k" etc.
_PURITY_22K_RE = re.compile(r"\b22\s*(?:k\b|karat|carat)", re.IGNORECASE)


class GoldRateScraperError(Exception):
    """Raised when the gold rate cannot be reliably retrieved or parsed."""


@dataclass
class GoldRate:
    city: str
    purity: str
    rate_per_gram: float
    date: str  # ISO format YYYY-MM-DD
    source: str

    def as_dict(self) -> dict:
        return asdict(self)


def fetch_page(url: str = SOURCE_URL, timeout: int = REQUEST_TIMEOUT_SECONDS) -> str:
    """Download the Goodreturns Hyderabad gold-rate page.

    Raises GoldRateScraperError on any network failure, timeout, or non-200
    response. Never fabricates or returns cached/placeholder HTML.
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise GoldRateScraperError(f"Timed out while fetching {url}") from exc
    except requests.exceptions.ConnectionError as exc:
        raise GoldRateScraperError(
            f"Could not connect to {url} (no internet or host unreachable)"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise GoldRateScraperError(f"Request to {url} failed: {exc}") from exc

    if response.status_code != 200:
        raise GoldRateScraperError(
            f"Unexpected HTTP status {response.status_code} from {url}"
        )

    if not response.text or len(response.text) < 500:
        raise GoldRateScraperError(
            f"Response from {url} was empty or suspiciously short "
            f"({len(response.text or '')} chars)"
        )

    return response.text


def parse_price_string(raw: str) -> float:
    """Convert a rupee price string to a float.

    Accepts formats such as "₹14,255", "14,255", "₹ 14,255", "14255.50".
    Raises ValueError if no valid numeric value can be extracted.
    """
    if raw is None:
        raise ValueError("Price string is None")

    cleaned = raw.strip()
    # Strip the rupee sign (both literal ₹ and any stray currency words),
    # non-breaking spaces, commas, and surrounding whitespace.
    cleaned = cleaned.replace("₹", "")  # ₹
    cleaned = cleaned.replace("\xa0", " ")  # non-breaking space
    cleaned = cleaned.replace(",", "")
    cleaned = cleaned.replace("Rs.", "").replace("Rs", "").replace("INR", "")
    cleaned = cleaned.strip()

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        raise ValueError(f"Could not parse a numeric price from {raw!r}")

    value = float(match.group())
    if value <= 0:
        raise ValueError(f"Parsed price is not positive: {value} (from {raw!r})")
    return value


def _parse_page_date(soup: BeautifulSoup) -> str:
    """Extract the rate's date from the page, e.g. '11 September 2026'.

    Falls back to today's local date if the date element is missing or
    unparseable -- the rate itself still came from the live page, so we do
    not fail the whole scrape just because a display label changed. The
    fallback is logged clearly so it is never silently mistaken for a
    Goodreturns-confirmed date.
    """
    date_span = soup.find(id="metal-price-date")
    if date_span:
        text = date_span.get_text(strip=True)
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                parsed = datetime.strptime(text, fmt).date()
                return parsed.isoformat()
            except ValueError:
                continue
        logger.warning("Could not parse page date text %r; using local date", text)
    else:
        logger.warning("Date element (#metal-price-date) not found; using local date")

    return date_type.today().isoformat()


def parse_hyderabad_22k(html: str) -> GoldRate:
    """Parse the Goodreturns Hyderabad page HTML and extract the 22K rate.

    Raises GoldRateScraperError if the 22K rate cannot be confidently
    identified (e.g. the site's markup changed). Never returns a fabricated
    or guessed value.
    """
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.find_all("div", class_="gr-price-card")
    if not cards:
        raise GoldRateScraperError(
            "No gold price cards found on the page -- Goodreturns' HTML "
            "structure may have changed."
        )

    candidates: list[float] = []
    for card in cards:
        label_el = card.find("p")
        if not label_el:
            continue
        label_text = label_el.get_text(" ", strip=True)
        if not _PURITY_22K_RE.search(label_text):
            continue

        value_el = card.find(id=re.compile(r"price", re.IGNORECASE))
        if value_el is None:
            # Fall back to any element carrying the price-value class.
            value_el = card.find(class_=re.compile(r"price-card-value"))
        if value_el is None:
            continue

        raw_value = value_el.get_text(strip=True)
        try:
            candidates.append(parse_price_string(raw_value))
        except ValueError:
            continue

    if not candidates:
        raise GoldRateScraperError(
            "Found gold price cards but none matched a 22K/22-carat label -- "
            "Goodreturns' HTML structure may have changed."
        )

    # If more than one 22K candidate is found (e.g. duplicated markup),
    # they should agree; if they don't, we cannot be confident which is
    # the current retail rate, so fail loudly rather than guess.
    unique_values = set(candidates)
    if len(unique_values) > 1:
        raise GoldRateScraperError(
            f"Multiple conflicting 22K rate values found on the page: "
            f"{sorted(unique_values)} -- refusing to guess."
        )

    rate_per_gram = candidates[0]
    rate_date = _parse_page_date(soup)

    return GoldRate(
        city=CITY,
        purity="22K",
        rate_per_gram=rate_per_gram,
        date=rate_date,
        source=SOURCE_NAME,
    )


def get_hyderabad_22k_rate(
    url: str = SOURCE_URL, timeout: int = REQUEST_TIMEOUT_SECONDS
) -> GoldRate:
    """Fetch and parse the current Hyderabad 22K gold rate.

    This is the main entry point other modules should use. Raises
    GoldRateScraperError on any failure -- callers must not fabricate a
    fallback value.
    """
    logger.info("Fetching %s ...", url)
    html = fetch_page(url, timeout=timeout)
    rate = parse_hyderabad_22k(html)
    logger.info(
        "Hyderabad 22K rate found: ₹%s/g (as of %s)",
        f"{rate.rate_per_gram:,.2f}",
        rate.date,
    )
    return rate


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = get_hyderabad_22k_rate()
    print(result.as_dict())
