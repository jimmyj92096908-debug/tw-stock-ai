"""Strictly bounded 240-session TWSE technical/SMC factor research from monthly official prices.

Only one frozen currently officially-listed ticker (2330) over exactly 13
predeclared historical months, with source quotes held solely in runner RAM.
READ ONLY Neon connection checks current issuer and user exclusion registry.
No price, derived factor, weight, archive, LINE or trading/database writes.
A successful canary does NOT establish full-market historical completeness,
survivorship-free as-of issuer membership, dividend-adjusted returns, or alpha.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE
from src.market_data import API_URL, parse_roc_date
from src.official_market_feed import HEADERS, _validate_bar, nonnegative_int, numeric
from src.raw_factor_feature_bridge import (
    FEATURE_NAMES, MIN_WARMUP_SESSIONS, build_research_features,
)

STOCK_ID = "2330"
MONTHS = tuple(
    date(y, m, 1) for y, low, high in ((2021, 12, 12), (2022, 1, 12))
    for m in range(low, high + 1)
)
assert len(MONTHS) == 13
SOURCE_TAG = "TWSE_STOCK_DAY"
MIN_VALID_PRICE_SESSIONS = 240
MAX_ROWS_PER_MONTH = 25
MAX_SOURCE_REQUESTS = 13
MAX_OUTPUT_BYTES = 8192

ROSTER_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT COUNT(*)::int AS eligible
FROM official_current_listed l
WHERE l.market='twse' AND l.stock_id=%s
  AND NOT EXISTS (
      SELECT 1 FROM public.model_stock_exclusions e
      WHERE e.market=l.market AND e.stock_id=l.stock_id
  )
"""

REQUIRED_FIELDS = (
    "日期", "成交股數", "成交金額", "開盤價",
    "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數",
)


def parse_month(payload: dict, *, month: date, stock_id=STOCK_ID) -> list[dict]:
    """Reject wrong issuer/month, inconsistent columns and source OHLCV.

    Numeric values stay Decimal rather than passing through float. No-trade
    placeholders are explicitly skipped, never manufactured as zero bars.
    """
    if (type(month) is not date or month.day != 1 or
        month not in MONTHS or stock_id != STOCK_ID or
        not isinstance(payload, dict) or payload.get("stat") != "OK"):
        raise ValueError("Official historical STOCK_DAY month or issuer invalid")
    title = str(payload.get("title") or "")
    expected_roc = f"{month.year - 1911}年{month.month}月"
    if (expected_roc not in title or
        re.search(r"(?<![0-9])2330(?![0-9])", title) is None):
        raise ValueError("Official monthly source issuer/title/date mismatched")
    source_month = str(payload.get("date") or "")
    if not source_month.startswith(month.strftime("%Y%m")) or not re.fullmatch(
        r"[0-9]{8}", source_month
    ):
        raise ValueError("Official month source response date mismatched")
    fields = payload.get("fields")
    data = payload.get("data")
    if (not isinstance(fields, list) or len(fields) != len(set(fields))
        or not all(name in fields for name in REQUIRED_FIELDS)
        or not isinstance(data, list)
        or not 1 <= len(data) <= MAX_ROWS_PER_MONTH):
        raise ValueError("Missing/ambiguous monthly source fields or row count")
    i = {field: fields.index(field) for field in REQUIRED_FIELDS}
    results = []
    dates = set()
    for values in data:
        if not isinstance(values, list) or len(values) != len(fields):
            raise ValueError("Malformed monthly TWSE source row")
        trading_day = date.fromisoformat(parse_roc_date(str(values[i["日期"]])))
        if trading_day.year != month.year or trading_day.month != month.month:
            raise ValueError("Wrong official month source trade date")
        if trading_day.weekday() >= 5 or trading_day in dates:
            raise ValueError("Duplicate or impossible monthly trading date")
        dates.add(trading_day)
        op, hi, lo, cl = (
            numeric(values[i[f]]) for f in
            ("開盤價", "最高價", "最低價", "收盤價")
        )
        volume = nonnegative_int(values[i["成交股數"]])
        turnover = numeric(values[i["成交金額"]])
        transactions = nonnegative_int(values[i["成交筆數"]])
        change = numeric(values[i["漲跌價差"]])
        if any(v is None for v in (op, hi, lo, cl, volume)):
            # Suspended/zero-trade quotes are NOT real factor bars.
            continue
        if (turnover is not None and turnover < 0 or
            transactions is not None and transactions < 0 or
            volume <= 0 or hi < lo):
            raise ValueError("Unusable official monthly price economics")
        row = {
            "market": "twse", "stock_id": stock_id,
            "trade_date": trading_day, "open": op, "high": hi, "low": lo,
            "close": cl, "volume": volume, "turnover": turnover,
            "price_change": change, "transactions": transactions,
            "source": SOURCE_TAG,
        }
        if not _validate_bar(row):
            raise ValueError("Impossible official source OHLC high/low/close")
        results.append(row)
    if not results:
        raise ValueError("Official monthly source has no valid real price bars")
    results.sort(key=lambda row: row["trade_date"])
    return results


