"""Read-only daily five-year TWSE importer gate; no LINE, trading, or writes.

Never require materialized TPEx factor history merely to append official
TWSE source bars. Both live database storage and current exchange-listing
evidence must remain safe; every outstanding weekday is checked against the
dated verified-progress ledger without fabricating market holidays.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

MAX_DATABASE_BYTES = 800_000_000
MIN_SOURCE_DAYS = 100
MIN_ACTIVE_TWSE = 700

STATE_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT pg_database_size(current_database())::bigint AS database_bytes,
       (SELECT count(*)::int FROM official_current_listed
        WHERE market='twse') AS active_twse,
       (SELECT count(DISTINCT trade_date)::int FROM public.daily_prices
        WHERE market='twse'
          AND source='TWSE_MI_INDEX_ALLBUT0999') AS verified_source_days,
       (SELECT count(*)::int
          FROM generate_series(
             ((now() AT TIME ZONE 'Asia/Taipei')::date - INTERVAL '5 years')::date,
             ((now() AT TIME ZONE 'Asia/Taipei')::date - INTERVAL '1 day')::date,
             INTERVAL '1 day'
          ) AS day(day_date)
         WHERE extract(isodow FROM day.day_date) BETWEEN 1 AND 5
           AND NOT EXISTS (
             SELECT 1 FROM public.twse_history_day_progress p
              WHERE p.trade_date=day.day_date::date
                AND p.status IN ('imported','closed')
           )) AS missing_weekdays
"""


def snapshot(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url, connect_timeout=20, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        evidence = dict(conn.execute(STATE_SQL).fetchone())
    for key in ("database_bytes", "active_twse", "verified_source_days",
                "missing_weekdays"):
        if type(evidence.get(key)) is not int or evidence[key] < 0:
            raise RuntimeError("Five-year source evidence invalid")
    return evidence


def decide(evidence):
    return (
        evidence["database_bytes"] < MAX_DATABASE_BYTES
        and evidence["verified_source_days"] >= MIN_SOURCE_DAYS
        and evidence["active_twse"] >= MIN_ACTIVE_TWSE
        and evidence["missing_weekdays"] > 0
    )


def main():
    state = snapshot(os.getenv("DATABASE_URL", ""))
    ready = decide(state)
    result = {
        "scope": "TWSE_5Y_OFFICIAL_ACTIVE_ONLY",
        "should_run": ready, "evidence": state, "read_only": True,
        "line_messages_sent": False, "trading_enabled": False,
        "paid_upgrade_requested": False,
    }
    print(json.dumps(result, ensure_ascii=False))
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write("should_run=" + str(ready).lower() + "\n")


if __name__ == "__main__":
    main()
