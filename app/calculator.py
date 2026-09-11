"""
Pure calculation helpers: multi-gram pricing and rate-change math.

Nothing in this module touches the network or the database, so it is easy
to unit test in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def price_for_grams(rate_per_gram: float, grams: float) -> float:
    """Round-half-up to the nearest rupee, since gold rates are quoted in
    whole rupees per gram on Goodreturns and fractional paise are not
    meaningful for a retail quote."""
    if rate_per_gram < 0 or grams < 0:
        raise ValueError("rate_per_gram and grams must be non-negative")
    return round(rate_per_gram * grams, 2)


@dataclass
class RateChange:
    absolute: float
    percentage: float

    def formatted(self) -> str:
        sign = "+" if self.absolute >= 0 else "-"
        return (
            f"{sign}₹{abs(self.absolute):,.0f} / gram "
            f"({sign}{abs(self.percentage):.2f}%)"
        )


def calculate_change(
    today_rate: float, previous_rate: Optional[float]
) -> Optional[RateChange]:
    """Returns None when there is no previous rate to compare against --
    callers should render this as "Change: Not available" rather than
    inventing a historical value."""
    if previous_rate is None:
        return None
    if previous_rate == 0:
        return None

    absolute = round(today_rate - previous_rate, 2)
    percentage = round((absolute / previous_rate) * 100, 2)
    return RateChange(absolute=absolute, percentage=percentage)


def format_inr(amount: float) -> str:
    """Format a rupee amount with Indian-style comma grouping, e.g.
    1234567.0 -> '12,34,567'."""
    amount = round(amount)
    negative = amount < 0
    amount = abs(amount)
    s = str(int(amount))

    if len(s) <= 3:
        grouped = s
    else:
        last_three = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts) + "," + last_three

    return ("-" if negative else "") + grouped
