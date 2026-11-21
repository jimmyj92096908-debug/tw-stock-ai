"""Read-only TPEx current-price short-history gap audit.

A first OBSERVED price date is never an official IPO/listing date. No inferred
historic sessions, retroactive scores, paid APIs, LINE sends or raw writes.
This aggregates counts only; no ticker lists in scheduled artifacts.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

MIN_DAYS = 60
EXPECTED_BANDS = ("0-19", "20-29", "30-39", "40-49", "50-59", "60+")

GAPS_SQL = """
WITH last_market AS (
 SELECT MAX(trade_date) latest_date FROM public.daily_prices WHERE close>0
), history AS (
 SELECT stock_id,
   COUNT(*) FILTER(WHERE close>0 AND volume>=0)::int valid_days,
   MIN(trade_date) FILTER(WHERE close>0 AND volume>=0) first_observed,
   MAX(trade_date) FILTER(WHERE close>0 AND volume>=0) last_observed
 FROM public.daily_prices WHERE market='tpex'
 GROUP BY stock_id
), currently_priced AS (
 SELECT h.stock_id,h.valid_days,h.first_observed,h.last_observed,l.latest_date
 FROM history h
 CROSS JOIN last_market l
 JOIN public.daily_prices today
   ON today.market='tpex' AND today.stock_id=h.stock_id
  AND today.trade_date=l.latest_date
 WHERE today.close>0 AND today.volume>=0
)
SELECT CASE
 WHEN valid_days>=60 THEN '60+'
 WHEN valid_days>=50 THEN '50-59'
 WHEN valid_days>=40 THEN '40-49'
 WHEN valid_days>=30 THEN '30-39'
 WHEN valid_days>=20 THEN '20-29'
 ELSE '0-19' END AS band,
 COUNT(*)::int AS stocks,
 MIN(first_observed) AS earliest_observed_start,
 MAX(first_observed) AS latest_observed_start,
 MAX(latest_date) AS latest_market_date
FROM currently_priced
GROUP BY 1
ORDER BY 1
"""


def check_and_aggregate(rows):
    if not isinstance(rows,list):
        raise ValueError("Verified SQL aggregate rows required")
    seen=set()
    result={label:0 for label in EXPECTED_BANDS}
    dates=set()
    start_by_band={}
    for raw in rows:
        if not isinstance(raw,dict):
            raise ValueError("Unexpected TPEx gap row")
        band=raw.get("band")
        n=raw.get("stocks")
        if band not in EXPECTED_BANDS or band in seen or type(n) is not int or n<0:
            raise ValueError("Invalid or duplicate TPEx gap band")
        seen.add(band)
        result[band]=n
        market_day=raw.get("latest_market_date")
        first=raw.get("earliest_observed_start")
        latest=raw.get("latest_observed_start")
        if (type(market_day) is not date or type(first) is not date
                or type(latest) is not date or first>latest or latest>market_day):
            raise ValueError("Invalid observed TPEx trading history dates")
        dates.add(market_day)
        start_by_band[band]={
            "first_observed_earliest":first.isoformat(),
            "first_observed_latest":latest.isoformat(),
        }
    if len(dates)!=1 or sum(result.values())<500:
        raise ValueError("Invalid whole-TPEx daily market coverage")
    total=sum(result.values())
    below=sum(result[k] for k in EXPECTED_BANDS if k!="60+")
    return {
        "schema_version":1,
        "market":"tpex",
        "price_date":next(iter(dates)).isoformat(),
        "currently_priced":total,
        "eligible_real_60_session_history":result["60+"],
        "below_60_session_history":below,
        "bands":result,
        "observed_price_date_ranges":start_by_band,
        "official_listing_dates_independently_verified":False,
        "new_listing_vs_missing_history_not_yet_classified":True,
        "inferred_trading_dates_inserted":False,
        "read_only":True,
        "line_trade_signals_enabled":False,
        "orders_enabled":False,
    }


def execute(url,*,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        rows=[dict(row) for row in conn.execute(GAPS_SQL).fetchall()]
    report=check_and_aggregate(rows)
    report["recorded_utc"]=datetime.now(timezone.utc).isoformat()
    if report_path:
        path=Path(report_path)
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(path.suffix+".tmp")
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                       encoding="utf-8")
        tmp.replace(path)
    return report


def main():
    parser=argparse.ArgumentParser(description="Current TPEx close-date short-history gap aggregate")
    parser.add_argument("--out",type=Path,default=Path("tpex-short-history-gap-evidence.json"))
    args=parser.parse_args()
    result=execute(os.environ.get("DATABASE_URL",""),report_path=args.out)
    print(json.dumps({
        "price_date":result["price_date"],
        "currently_priced":result["currently_priced"],
        "real_60_session_eligible":result["eligible_real_60_session_history"],
        "below_60":result["below_60_session_history"],
        "bands":result["bands"],
        "listing_date_verified":False,
        "database_written":False,
    },ensure_ascii=False))


if __name__=="__main__":
    main()
