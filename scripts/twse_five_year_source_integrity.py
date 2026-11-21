"""Read-only integrity audit for the 5-year official TWSE dated-source ledger.

The progress ledger claims only verified imported/closed official dates. This
independent check verifies actual persisted source-date equivalence and raw bar
sanity, without changing prices, recalculating factors, trading or sending LINE.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

STATE_SQL="""
WITH tracked AS (
 SELECT count(*)::int processed_days,
        count(*) FILTER(WHERE status='imported')::int imported_days,
        count(*) FILTER(WHERE status='closed')::int closed_days,
        count(*) FILTER (
          WHERE status NOT IN ('imported','closed')
             OR (status='imported' AND
                 (qualified<500 OR inserted<0 OR inserted>qualified))
             OR (status='closed' AND (qualified<>0 OR inserted<>0))
        )::int invalid_progress_days,
        coalesce(sum(inserted),0)::bigint inserted_receipts
 FROM public.twse_history_day_progress
), sourced AS (
 SELECT count(*)::bigint official_price_rows,
        count(DISTINCT trade_date)::int official_price_dates,
        count(*) FILTER (
          WHERE close IS NULL OR close<=0 OR volume IS NULL OR volume<0
             OR high IS NULL OR low IS NULL OR open IS NULL
             OR low<=0 OR high<low OR open<low OR open>high
             OR close<low OR close>high
        )::bigint invalid_ohlcv_rows,
        min(trade_date) earliest_official_date
 FROM public.daily_prices
 WHERE market='twse' AND source='TWSE_MI_INDEX_ALLBUT0999'
)
SELECT tracked.*, sourced.*,
       (SELECT count(*)::int FROM generate_series(
          ((now() AT TIME ZONE 'Asia/Taipei')::date-INTERVAL '5 years')::date,
          ((now() AT TIME ZONE 'Asia/Taipei')::date-INTERVAL '1 day')::date,
          INTERVAL '1 day'
       ) d(day_date)
       WHERE extract(isodow FROM d.day_date) BETWEEN 1 AND 5
         AND NOT EXISTS (
           SELECT 1 FROM public.twse_history_day_progress progress
           WHERE progress.trade_date=d.day_date::date
             AND progress.status IN ('imported','closed')
       )) missing_five_year_weekdays,
       pg_database_size(current_database())::bigint AS database_bytes
FROM tracked CROSS JOIN sourced
"""

COUNT_KEYS=("processed_days","imported_days","closed_days",
            "invalid_progress_days","inserted_receipts",
            "official_price_rows","official_price_dates",
            "invalid_ohlcv_rows","database_bytes",
            "missing_five_year_weekdays")


def evaluate(state):
    if not isinstance(state,dict):
        raise RuntimeError("Invalid official TWSE database evidence")
    if any(type(state.get(key)) is not int or state[key]<0
           for key in COUNT_KEYS):
        raise RuntimeError("Missing or invalid official source reconciliation counters")
    if (state["processed_days"]!=state["imported_days"]+
        state["closed_days"]):
        raise RuntimeError("TWSE session ledger partition mismatch")
    if state["invalid_progress_days"]!=0:
        raise RuntimeError("Invalid official TWSE historical session receipt")
    if (state["official_price_dates"]!=state["imported_days"]
        or state["official_price_rows"]<state["official_price_dates"]
        or state["official_price_dates"]<100):
        raise RuntimeError("TWSE raw dated source does not reconcile with imported ledger")
    if state["invalid_ohlcv_rows"]!=0:
        raise RuntimeError("Invalid saved official TWSE OHLCV source row")
    if state["earliest_official_date"] is None:
        raise RuntimeError("Missing earliest genuine official TWSE date")
    return {
        "scope":"TWSE_FIVE_YEAR_OFFICIAL_SOURCE_INTEGRITY_READ_ONLY",
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "evidence":state,
        "official_date_progress_reconciled":True,
        "raw_source_ohlcv_validated":True,
        "database_mutations":0,
        "factor_rows_materialized":0,
        "line_messages_sent":False,
        "live_trading_enabled":False,
        "paid_service_requested":False,
        # Calendar-date source coverage is distinct from full issuer histories,
        # adjusted factors, or a pristine model validation sample.
        "five_year_dates_fully_examined":bool(
            state["missing_five_year_weekdays"]==0
            and state["official_price_dates"]>=1000
        ),
        "model_holdout_validated":False,
    }


def run(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url, connect_timeout=20, row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='60000ms'")
        evidence=dict(conn.execute(STATE_SQL).fetchone())
    return evaluate(evidence)


def main():
    parser=argparse.ArgumentParser(description="Read-only TWSE verified dated historical bar ledger audit")
    parser.add_argument("--report",type=Path,default=Path("twse-verified-source-integrity.json"))
    args=parser.parse_args()
    report=run(os.environ.get("DATABASE_URL",""))
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+"\n",
                           encoding="utf-8")
    print(json.dumps({
        "official_price_dates":report["evidence"]["official_price_dates"],
        "official_price_rows":report["evidence"]["official_price_rows"],
        "invalid_progress_days":report["evidence"]["invalid_progress_days"],
        "invalid_ohlcv_rows":report["evidence"]["invalid_ohlcv_rows"],
        "database_mutations":0,
        "five_year_dates_fully_examined":report["five_year_dates_fully_examined"],
        "live_trading_enabled":False,
    },ensure_ascii=False))


if __name__=="__main__":
    main()
