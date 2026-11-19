"""Parse official one-day all-market quote payloads without database side effects.

TWSE MI_INDEX and TPEx otc are date-scoped bulk endpoints. TPEx's public
"otc" table explicitly excludes fixed-price transactions; this scope is
preserved in the source label and must not be interpreted as all trading modes.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any


MISSING = {"", "--", "---", "-", "—", "－", "N/A", "NA", "X"}

FIELD_ALIASES = {
    "stock_id": ("證券代號", "代號", "股票代號"),
    "name": ("證券名稱", "名稱", "股票名稱"),
    "volume": ("成交股數",),
    "transactions": ("成交筆數",),
    "turnover": ("成交金額", "成交金額(元)"),
    "open": ("開盤價", "開盤"),
    "high": ("最高價", "最高"),
    "low": ("最低價", "最低"),
    "close": ("收盤價", "收盤"),
    "change": ("漲跌價差", "漲跌"),
}


def parse_roc_date(value: Any) -> str | None:
    text = str(value or "").strip().rstrip("*＊")
    parts = text.split("/")
    if len(parts) != 3:
        return None
    try:
        year, month, day = map(int, parts)
        return date(year + 1911, month, day).isoformat()
    except (TypeError, ValueError):
        return None


def _date_from_payload(payload: dict) -> str | None:
    dates: set[str] = set()
    raw = str(payload.get("date") or "").strip()
    if len(raw) == 8 and raw.isdigit():
        try:
            dates.add(date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat())
        except ValueError:
            raise ValueError(f"Invalid response date: {raw!r}")
    for table in payload.get("tables") or []:
        parsed = parse_roc_date(table.get("date"))
        if parsed:
            dates.add(parsed)
    if len(dates) != 1:
        raise ValueError(f"Response date missing or inconsistent: {sorted(dates)!r}")
    return next(iter(dates))


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if raw.upper() in MISSING:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _ohlc_status(row: dict[str, Any]) -> str:
    values = [row.get(key) for key in ("open", "high", "low", "close")]
    if any(value is None for value in values):
        return "missing"
    opening, high, low, close = values
    if min(values) <= 0 or high < max(opening, low, close) or low > min(opening, high, close):
        return "invalid"
    return "complete"


def parse_all_market_daily(payload: dict, market: str, expected_date: str) -> list[dict[str, Any]]:
    """Normalize a single date's whole-market payload; never repairs missing fields."""
    if market not in {"twse", "tpex"}:
        raise ValueError("market must be 'twse' or 'tpex'")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    status = str(payload.get("stat") or "").strip().lower()
    if status and status != "ok":
        raise ValueError(f"Official endpoint status is not OK: {payload.get('stat')!r}")

    response_date = _date_from_payload(payload)
    if response_date != expected_date:
        raise ValueError(
            f"Official endpoint returned {response_date}, requested {expected_date}"
        )

    source = (
        "TWSE_MI_INDEX_ALLBUT0999"
        if market == "twse"
        else "TPEX_OTC_EXCLUDING_FIXED_PRICE"
    )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for table in payload.get("tables") or []:
        fields = [str(value).strip() for value in (table.get("fields") or [])]
        indexes: dict[str, int] = {}
        for key, aliases in FIELD_ALIASES.items():
            idx = next((i for i, field in enumerate(fields) if field in aliases), None)
            if idx is not None:
                indexes[key] = idx
        required = {"stock_id", "name", "volume", "open", "high", "low", "close"}
        if not required.issubset(indexes):
            continue
        for raw in table.get("data") or []:
            if len(raw) < len(fields):
                continue
            stock_id = str(raw[indexes["stock_id"]]).strip()
            if not stock_id:
                continue
            if stock_id in seen:
                raise ValueError(f"Duplicate security code in response: {stock_id}")
            seen.add(stock_id)
            item: dict[str, Any] = {
                "market": market,
                "stock_id": stock_id,
                "name": str(raw[indexes["name"]]).strip(),
                "trade_date": response_date,
                "source": source,
            }
            for key in ("volume", "transactions", "turnover", "open", "high", "low", "close", "change"):
                idx = indexes.get(key)
                item[key] = _number(raw[idx]) if idx is not None else None
            item["ohlc_status"] = _ohlc_status(item)
            normalized.append(item)

    if not normalized:
        raise ValueError("No compatible all-market quote table or rows found")
    return normalized
