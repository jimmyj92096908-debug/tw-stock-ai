"""Read-only TWSE historical coverage triage; never backfills or sends signals.

Dates are drawn from existing 2330 sessions. These are *candidates* for
review, not proof that every issuer traded on each date. No paid resources.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
import json
import os

CALENDAR_SQL = """
SELECT p.trade_date, COUNT(*)::integer AS observed,
       MAX(CASE WHEN h.status = 'imported' THEN 1 ELSE 0 END)::integer AS imported,
       MAX(CASE WHEN h.status = 'closed' THEN 1 ELSE 0 END)::integer AS closed
FROM public.daily_prices AS p
LEFT JOIN public.twse_history_day_progress AS h ON h.trade_date = p.trade_date
WHERE p.market = 'twse'
  AND p.trade_date >= %s
  AND p.trade_date < %s
GROUP BY p.trade_date
HAVING COUNT(*) FILTER (WHERE p.stock_id = '2330') > 0
ORDER BY p.trade_date
"""

def summarize(rows, *, minimum=700, limit=30):
    """Rank undercovered, unprocessed sessions oldest first."""
    if not 1 <= minimum <= 1500 or not 1 <= limit <= 100:
        raise ValueError("Invalid report limits")
    parsed = []
    for day, observed, imported, closed in rows:
        if not isinstance(day, date) or min(observed, imported, closed) < 0:
            raise ValueError("Invalid aggregate ledger row")
        parsed.append((day, observed, bool(imported), bool(closed)))
    candidates = [
        {"trade_date": day.isoformat(), "observed": n}
        for day, n, imported, closed in parsed
        if not imported and not closed and n < minimum
    ]
    years = {}
    for day, n, imported, closed in parsed:
        yr = str(day.year)
        group = years.setdefault(yr, {
            "reference_dates": 0,
            "unprocessed_undercovered_dates": 0,
            "processed_but_sparse_dates": 0,
        })
        group["reference_dates"] += 1
        if n < minimum:
            if imported:
                group["processed_but_sparse_dates"] += 1
            elif not closed:
                group["unprocessed_undercovered_dates"] += 1
    return {
        "scope": "TWSE_READ_ONLY_COVERAGE_TRIAGE_NOT_COMPLETION_PROOF",
        "reference": "existing_2330_trade_dates_only",
        "observed_market_dates": len(parsed),
        "receipt_imported_dates": sum(imported for _, _, imported, _ in parsed),
        "receipt_closed_dates": sum(closed for _, _, _, closed in parsed),
        "unprocessed_undercovered_dates": len(candidates),
        "minimum_count_heuristic": minimum,
        "by_year": years,
        "priority_dates": candidates[:limit],
        "writes": 0,
        "line_messages": 0,
        "does_not_prove_listing_history_or_five_year_completion": True,
    }

def default_window(today):
    """A rolling five-year window, including today's date but no future days."""
    try:
        start = today.replace(year=today.year - 5)
    except ValueError:
        start = today.replace(year=today.year - 5, day=28)
    return start, today + timedelta(days=1)


def run(database_url, *, start=None, end=None, minimum=700, limit=30):
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    default_start, default_end = default_window(today)
    start = start if start is not None else default_start
    end = end if end is not None else default_end
    if not database_url or not isinstance(start, date) or not isinstance(end, date) or not start < end:
        raise ValueError("Read-only database URL and valid dates required")
    import psycopg
    with psycopg.connect(
        database_url, connect_timeout=20,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '45000ms'")
        with conn.cursor() as cur:
            cur.execute(CALENDAR_SQL, (start, end))
            return summarize(cur.fetchall(), minimum=minimum, limit=limit)

def main():
    parser = argparse.ArgumentParser(description="Read-only TWSE gap triage")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--minimum", type=int, default=700)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    result = run(os.environ.get("DATABASE_URL", ""), start=args.start,
                 end=args.end, minimum=args.minimum, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
