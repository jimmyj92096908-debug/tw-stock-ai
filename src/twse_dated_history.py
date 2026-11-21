"""Bounded historical TWSE whole-market daily bars from the official MI_INDEX.

Compared with per-stock monthly requests, this ingests many listed stocks per
source GET. Strictly validates dates, sessions, codes, OHLC, and source coverage.
Only inserts missing (market, stock_id, trade_date) keys and tracks processed
days; never overwrites historical prices or sends LINE messages.

Dry run is the default and never writes. Applying requires both --apply and
STOCK_TWSE_HISTORY_WRITE_ENABLED=yes. Bound network requests to 1..8 dates.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg

from official_market_feed import (
    HEADERS, TWSE_URL, _parse_twse, select_candidates,
)
from official_snapshot_ingest import write_missing
from current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

LOGGER = logging.getLogger(__name__)
MAX_DAYS_PER_RUN = 8
MAX_LOOKBACK_DAYS = 1830
MIN_COVERAGE_SHARE = 0.60
# Conservative index-inclusive stress cost, intentionally well above the
# measured raw table average. Free storage safety, not an actual quota promise.
MAX_DATABASE_BYTES = 800_000_000
MIN_MAINTENANCE_RESERVE_BYTES = 50_000_000
MAX_OFFICIAL_BARS_PER_DAY = 1500
STRESS_BYTES_PER_NEW_BAR = 600


def has_source_write_budget(database_bytes: int, *, days: int = 1) -> bool:
    """Allow an upper-bounded official import only with a maintenance reserve."""
    if (type(database_bytes) is not int or database_bytes < 0
            or type(days) is not int or not 1 <= days <= MAX_DAYS_PER_RUN):
        raise ValueError("Unverifiable TWSE storage estimate")
    budget = (MIN_MAINTENANCE_RESERVE_BYTES
              + days * MAX_OFFICIAL_BARS_PER_DAY * STRESS_BYTES_PER_NEW_BAR)
    return database_bytes + budget < MAX_DATABASE_BYTES


def verify_source_write_budget(conn, *, days: int = 1) -> None:
    """A read-only physical size check immediately before each dated insertion."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database())::bigint")
        size = cur.fetchone()[0]
    if not has_source_write_budget(size, days=days):
        raise RuntimeError("TWSE official source import blocked by Neon Free storage reserve")

# Only a recognized exchange "no matching data" response is an off-session.
NO_DATA_MARKERS = ("沒有符合條件的資料", "無符合條件", "無資料")

ACTIVE_ALLOWED_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT m.market,m.stock_id FROM public.stock_master m
INNER JOIN official_current_listed o
  ON o.market=m.market AND o.stock_id=m.stock_id
WHERE m.market='twse'
  AND NOT EXISTS (
    SELECT 1 FROM public.model_stock_exclusions x
    WHERE x.market=m.market AND x.stock_id=m.stock_id
  )
