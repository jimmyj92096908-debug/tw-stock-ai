"""Prove TWO historical 2021 TWSE whole-market source days, with zero storage.

Official MI_INDEX dates and current-listed survivor universe are validated via
existing guarded source code. Both old 2330 closing prices must independently
match stored TWSE_STOCK_DAY anchors. No market row is saved, no Neon write, LINE,
paid resource, archive publication or live trading permission is issued.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import json
import os
import time
from zoneinfo import ZoneInfo

from scripts.twse_official_direct_archive import (
    preflight, _canonical_source_rows,
)
from src.twse_dated_history import fetch_official_day

START = date(2021, 12, 1)
END = date(2021, 12, 31)
FROZEN_DAYS = (date(2021, 12, 1), date(2021, 12, 2))
MIN_SOURCE_BARS = 500
MAX_SOURCE_BARS = 1500

ANCHORS_SQL = """
SELECT trade_date, close
FROM public.daily_prices
WHERE market='twse'
  AND stock_id='2330'
  AND source='TWSE_STOCK_DAY'
  AND trade_date IN (%s, %s)
  AND close > 0
ORDER BY trade_date
"""


def read_anchors(database_url: str) -> dict[date, Decimal]:
    """An independent bounded Neon READ ONLY lookup of dated 2330 closes."""
    if not database_url:
        raise ValueError("Protected existing Neon access required")
    import psycopg
    with psycopg.connect(database_url, connect_timeout=20) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '30000ms'")
        with conn.cursor() as cur:
            cur.execute(ANCHORS_SQL, FROZEN_DAYS)
            rows = cur.fetchall()
        conn.rollback()
    if (len(rows) != len(FROZEN_DAYS)
            or any(type(d) is not date or type(value) is not Decimal
                   or not value.is_finite() or value <= 0
                   for d, value in rows)
            or tuple(day for day, _ in rows) != FROZEN_DAYS):
        raise ValueError("Two independent saved 2021 official 2330 anchors required")
    return dict(rows)


def evaluate_source(dates, allowed, anchor_closes, *,
                    fetcher=fetch_official_day,
                    sleeper=time.sleep, pause_seconds=4.0):
    """Pure, bounded source verification: no persistence, no DB connection."""
    if (tuple(dates) != FROZEN_DAYS
            or not isinstance(allowed, set)
            or len(allowed) < 700
            or ("twse", "1589") in allowed
            or not isinstance(anchor_closes, dict)
            or set(anchor_closes) != set(FROZEN_DAYS)
            or any(type(v) is not Decimal or not v.is_finite() or v <= 0
                   for v in anchor_closes.values())
            or type(pause_seconds) not in (float, int)
            or not 4 <= pause_seconds <= 6
            or not callable(sleeper) or not callable(fetcher)):
        raise ValueError("Frozen 2021 source budget, roster or prior closes unverified")
    next_day = 0
    calls = 0

    def paced(day):
        nonlocal calls, next_day
        if calls >= len(FROZEN_DAYS) or day != FROZEN_DAYS[calls]:
            raise ValueError("Official request count or order violation")
        if calls:
            sleeper(pause_seconds)
        calls += 1
        next_day = day
        return fetcher(day)

    counts = Counter()
    anchors_compared = set()
    for bar in _canonical_source_rows(paced, FROZEN_DAYS, allowed):
        day = bar["trade_date"]
        if day not in FROZEN_DAYS or bar["stock_id"] == "1589":
            raise ValueError("Unexpected official source date or excluded issuer")
        counts[day] += 1
        if counts[day] > MAX_SOURCE_BARS:
            raise ValueError("Unbounded official source payload")
        if bar["stock_id"] == "2330":
            if bar["close"] != anchor_closes[day]:
                raise ValueError("2021 official whole-market 2330 close conflicts with existing anchor")
            anchors_compared.add(day)
    if (calls != len(FROZEN_DAYS) or set(counts) != set(FROZEN_DAYS)
            or not all(MIN_SOURCE_BARS <= n <= MAX_SOURCE_BARS
                       for n in counts.values())
            or anchors_compared != set(FROZEN_DAYS)):
        raise ValueError("Missing full source day or independent 2330 close parity")
    return {
        "schema_version": 1,
        "scope": "TWSE_2021_TWO_REAL_OFFICIAL_MARKET_DAYS_RAM_ONLY",
        "official_source_dates": [d.isoformat() for d in FROZEN_DAYS],
        "eligible_current_listed_source_bar_counts":
            {d.isoformat(): counts[d] for d in FROZEN_DAYS},
        "validated_2330_original_close_anchor_days": len(anchors_compared),
        "source_request_count": calls,
        "minimum_inter_request_pause_seconds": pause_seconds,
        "original_2021_source_prices_or_archives_saved": 0,
        "neon_price_or_technical_rows_written": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
        "currently_delisted_issuer_included": False,
        "owner_excluded_1589_included": False,
        "point_in_time_historical_issuer_membership_proven": False,
        "corporate_action_total_returns_proven": False,
        "all_2021_market_days_proven": False,
        "five_year_history_completed": False,
        "live_trading_approved": False,
    }


def run(database_url: str, *, today: date | None = None,
        fetcher=fetch_official_day, sleeper=time.sleep):
    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if type(today) is not date or today <= END:
        raise ValueError("2021 historical source validation only")
    sessions, allowed = preflight(database_url, start=START, end=END, today=today)
    if tuple(sessions[:2]) != FROZEN_DAYS:
        raise ValueError("Saved 2021 sparse reference calendar changed")
    anchors = read_anchors(database_url)
    return evaluate_source(FROZEN_DAYS, allowed, anchors,
                           fetcher=fetcher, sleeper=sleeper)


def main():
    report = run(os.environ.get("DATABASE_URL", ""))
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
