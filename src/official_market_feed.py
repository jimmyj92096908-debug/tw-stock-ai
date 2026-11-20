"""Strict parsers for *official* TWSE / TPEx daily whole-market quotes.

Never infer a quote's trade date from current time. Never import warrants/ETFs
absent from stock_master. A daily snapshot adds missing bars only, preserving
existing single-stock historical records and calculated factors.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import requests

TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
SOURCE = {"twse": "TWSE_MI_INDEX_ALLBUT0999", "tpex": "TPEX_DAILY_CLOSE_OPENAPI"}
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0; +https://www.twse.com.tw)",
}
BLOCKED = {"", "-", "--", "---", "X", "x", "N/A", "NA", "無成交", "不適用"}


def numeric(value: object) -> Decimal | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if raw in BLOCKED:
        return None
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Invalid official numeric value") from exc
    if not result.is_finite():
        raise ValueError("Non-finite official numeric value")
    return result


def nonnegative_int(value: object) -> int | None:
    result = numeric(value)
    if result is None:
        return None
    if result < 0 or result != result.to_integral_value():
        raise ValueError("Invalid official share/transaction count")
    return int(result)


def official_date(value: object) -> date:
    raw = str(value).strip()
    if re.fullmatch(r"\d{7}", raw):
        return date(1911 + int(raw[:3]), int(raw[3:5]), int(raw[5:7]))
    if re.fullmatch(r"\d{8}", raw):
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    if re.fullmatch(r"\d{2,3}/\d{1,2}/\d{1,2}", raw):
        parts = [int(p) for p in raw.split("/")]
        return date(parts[0] + 1911, parts[1], parts[2])
    match = re.fullmatch(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日", raw)
    if match:
        y, m, d = (int(x) for x in match.groups())
        return date(y + 1911, m, d)
    raise ValueError("Official quote date is missing or invalid")


def signed_twse_change(marker: object, change: object) -> Decimal | None:
    amount = numeric(change)
    if amount is None:
        return None
    if amount == 0:
        return Decimal("0")
    indicator = re.sub(r"<[^>]*>", "", str(marker or "")).strip()
    if indicator in ("+", "＋"):
        return abs(amount)
    if indicator in ("-", "－"):
        return -abs(amount)
    # Neither dividend-adjustment status nor markup may be interpreted as a
    # daily +/- amount without a known indicator.
    return None


def _validate_bar(bar: dict) -> bool:
    close = bar["close"]
    if close is None or close <= 0:
        return False
    low, high = bar["low"], bar["high"]
    if low is not None and high is not None and (low <= 0 or low > high):
        return False
    if high is not None and close > high:
        return False
    if low is not None and close < low:
        return False
    if bar["open"] is not None and (
        bar["open"] <= 0 or
        (high is not None and bar["open"] > high) or
        (low is not None and bar["open"] < low)
    ):
        return False
    return True


def _parse_twse(payload: dict, expected_date: date) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        raise ValueError("TWSE did not report a valid trading session")
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise ValueError("TWSE tables missing")
    accepted = []
    for table in tables:
        fields = table.get("fields") or []
        required = [
            "證券代號", "成交股數", "成交筆數", "成交金額", "開盤價",
            "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差"
        ]
        if not all(k in fields for k in required):
            continue
        title = str(table.get("title") or "")
        match = re.search(r"\d{2,3}年\d{1,2}月\d{1,2}日", title)
        if not match or official_date(match.group(0)) != expected_date:
            raise ValueError("TWSE returned a different trade date")
        indexes = {key: fields.index(key) for key in required}
        data = table.get("data") or []
        if not isinstance(data, list):
            raise ValueError("TWSE data must be a list")
        for values in data:
            if not isinstance(values, list) or len(values) < len(fields):
                continue
            code = str(values[indexes["證券代號"]]).strip()
            if not re.fullmatch(r"\d{4}", code):
                continue
            try:
                bar = {
                    "market": "twse", "stock_id": code, "trade_date": expected_date,
                    "open": numeric(values[indexes["開盤價"]]),
                    "high": numeric(values[indexes["最高價"]]),
                    "low": numeric(values[indexes["最低價"]]),
                    "close": numeric(values[indexes["收盤價"]]),
                    "volume": nonnegative_int(values[indexes["成交股數"]]),
                    "turnover": numeric(values[indexes["成交金額"]]),
                    "price_change": signed_twse_change(
                        values[indexes["漲跌(+/-)"]],
                        values[indexes["漲跌價差"]]
                    ),
                    "transactions": nonnegative_int(values[indexes["成交筆數"]]),
                    "source": SOURCE["twse"]
                }
                if _validate_bar(bar):
                    accepted.append(bar)
            except ValueError:
                continue
        break
    if not accepted:
        raise ValueError("TWSE returned no valid four-digit closing bars")
    return accepted


def _parse_tpex(payload: list, expected_date: date) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError("TPEx quote payload must be a list")
    accepted = []
    seen_dates: set[date] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("SecuritiesCompanyCode", "")).strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        try:
            day = official_date(entry.get("Date"))
        except ValueError as exc:
            raise ValueError("TPEx returned an undated security") from exc
        seen_dates.add(day)
        if day != expected_date:
            continue
        try:
            bar = {
                "market": "tpex", "stock_id": code, "trade_date": day,
                "open": numeric(entry.get("Open")),
                "high": numeric(entry.get("High")),
                "low": numeric(entry.get("Low")),
                "close": numeric(entry.get("Close")),
                "volume": nonnegative_int(entry.get("TradingShares")),
                "turnover": numeric(entry.get("TransactionAmount")),
                "price_change": numeric(entry.get("Change")),
                "transactions": nonnegative_int(entry.get("TransactionNumber")),
                "source": SOURCE["tpex"]
            }
            if _validate_bar(bar):
                accepted.append(bar)
        except ValueError:
            continue
    if len(seen_dates) != 1 or expected_date not in seen_dates:
        raise ValueError("TPEx dates are inconsistent or stale")
    if not accepted:
        raise ValueError("TPEx returned no valid four-digit closing bars")
    return accepted


def fetch_latest_snapshot(market: str, *, today: date | None = None,
                          session: requests.Session | None = None) -> tuple[date, list[dict]]:
    """Fetch a bounded official session, without writing any data.

    TWSE is queried for a specified recent date, with a holiday/weekend
    fallback. TPEx OpenAPI returns only the latest published trading date.
    """
    taipei_now = datetime.now(ZoneInfo("Asia/Taipei"))
    today = today or taipei_now.date()
    http = session or requests
    if market == "twse":
        for lag in range(0, 7):
            candidate = today - timedelta(days=lag)
            if candidate.weekday() >= 5:
                continue
            # During the Taiwan trading session, today's official close is
            # not yet final. Exclude today on an actual current-day run.
            if today == taipei_now.date() and candidate == today and taipei_now.hour < 18:
                continue
            resp = http.get(TWSE_URL, params={
                "date": candidate.strftime("%Y%m%d"),
                "type": "ALLBUT0999", "response": "json"
            }, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("stat") != "OK":
                continue
            return candidate, _parse_twse(payload, candidate)
        raise ValueError("No recent valid TWSE daily settlement found")
    if market == "tpex":
        resp = http.get(TPEX_URL,headers=HEADERS,timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        days = {
            official_date(row["Date"])
            for row in payload if isinstance(row, dict) and
            re.fullmatch(r"\d{4}", str(row.get("SecuritiesCompanyCode","")).strip())
            and row.get("Date")
        }
        if len(days) != 1:
            raise ValueError("TPEx data contain mixed or missing trading days")
        day = next(iter(days))
        if day > today or day < today - timedelta(days=7):
            raise ValueError("TPEx latest trading day is outside safe freshness window")
        return day, _parse_tpex(payload, day)
    raise ValueError("Invalid market")


def select_candidates(bars: list[dict], allowed: set[tuple[str, str]],
                      *, minimum: int = 100) -> list[dict]:
    """Fail closed if payload looks incomplete, misdated or duplicated."""
    unique: dict[tuple[str,str,date], dict] = {}
    for bar in bars:
        identity = (bar["market"], bar["stock_id"])
        if identity not in allowed:
            continue
        key = (*identity, bar["trade_date"])
        if key in unique:
            raise ValueError("Duplicate daily quote for one listed candidate")
        unique[key] = bar
    selected = list(unique.values())
    if len(selected) < minimum:
        raise ValueError(f"Official feed covered only {len(selected)} eligible stocks")
    if len({row["trade_date"] for row in selected}) != 1:
        raise ValueError("Official feed mixes trade dates")
    return selected
