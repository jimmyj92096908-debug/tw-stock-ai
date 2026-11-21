"""Bounded official TPEx dated whole-market historical price backfill.

Default mode is read-only: no HTTP, no writes. Applying requires BOTH --apply
and STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED=yes, reviews at most four dates,
checks known same-day closes against independent existing DB records, limits
requests, and INSERTs missing keys only. Never updates existing OHLCV or LINE.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import date, timedelta, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
import requests

from official_snapshot_ingest import load_allowed, select_candidates, write_missing
from tpex_dated_bulk_canary import ENDPOINT, parse_day

MAX_DATES = 4
MAX_LOOKBACK = 366
MIN_EXISTING_COMPARISONS = 10
MIN_CLOSE_MATCH_FRACTION = Decimal("0.98")
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0)",
}


def choose_days(conn, *, today: date, universe: int, batch_days: int, lookback: int):
    if not 1 <= batch_days <= MAX_DATES or not 7 <= lookback <= MAX_LOOKBACK:
        raise ValueError("Unsafe history request bounds")
    if universe < 500:
        raise ValueError("TPEx stock universe too small")
    floor = today - timedelta(days=lookback)
    with conn.cursor() as cur:
        cur.execute("""SELECT trade_date,
                    COUNT(*) FILTER(WHERE close>0)::int
                    FROM public.daily_prices
                    WHERE market='tpex' AND trade_date >= %s AND trade_date < %s
                    GROUP BY trade_date""", (floor, today))
        counts = {d: n for d, n in cur.fetchall()}
    chosen = []
    for delta in range(1, lookback + 1):
        day = today - timedelta(days=delta)
        if day.weekday() >= 5:
            continue
        # The day must have SOME independent provenance for date anchoring.
        # Never bootstrap completely unseen dates using only a requested URL.
        existing = counts.get(day, 0)
        if existing < MIN_EXISTING_COMPARISONS or existing >= int(universe * .8):
            continue
        chosen.append({"trade_date": day, "old_valid_rows": existing})
        if len(chosen) == batch_days:
            break
    return chosen


def fetch_day(day: date, *, session=None):
    http = session or requests
    reply = http.get(ENDPOINT, params={
        "date": day.strftime("%Y/%m/%d"), "type": "EW", "response": "json",
    }, headers=HTTP_HEADERS, timeout=30)
    reply.raise_for_status()
    return parse_day(reply.json(), day, include_bars=True)


def verify_source_date(conn, day: date, bars: list[dict]) -> dict:
    """Check source date using SAME-DAY persisted close records, fail closed."""
    if not bars or any(b["trade_date"] != day or b["market"] != "tpex" for b in bars):
        raise ValueError("Mixed or empty TPEx dated bars")
    by_code = {b["stock_id"]: b["close"] for b in bars}
    if len(by_code) != len(bars):
        raise ValueError("Duplicate TPEx dated stock code")
    with conn.cursor() as cur:
        cur.execute("""SELECT stock_id, close FROM public.daily_prices
            WHERE market='tpex' AND trade_date=%s AND close>0""", (day,))
        known = cur.fetchall()
    matches = mismatches = 0
    for stock_id, close in known:
        if stock_id not in by_code:
            continue
        if Decimal(str(close)) == by_code[stock_id]:
            matches += 1
        else:
            mismatches += 1
    overlap = matches + mismatches
    if overlap < MIN_EXISTING_COMPARISONS:
        raise ValueError("Insufficient independently dated TPEx close comparisons")
    if Decimal(matches) / Decimal(overlap) < MIN_CLOSE_MATCH_FRACTION:
        raise ValueError("TPEx source date/close mismatch with stored daily prices")
    return {"compared": overlap, "matched": matches, "mismatched": mismatches}


def run(database_url: str, *, apply=False, batch_days=2, lookback=90,
        today=None, pause_seconds=3, session=None):
    if not database_url:
        raise ValueError("DATABASE_URL required")
    if not 1 <= batch_days <= MAX_DATES or not 7 <= lookback <= MAX_LOOKBACK:
        raise ValueError("Unsafe history request bounds")
    if apply and os.environ.get("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED") != "yes":
        raise ValueError("Explicit TPEx dated history write gate is required")
    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    results = []
    with psycopg.connect(database_url, connect_timeout=20) as conn:
        allowed = load_allowed(conn)
        tpex_allowed = {x for x in allowed if x[0] == "tpex"}
        chosen = choose_days(conn, today=today, universe=len(tpex_allowed),
                             batch_days=batch_days, lookback=lookback)
        for item in chosen:
            day = item["trade_date"]
            out = {"date": day.isoformat(), "previous_valid": item["old_valid_rows"],
                   "status": "dry-run", "inserted": 0}
            if apply:
                snapshot = fetch_day(day, session=session)
                # Minimum original stock coverage; exclude ETFs/unlisted codes.
                minimum = max(500, int(len(tpex_allowed) * .6))
                approved = select_candidates(snapshot["bars"], allowed, minimum=minimum)
                proof = verify_source_date(conn, day, approved)
                inserted = write_missing(conn, "tpex", day, approved)
                out.update({"status": "imported", "qualified": len(approved),
                            "inserted": inserted, **proof})
                if pause_seconds > 0:
                    time.sleep(pause_seconds)
            results.append(out)
    return results


def main():
    parser = argparse.ArgumentParser(description="Bounded dated TPEx history importer")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-days", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=90)
    args = parser.parse_args()
    result = run(os.getenv("DATABASE_URL", ""), apply=args.apply,
                 batch_days=args.batch_days, lookback=args.lookback_days)
    for row in result:
        print(row)
    if not result:
        print("No date-anchorable sparse TPEx session found")


if __name__ == "__main__":
    main()
