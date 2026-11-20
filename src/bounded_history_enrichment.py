"""Bounded, opt-in historical enrichment after official one-day market snapshots.

Limits: at most two stocks per market and at most five source months per stock.
Only stocks with an existing verified close and fewer than 60 daily prices are
eligible. Default is dry-run. Never fabricates OHLC data or sends LINE pushes.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from full_market_refresh import plan_download_windows, refresh_one
from build_adjusted_prices import build as build_adjusted_stock
from calculate_technicals import calculate_stock as calculate_technical_stock
from calculate_smc import calculate_stock as calculate_smc_stock

LOGGER = logging.getLogger(__name__)
MAX_PER_MARKET = 2
MAX_SOURCE_MONTHS = 5

CANDIDATES_SQL = """
WITH priced AS (
 SELECT sm.market,sm.stock_id,sm.stock_name,
        MIN(p.trade_date) FILTER (WHERE p.close IS NOT NULL) earliest_trade_date,
        MAX(p.trade_date) FILTER (WHERE p.close IS NOT NULL) latest_trade_date,
        COUNT(p.trade_date) FILTER (WHERE p.close IS NOT NULL)::int price_days
 FROM public.stock_master sm
 LEFT JOIN public.daily_prices p
   ON p.market=sm.market AND p.stock_id=sm.stock_id
 WHERE sm.market=%s AND sm.stock_id<>'1808'
 GROUP BY sm.market,sm.stock_id,sm.stock_name
)
SELECT priced.market,priced.stock_id,priced.stock_name,
       priced.earliest_trade_date,priced.latest_trade_date,priced.price_days
FROM priced
LEFT JOIN public.market_data_refresh_state st
  ON st.market=priced.market AND st.stock_id=priced.stock_id
WHERE priced.price_days BETWEEN 1 AND 59
ORDER BY st.last_attempt_at ASC NULLS FIRST, priced.price_days ASC, priced.stock_id
LIMIT %s
"""

CHECK_SQL = """
SELECT COUNT(*)::int price_days, MIN(trade_date) min_day, MAX(trade_date) max_day
FROM public.daily_prices
WHERE market=%s AND stock_id=%s AND close IS NOT NULL
"""

def select_candidates(conn, market: str, limit: int) -> list[dict]:
    if market not in ("twse","tpex") or not 1 <= limit <= MAX_PER_MARKET:
        raise ValueError("Unsafe market or batch limit")
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL,(market,limit))
        return [dict(row) for row in cur.fetchall()]


def count_months(windows) -> int:
    return sum((end.year-start.year)*12+end.month-start.month+1 for start,end in windows)


def execute(database_url: str, *, apply=False, per_market=2, today=None, pause_seconds=3):
    if not database_url:
        raise ValueError("DATABASE_URL required")
    if not 1 <= per_market <= MAX_PER_MARKET:
        raise ValueError("Only 1 or 2 stocks per market are permitted")
    if apply and os.environ.get("STOCK_ENRICHMENT_WRITE_ENABLED")!="yes":
        raise ValueError("Database writing requires explicit opt-in gate")
    today=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    results=[]
    with psycopg.connect(database_url,connect_timeout=20,row_factory=dict_row) as conn:
        for market in ("twse","tpex"):
            candidates=select_candidates(conn,market,per_market)
            for stock in candidates:
                windows=plan_download_windows(stock,today)
                months=count_months(windows)
                if not 1<=months<=MAX_SOURCE_MONTHS:
                    raise ValueError("Bounded history window exceeded")
                result={
                    "market":market,"stock_id":stock["stock_id"],
                    "old_price_days":stock["price_days"],
                    "months_requested":months,"status":"dry-run"
                }
                if apply:
                    try:
                        refresh_one(conn,stock,today)
                        bars=build_adjusted_stock(conn,market,stock["stock_id"])
                        tech=calculate_technical_stock(conn,market,stock["stock_id"])
                        smc=calculate_smc_stock(conn,market,stock["stock_id"])
                        with conn.cursor() as cur:
                            cur.execute(CHECK_SQL,(market,stock["stock_id"]))
                            checked=cur.fetchone()
                        if min(bars,tech,smc)<=0 or checked["price_days"]<=stock["price_days"]:
                            raise RuntimeError("History enrichment did not add verified price days")
                        result.update({
                            "status":"verified",
                            "price_days":checked["price_days"],
                            "technical_rows":tech,"smc_rows":smc,
                            "last_date":str(checked["max_day"])
                        })
                    except Exception as exc:
                        LOGGER.error("Enrichment failed for %s %s (%s)",market,stock["stock_id"],type(exc).__name__)
                        result["status"]="failed"
                        # Prevent leaking connection strings or private exception details.
                        result["error_type"]=type(exc).__name__
                    if pause_seconds>0:
                        time.sleep(pause_seconds)
                results.append(result)
    return results


def main():
    parser=argparse.ArgumentParser(description="Conservative official TWSE/TPEx history enrichment")
    parser.add_argument("--apply",action="store_true",help="Requires STOCK_ENRICHMENT_WRITE_ENABLED=yes")
    parser.add_argument("--per-market",type=int,default=2)
    args=parser.parse_args()
    results=execute(os.environ.get("DATABASE_URL",""),apply=args.apply,per_market=args.per_market)
    for row in results:
        print(f"{row['market']} {row['stock_id']}: {row['status']}; "
              f"source_months={row['months_requested']}; "
              f"price_days={row.get('price_days',row['old_price_days'])}")
    failed=sum(row["status"]=="failed" for row in results)
    if failed:
        raise SystemExit(f"Enrichment incomplete: {failed} of {len(results)} stocks failed")
    if not results:
        print("No thin-history stocks are eligible for this bounded batch")


if __name__=="__main__":
    main()