"""


def load_current_twse_allowed(conn) -> set[tuple[str,str]]:
    """Fail closed unless a fresh official current listing includes the issuer."""
    with conn.cursor() as cur:
        cur.execute(ACTIVE_ALLOWED_SQL)
        return {(str(m),str(stock_id)) for m,stock_id in cur.fetchall()}


CREATE_PROGRESS = """
CREATE TABLE IF NOT EXISTS public.twse_history_day_progress (
    trade_date DATE PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('imported', 'closed')),
    qualified INTEGER NOT NULL DEFAULT 0 CHECK (qualified >= 0),
    inserted INTEGER NOT NULL DEFAULT 0 CHECK (inserted >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
READ_PROGRESS = """
SELECT trade_date FROM public.twse_history_day_progress
WHERE status IN ('imported', 'closed')
"""
UPSERT_PROGRESS = """
INSERT INTO public.twse_history_day_progress
(trade_date,status,qualified,inserted,updated_at)
VALUES (%s,%s,%s,%s,NOW())
ON CONFLICT (trade_date) DO UPDATE SET
  status=EXCLUDED.status,
  qualified=EXCLUDED.qualified,
  inserted=EXCLUDED.inserted,
  updated_at=NOW()
"""

def schedule_dates(*, today: date, already: set[date], batch_days: int = 6,
                   lookback_days: int = 366) -> list[date]:
    """Choose a few newest unprocessed weekdays, never today or a future day."""
    if not 1 <= batch_days <= MAX_DAYS_PER_RUN:
        raise ValueError("batch_days must be 1..8")
    if not 7 <= lookback_days <= MAX_LOOKBACK_DAYS:
        raise ValueError(f"lookback_days must be 7..{MAX_LOOKBACK_DAYS}")
    result: list[date] = []
    try:
        five_year_start = today.replace(year=today.year-5)
    except ValueError:  # 29 February -> 28 February in non-leap target year.
        five_year_start = today.replace(year=today.year-5,day=28)
    for days_ago in range(1, lookback_days + 1):
        candidate = today - timedelta(days=days_ago)
        if candidate < five_year_start:
            break
        if candidate.weekday() >= 5 or candidate in already:
            continue
        result.append(candidate)
        if len(result) >= batch_days:
            break
    return result


def fetch_official_day(day: date, *, session=None) -> list[dict] | None:
    """Fetch a single dated official TWSE session. None means closed holiday."""
    import requests

    http = session or requests
    response = http.get(
        TWSE_URL,
        params={"date": day.strftime("%Y%m%d"),
                "type": "ALLBUT0999", "response": "json"},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected TWSE daily payload")
    if payload.get("stat") != "OK":
        status = str(payload.get("stat") or "")
        if any(marker in status for marker in NO_DATA_MARKERS):
            return None
        raise ValueError("Official TWSE did not provide a recognized closing session")
    rows = _parse_twse(payload, day)  # Validates every table's claimed trade date.
    if any(row["trade_date"] != day or row["market"] != "twse" for row in rows):
        raise ValueError("TWSE daily source mixed markets or trade dates")
    return rows


def _processed_days(conn) -> set[date]:
    # Dry runs must not create this optional progress table.
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.twse_history_day_progress')")
        exists = cursor.fetchone()[0] is not None
        if not exists:
            return set()
        cursor.execute(READ_PROGRESS)
        return {row[0] for row in cursor.fetchall()}


def _record_day(conn, day: date, status: str, qualified: int, inserted: int) -> None:
    if status not in ("imported", "closed") or min(qualified, inserted) < 0:
        raise ValueError("Invalid TWSE progress state")
    with conn.transaction():
        with conn.cursor() as cursor:
            cursor.execute(UPSERT_PROGRESS, (day, status, qualified, inserted))


def run(database_url: str, *, apply: bool = False,
        batch_days: int = 6, lookback_days: int = 366,
        today: date | None = None, session=None,
        pause_seconds: float = 2.0) -> list[dict]:
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    if apply and os.environ.get("STOCK_TWSE_HISTORY_WRITE_ENABLED") != "yes":
        raise ValueError("TWSE historical writes require explicit opt-in")
    if not 1 <= batch_days <= MAX_DAYS_PER_RUN:
        raise ValueError("batch_days must be 1..8")
    if not 7 <= lookback_days <= MAX_LOOKBACK_DAYS:
        raise ValueError(f"lookback_days must be 7..{MAX_LOOKBACK_DAYS}")
    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    report: list[dict] = []
    with psycopg.connect(database_url, connect_timeout=20) as conn:
        allowed = load_current_twse_allowed(conn)
        if len(allowed) < 700:
            raise ValueError("TWSE candidate list too small for whole-market import")
        processed = _processed_days(conn)
        dates = schedule_dates(
            today=today, already=processed,
            batch_days=batch_days, lookback_days=lookback_days,
        )
        if not dates:
            return report

        # Creating a table is a write: do it *only* with explicit apply enabled.
        if apply:
            with conn.transaction():
                with conn.cursor() as cursor:
                    cursor.execute(CREATE_PROGRESS)

        minimum = max(500, int(len(allowed) * MIN_COVERAGE_SHARE))
        for index, day in enumerate(dates):
            # Never trust only the workflow's earlier snapshot: concurrent
            # writers can consume storage while the long campaign is running.
            if apply:
                verify_source_write_budget(conn, days=1)
            bars = fetch_official_day(day, session=session)
            if bars is None:
                item = {"trade_date":day.isoformat(), "status":"closed",
                        "qualified":0, "inserted":0}
                if apply:
                    _record_day(conn, day, "closed", 0, 0)
            else:
                selected = select_candidates(bars, allowed, minimum=minimum)
                written = write_missing(conn, "twse", day, selected) if apply else 0
                if apply:
                    _record_day(conn, day, "imported", len(selected), written)
                item = {
                    "trade_date":day.isoformat(),
                    "status":"imported" if apply else "dry-run",
                    "qualified":len(selected), "inserted":written,
                }
            report.append(item)
            # Pause between official HTTP calls; no sleep after the last one.
            if pause_seconds and index + 1 < len(dates):
                time.sleep(pause_seconds)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="官方 TWSE 全上市歷史日 K 限額回補")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-days", type=int, default=6)
    parser.add_argument("--lookback-days", type=int, default=366)
    args = parser.parse_args()
    for item in run(
        os.environ.get("DATABASE_URL", ""), apply=args.apply,
        batch_days=args.batch_days, lookback_days=args.lookback_days,
    ):
        print(f"{item['trade_date']}: {item['status']}; "
              f"qualified={item['qualified']}; inserted={item['inserted']}")


if __name__ == "__main__":
    main()
