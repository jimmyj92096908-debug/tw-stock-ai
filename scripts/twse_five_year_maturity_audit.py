"""Read-only TWSE officially-active stock history maturity and storage audit.

This audit describes actually observed positive-volume-valid?  No invented days:
only dates with a positive closing price and non-negative volume are counted.
A 1,000-session threshold is an indicator of depth, NOT proof of five complete
calendar years for a recently listed issuer or of unbiased model validation.
Never modifies historical prices, scores, LINE, or trade signals.
"""
from __future__ import annotations

import argparse
from datetime import date,datetime,timezone
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

MATURITY_SQL=CURRENT_OFFICIAL_LISTED_CTE+"""
, active AS (
 SELECT stock_id FROM official_current_listed WHERE market='twse'
), priced AS (
 SELECT a.stock_id,
        count(p.trade_date) FILTER(WHERE p.close>0 AND p.volume>=0)::int valid_days,
        max(p.trade_date) FILTER(WHERE p.close>0 AND p.volume>=0) latest_day
 FROM active a
 LEFT JOIN public.daily_prices p
   ON p.market='twse' AND p.stock_id=a.stock_id
 GROUP BY a.stock_id
)
SELECT count(*)::int active_stocks,
       count(*) FILTER(WHERE valid_days>=240)::int mature_240,
       count(*) FILTER(WHERE valid_days>=1000)::int mature_1000,
       count(*) FILTER(WHERE valid_days=0)::int no_valid_price,
       min(valid_days)::int minimum_days,
       round(avg(valid_days),1) AS average_days,
       (SELECT count(DISTINCT trade_date)::int
        FROM public.daily_prices
        WHERE market='twse' AND source='TWSE_MI_INDEX_ALLBUT0999')
          AS official_bulk_sessions,
       (SELECT count(*)::bigint FROM public.daily_prices
        WHERE market='twse') AS raw_twse_rows,
       (SELECT pg_database_size(current_database())::bigint)
          AS database_bytes
FROM priced
"""

KEYS=("active_stocks","mature_240","mature_1000","no_valid_price",
      "minimum_days","official_bulk_sessions","raw_twse_rows",
      "database_bytes")


def capture(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(
        url,connect_timeout=20,row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        values=dict(conn.execute(MATURITY_SQL).fetchone())
    for key in KEYS:
        if type(values.get(key)) is not int or values[key]<0:
            raise RuntimeError("Unverifiable official TWSE maturity count")
    n=values["active_stocks"]
    if not (n>=700 and 0<=values["mature_1000"]
            <=values["mature_240"]<=n
            and values["no_valid_price"]<=n):
        raise RuntimeError("Stale official listing or impossible maturity totals")
    if values["average_days"] is None:
        raise RuntimeError("Missing average valid session maturity")
    return values


def describe(values):
    return {
        "scope":"TWSE_CURRENT_OFFICIAL_ACTIVE_FIVE_YEAR_MATURITY",
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "evidence":values,
        "derived_240_day_ready":values["mature_240"]>=500
            and values["official_bulk_sessions"]>=240,
        "fully_five_year_verified":False,
        "raw_price_rows_overwritten":False,
        "db_capacity_warning":values["database_bytes"]>=650_000_000,
        "db_capacity_stop":values["database_bytes"]>=800_000_000,
        "line_messages_sent":False,
        "trading_approved":False,
    }


def main():
    ap=argparse.ArgumentParser(description="Read-only official listed TWSE maturity proof")
    ap.add_argument("--report",type=Path,default=Path("twse-five-year-maturity.json"))
    args=ap.parse_args()
    result=describe(capture(os.environ.get("DATABASE_URL","")))
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(
        json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n",
        encoding="utf-8",
    )
    print(json.dumps(result,ensure_ascii=False,default=str))


if __name__=="__main__":
    main()
