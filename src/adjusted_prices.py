"""Apply verified corporate-action factors to historical OHLCV without mutating raw bars."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Iterable


def _economic_number(value: Any, *, positive: bool = False) -> Decimal | None:
    """Canonical economic terms: 0.9800, Decimal('0.98') and 0.98 match.

    Missing optional amounts (absent or NULL) match; explicit zero does not
    silently become missing. Reject non-finite/invalid values before dedup.
    """
    if value is None or value == "":
        if positive:
            raise ValueError("公司行動調整係數必須是有限正數")
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("公司行動數值無效") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError("公司行動調整係數必須是有限正數" if positive else "公司行動數值無效")
    return number.normalize()


def _deduplicate_events(actions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse byte-for-byte equivalent economic events before compounding factors.

    Different source_event_id values can represent duplicate source rows. Keep
    distinct events (including different factors/types) so legitimate same-day
    corporate actions still compound.
    """
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for event in actions:
        key = (
            str(event["ex_date"]),
            str(event.get("action_type", "")),
            _economic_number(event["price_factor"], positive=True),
            _economic_number(event["share_factor"], positive=True),
            _economic_number(event.get("cash_amount")),
            _economic_number(event.get("stock_amount")),
        )
        unique.setdefault(key, event)
    return list(unique.values())


def adjust_bars(rows: Iterable[dict[str, Any]], actions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    bars = sorted(list(rows), key=lambda r: str(r["trade_date"]))
    events = _deduplicate_events(actions)
    previous = None
    for event in events:
        pf = float(event["price_factor"])
        sf = float(event["share_factor"])
        if not isfinite(pf) or not isfinite(sf) or pf <= 0 or sf <= 0:
            raise ValueError("公司行動調整係數必須是有限正數")
    result = []
    for bar in bars:
        d = str(bar["trade_date"])
        price_factor = 1.0
        share_factor = 1.0
        for event in events:
            if str(event["ex_date"]) > d:
                price_factor *= float(event["price_factor"])
                share_factor *= float(event["share_factor"])
        item = dict(bar)
        for field in ("open", "high", "low", "close"):
            value = bar.get(field)
            item[field] = None if value is None else float(value) * price_factor
        volume = bar.get("volume")
        item["volume"] = None if volume is None else float(volume) * share_factor
        item["price_adjustment_factor"] = price_factor
        item["share_adjustment_factor"] = share_factor
        item["adjustment_status"] = "ADJUSTED" if price_factor != 1.0 or share_factor != 1.0 else "UNADJUSTED"
        if item["close"] is not None and previous is not None:
            item["price_change"] = item["close"] - previous
        else:
            item["price_change"] = None
        if item["close"] is not None:
            previous = item["close"]
        result.append(item)
    return result