def fetch_month(month: date, *, stock_id=STOCK_ID, session=None):
    import requests
    if month not in MONTHS or stock_id != STOCK_ID:
        raise ValueError("Only precommitted 2021-12 through 2022-12 source months")
    http = session or requests
    response = http.get(
        API_URL,
        params={"response": "json", "date": month.strftime("%Y%m%d"),
                "stockNo": stock_id},
        headers=HEADERS, timeout=30,
    )
    response.raise_for_status()
    return parse_month(response.json(), month=month, stock_id=stock_id)


def assess_months(monthly_bars: list[list[dict]], *, baseline_days=MIN_VALID_PRICE_SESSIONS):
    if (not isinstance(monthly_bars, list) or len(monthly_bars) != MAX_SOURCE_REQUESTS
        or type(baseline_days) is not int or baseline_days != MIN_VALID_PRICE_SESSIONS):
        raise ValueError("Require all 13 precommitted official source months")
    series = []
    monthly_counts = []
    for month, rows in zip(MONTHS, monthly_bars):
        if (not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS_PER_MONTH):
            raise ValueError("Missing real monthly market observations")
        last = None
        for row in rows:
            if (row.get("market") != "twse" or row.get("stock_id") != STOCK_ID
                or row.get("source") != SOURCE_TAG
                or type(row.get("trade_date")) is not date
                or (row["trade_date"].year, row["trade_date"].month)
                   != (month.year, month.month)
                or last is not None and row["trade_date"] <= last):
                raise ValueError("Noncausal or mixed month/issuer source rows")
            last = row["trade_date"]
        monthly_counts.append(len(rows))
        series.extend(rows)
    if len(series) < MIN_VALID_PRICE_SESSIONS:
        raise ValueError("Official monthly price archive has <240 valid stock sessions")
    last = series[-1]["trade_date"]
    prior = series[-2]["trade_date"]
    # Reuse exact audited no-storage technical/SMC feature algorithms.
    latest = build_research_features(
        series, stock_id=STOCK_ID, market="twse",
        cutoff=last, signal_dates=[last],
    )
    previous_with_future = build_research_features(
        series, stock_id=STOCK_ID, market="twse",
        cutoff=last, signal_dates=[prior],
    )
    previous_only_past = build_research_features(
        series[:-1], stock_id=STOCK_ID, market="twse",
        cutoff=prior, signal_dates=[prior],
    )
    if (latest["included_signals"] != 1 or
        previous_with_future["included_signals"] != 1 or
        previous_only_past["included_signals"] != 1 or
        previous_with_future["signals"][0]["feature_vector"]
        != previous_only_past["signals"][0]["feature_vector"]):
        raise RuntimeError("Actual 240-session technical/SMC lookahead leakage")
    # No raw stock record or model weight leaves runner memory.
    fingerprint = sha256(json.dumps(
        [latest["raw_source_fingerprint_sha256"],
         previous_with_future["raw_source_fingerprint_sha256"],
         monthly_counts, last.isoformat()],
        separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    return {
        "scope": "TWSE_2330_240_SESSION_MEMORY_ONLY_MONTHLY_FACTOR_RESEARCH",
        "stock_count": 1,
        "official_months_fetched": len(MONTHS),
        "market_source": SOURCE_TAG,
        "actual_valid_stock_sessions": len(series),
        "official_monthly_valid_rows": monthly_counts,
        "first_real_stock_date": series[0]["trade_date"].isoformat(),
        "last_real_stock_date": last.isoformat(),
        "factor_source_fingerprint_sha256": fingerprint,
        "feature_version": latest["feature_version"],
        "feature_count": len(FEATURE_NAMES),
        "causal_previous_day_prefix_parity_passed": True,
        "actual_240_session_warmup_met": True,
        "all_market_240_day_coverage_proven": False,
        "five_year_official_market_data_complete": False,
        "historical_issuer_survivorship_free": False,
        "historical_asof_source_capture_proven": False,
        "dividend_adjusted_total_return_proven": False,
        "independent_future_model_validation_passed": False,
        "raw_rows_persisted": 0,
        "neon_derived_rows_written": 0,
        "github_raw_market_price_artifacts": 0,
        "line_messages_sent": 0,
        "model_live_trading_approved": False,
        "paid_upgrade_requested": False,
    }


def execute(database_url, *, loader=fetch_month, pause_seconds=3.0,
            output=None):
    if (not database_url or type(pause_seconds) not in (int, float)
        or not 2 <= pause_seconds <= 4):
        raise ValueError("Read-only Neon eligibility and paced official requests required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(database_url, connect_timeout=15,
                         row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '25000ms'")
        receipt = conn.execute(ROSTER_SQL, (STOCK_ID,)).fetchone()
        if not receipt or receipt["eligible"] != 1:
            raise ValueError("2330 is not a fresh official current-listed allowed issuer")
    readings = []
    for i, month in enumerate(MONTHS):
        rows = loader(month)
        readings.append(rows)
        if i + 1 < len(MONTHS):
            time.sleep(pause_seconds)
    report = assess_months(readings)
    # Only aggregate proof saved, never original per-stock source prices.
    blob = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if len(blob.encode()) > MAX_OUTPUT_BYTES:
        raise RuntimeError("Unbounded model evidence output")
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(blob, encoding="utf-8")
    else:
        print(blob)
    return report


def main():
    p = argparse.ArgumentParser(
        description="Read 13 dated official TWSE months in RAM to prove 240-session factor")
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    execute(os.getenv("DATABASE_URL", ""), output=a.output)


if __name__ == "__main__":
    main()
