"""Read-only OHLC row classification.

This module deliberately does not repair, delete, or impute market data.
Rows classified as no_trade or invalid must not enter price-based indicators.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


@dataclass(frozen=True)
class OHLCQuality:
    status: str
    reason: str
    eligible_for_indicators: bool


def _number(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite():
        return None
    return number


def classify_ohlc_row(row: Mapping[str, Any]) -> OHLCQuality:
    """Classify one daily-price row without mutating it.

    Required keys: open, high, low, close, volume.
    Zero volume plus four NULL prices is a no-trade marker.
    Any other missing/non-numeric price is invalid.
    """
    prices = {key: _number(row.get(key)) for key in ("open", "high", "low", "close")}
    volume = _number(row.get("volume"))

    if volume is None:
        return OHLCQuality("invalid", "missing_or_non_numeric_volume", False)
    if volume < 0:
        return OHLCQuality("invalid", "negative_volume", False)

    missing = [key for key, value in prices.items() if value is None]
    if volume == 0 and len(missing) == 4:
        return OHLCQuality("no_trade", "zero_volume_all_ohlc_null", False)
    if volume == 0 and not missing:
        return OHLCQuality("review", "zero_volume_with_prices_requires_source_validation", False)
    if missing:
        return OHLCQuality("invalid", "missing_or_non_numeric_ohlc:" + ",".join(missing), False)

    opening, high, low, close = (prices[k] for k in ("open", "high", "low", "close"))
    if min(opening, high, low, close) <= 0:
        return OHLCQuality("invalid", "non_positive_price", False)
    if high < max(opening, close, low) or low > min(opening, close, high):
        return OHLCQuality("invalid", "inconsistent_ohlc_range", False)

    return OHLCQuality("valid", "complete_ohlc", True)
