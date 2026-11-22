"""Observe early TWSE official five-year history without using Neon storage.

Uses existing date-validated official MI_INDEX parser and a fresh official
current-listed / model-excluded roster. Exactly two predeclared historic
trading dates are probed (not a blind bulk downloader). Source OHLCV stays
in ephemeral GitHub runner memory. Only aggregates and source fingerprints
are retained: no price-row files, no Neon price/index/derived writes,
no LINE notifications, no archive/migration/trading approval.

Passing two historic dates proves *source-on-demand feasibility only*.
It is not five-year coverage or pristine point-in-time universe evidence.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from src.official_market_feed import SOURCE, select_candidates
from src.twse_dated_history import (
    MAX_LOOKBACK_DAYS,
    MIN_COVERAGE_SHARE,
    fetch_official_day,
    load_current_twse_allowed,
    _processed_days,
)

DAYS = (date(2022, 1, 4), date(2022, 1, 5))
MAX_DAYS = 2
MAX_BYTES_IN_RECEIPT = 8192
FINGERPRINT_COLUMNS = (
    "market", "stock_id", "trade_date", "open", "high", "low", "close",
    "volume", "turnover", "transactions", "price_change", "source",
)


def validate_dates(days, *, today=None):
    today = today or datetime.now(timezone.utc).date()
    if (not isinstance(days, (list, tuple)) or
        not 1 <= len(days) <= MAX_DAYS or
        any(type(d) is not date for d in days) or
        days != tuple(sorted(set(days))) and days != list(sorted(set(days))) or
        any(d.weekday() >= 5 or d >= today or d < date(2021, 11, 22)
            or d >= date(2023, 2, 24) for d in days)):
        raise ValueError("Require 1-2 unique ordered unprocessed 2021-2023 weekdays")
    if (today - days[0]).days > MAX_LOOKBACK_DAYS:
        raise ValueError("Historic source date is past five-year query window")
    return tuple(days)


def source_fingerprint(rows, *, trade_date, allowed, minimum):
    if type(minimum) is not int or minimum < 500 or not allowed:
        raise ValueError("Fresh full-market allowed issuer roster required")
    selected = select_candidates(rows, allowed, minimum=minimum)
    selected.sort(key=lambda r: r["stock_id"])
    hash_ = sha256()
    prev = ""
    for row in selected:
        if (row["trade_date"] != trade_date or row["market"] != "twse"
            or row["source"] != SOURCE["twse"] or row["stock_id"] <= prev
            or row["stock_id"] == "1589" or row["close"] is None
            or row["close"] <= 0 or row["volume"] is None
            or row["volume"] < 0):
            raise ValueError("Noncanonical official source, price or owner exclusion")
        prev = row["stock_id"]
        record = []
        for field in FINGERPRINT_COLUMNS:
            value = row.get(field)
            if isinstance(value, Decimal):
                if not value.is_finite():
                    raise ValueError("Nonfinite TWSE source price")
                value = str(value)
            elif isinstance(value, date):
                value = value.isoformat()
            elif value is not None and type(value) not in (str, int):
                raise ValueError("Unexpected official quote type")
            record.append(value)
        hash_.update((json.dumps(record,ensure_ascii=False,
                                 allow_nan=False,separators=(",",":"))+"\n").encode())
    return {
        "date": trade_date.isoformat(),
        "validated_current_listed_source_bars": len(selected),
        "source_fingerprint_sha256": hash_.hexdigest(),
        "none_of_the_source_bars_persisted": True,
    }


def execute(database_url, *, days=DAYS, fetcher=fetch_official_day,
            sleep_seconds=2.0, output_path=None):
    ordered = validate_dates(days)
    if not database_url:
        raise ValueError("Protected read-only Neon connection URL required")
    if not 0 <= sleep_seconds <= 3:
        raise ValueError("Bounded nonnegative exchange request pause required")
    import psycopg
    with psycopg.connect(database_url, connect_timeout=15,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '40000ms'")
        allowed = load_current_twse_allowed(conn)
        processed = _processed_days(conn)
        if len(allowed) < 700:
            raise ValueError("Official current TWSE roster unexpectedly incomplete")
        if any(("twse","1589") in allowed for _ in (0,)):
            raise ValueError("Owner excluded 1589 found in current research roster")
        if any(d in processed for d in ordered):
            raise ValueError("One or more proposed source dates are no longer missing")
    minimum = max(500, int(len(allowed)*MIN_COVERAGE_SHARE))
    source_receipts = []
    for index,day in enumerate(ordered):
        rows = fetcher(day)
        if rows is None:
            raise ValueError("Selected historical session is not a valid trading day")
        source_receipts.append(source_fingerprint(
            rows, trade_date=day, allowed=allowed, minimum=minimum,
        ))
        del rows
        if index + 1 < len(ordered) and sleep_seconds:
            time.sleep(sleep_seconds)

    receipt = {
        "scope": "TWSE_TWO_EARLY_SOURCE_DAYS_MEMORY_ONLY_RESEARCH_PROOF",
        "historical_dates_requested": len(ordered),
        "dates": source_receipts,
        "aggregate_current_eligible_source_bars": sum(
            x["validated_current_listed_source_bars"] for x in source_receipts
        ),
        "source_parser": "TWSE_MI_INDEX_ALLBUT0999_OFFICIAL_DATE_VERIFIED",
        "official_current_listed_and_user_excluded_only": True,
        "twse_historical_source_on_demand_observed": True,
        "historical_full_market_survivorship_free": False,
        "complete_five_year_price_history_proven": False,
        "complete_historical_factor_model_proven": False,
        "current_market_date_not_fetched": True,
        "raw_ohlcv_files_or_archives_written": 0,
        "neon_storage_bytes_written": 0,
        "neon_prices_modified": False,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
        "model_live_trading_approved": False,
    }
    blob = json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if len(blob.encode()) > MAX_BYTES_IN_RECEIPT:
        raise RuntimeError("Unexpectedly oversized source-only evidence")
    if output_path is None:
        print(blob)
    else:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(blob,encoding="utf-8")
    return receipt


def main():
    parser=argparse.ArgumentParser(
        description="Probe two 2022 official TWSE source days without Neon writes")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    execute(os.environ.get("DATABASE_URL",""),output_path=args.output)


if __name__ == "__main__":
    main()
