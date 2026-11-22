"""48-date genuine 2022 TWSE whole-market shared stream; never store bars.

This next bounded experimental stage follows the successful twelve-day
source canary. A 2330 dated calendar from an immutable READ ONLY Neon snapshot
selects exactly 48 official 2022 market sessions across Lunar New Year.
Each receives one explicitly dated TWSE MI_INDEX ALLBUT0999 GET spaced by
at least 4 seconds. Responses and complete eligible-stock intersections
remain in runner memory, then only aggregate proof is reported.

No 240-day real MA is claimed here. The protected main CI does not expose
the date/request count as a workflow or CLI parameter, auto-retry failed
calls, write Neon, store raw OHLCV or issue LINE/trading events.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import time

from src.twse_dated_history import (
    fetch_official_day, load_current_twse_allowed, _processed_days,
)
from scripts.twse_2022_shared_source_stream import (
    REFERENCE_CALENDAR_SQL, compute_stream, validate_days,
)

PILOT_DAYS = 48
FIRST_DAY = date(2022, 1, 4)
LAST_DAY = date(2022, 3, 22)
HOLIDAY_GAP_START = date(2022, 1, 26)
HOLIDAY_GAP_END = date(2022, 2, 7)
PAUSE_SECONDS = 4.0
MAX_REPORT_BYTES = 8192


def validate_48_date_calendar(days):
    dates = validate_days(days)
    if (len(dates) != PILOT_DAYS or dates[0] != FIRST_DAY
        or dates[-1] != LAST_DAY or
        HOLIDAY_GAP_START not in dates or HOLIDAY_GAP_END not in dates
        or any(HOLIDAY_GAP_START < day < HOLIDAY_GAP_END for day in dates)
        or date(2022, 2, 28) in dates):
        raise ValueError("Expected exactly 48 source-confirmed Jan-March market sessions")
    return dates


def execute(database_url, *, fetcher=fetch_official_day, sleeper=time.sleep,
            output=None):
    if not isinstance(database_url, str) or not database_url:
        raise ValueError("Explicit read-only Neon roster/calendar URL required")
    import psycopg
    with psycopg.connect(
        database_url, connect_timeout=20,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '45000ms'")
        allowed = load_current_twse_allowed(conn)
        with conn.cursor() as cur:
            cur.execute(
                REFERENCE_CALENDAR_SQL,
                (FIRST_DAY, LAST_DAY, PILOT_DAYS + 1),
            )
            result = cur.fetchall()
        dates = validate_48_date_calendar([item[0] for item in result])
        previously_processed = _processed_days(conn)
        if any(day in previously_processed for day in dates):
            raise ValueError("One or more 2022 dates has official import receipt; refuse")
    if len(allowed) < 700 or ("twse", "1589") in allowed:
        raise ValueError("Missing fresh official-current-listed owner-allowed TWSE roster")

    calls = 0
    def limited_official_request(day):
        nonlocal calls
        if calls >= PILOT_DAYS or dates[calls] != day:
            raise RuntimeError("48-day source request cap/order violated")
        if calls:
            sleeper(PAUSE_SECONDS)
        calls += 1
        return fetcher(day)

    report = compute_stream(dates, allowed, limited_official_request)
    if (calls != PILOT_DAYS or
        report.get("authentic_source_days_evaluated") != PILOT_DAYS or
        report.get("stock_ma240_passes") != 0 or
        report.get("raw_price_or_factor_rows_persisted") != 0 or
        report.get("neon_rows_written") != 0):
        raise RuntimeError("Scope-limited 48-day source feasibility check failed")

    report["scope"] = "TWSE_2022_48_REAL_MARKET_DAYS_SHARED_MEMORY_ONLY"
    report["actual_official_http_requests"] = calls
    report["maximum_official_http_requests"] = PILOT_DAYS
    report["minimum_request_interval_seconds"] = PAUSE_SECONDS
    report["lunar_new_year_official_nontrading_gap_excluded"] = True
    report["no_240_session_real_market_factor_claim"] = True
    report["github_hosted_runner_class"] = "standard_public_repository_ubuntu"
    report["no_raw_ohlcv_or_factor_data_artifact"] = True
    text = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if len(text.encode("utf-8")) > MAX_REPORT_BYTES:
        raise RuntimeError("Unexpectedly large source-only aggregate proof")
    if output is None:
        print(text)
    else:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(
        description="One-time 48 real old TWSE trading days with 4s request spacing")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    execute(os.getenv("DATABASE_URL", ""), output=args.output)


if __name__ == "__main__":
    main()
