"""Incrementally compute verified adjusted bars, technicals and SMC.

A whole-market daily snapshot gives quotes, not trading history or credible
long-horizon signals. Compute indicators only for stocks with >=60 valid close
sessions; never synthesize missing prices, and never send LINE messages.

Default: dry run. Apply requires --apply AND
STOCK_INDICATOR_CATCHUP_WRITE_ENABLED=yes. Maximum 20 per market per run.
"""
from __future__ import annotations

import argparse
import logging
import os

import psycopg
from psycopg.rows import dict_row

from build_adjusted_prices import build as build_adjusted_stock
from calculate_technicals import calculate_stock as calculate_technical_stock
from calculate_smc import calculate_stock as calculate_smc_stock

LOGGER=logging.getLogger(__name__)
MIN_VERIFIED_PRICE_DAYS=60
MAX_PER_MARKET=20

CANDIDATES_SQL="""
WITH priced AS (
 SELECT p.market,p.stock_id,
        COUNT(*) FILTER (WHERE p.close IS NOT NULL)::int AS close_days,
        MAX(p.trade_date) FILTER (WHERE p.close IS NOT NULL) AS latest_close
 FROM public.daily_prices p
 WHERE p.market=%s AND p.stock_id<>'1808'
 GROUP BY p.market,p.stock_id
 HAVING COUNT(*) FILTER (WHERE p.close IS NOT NULL)>=%s
), analysis AS (
 SELECT p.market,p.stock_id,p.close_days,p.latest_close,
   (SELECT COUNT(*)::int FROM public.daily_technicals t
    WHERE t.market=p.market AND t.stock_id=p.stock_id) AS technical_rows,
   (SELECT COUNT(*)::int FROM public.daily_smc s
    WHERE s.market=p.market AND s.stock_id=p.stock_id) AS smc_rows
 FROM priced p
)
SELECT market,stock_id,close_days,latest_close,technical_rows,smc_rows
FROM analysis
WHERE (technical_rows < close_days OR smc_rows < close_days)
  AND latest_close >= (
      SELECT MAX(trade_date) FROM public.daily_prices
      WHERE close IS NOT NULL
  ) - INTERVAL '7 days'
ORDER BY CASE WHEN technical_rows=0 OR smc_rows=0 THEN 0 ELSE 1 END,
         close_days DESC, stock_id
LIMIT %s
"""

VERIFY_SQL="""
SELECT
  (SELECT COUNT(*)::int FROM public.daily_adjusted_prices
   WHERE market=%s AND stock_id=%s) AS adjusted_rows,
  (SELECT COUNT(*)::int FROM public.daily_technicals
   WHERE market=%s AND stock_id=%s) AS technical_rows,
  (SELECT COUNT(*)::int FROM public.daily_smc
   WHERE market=%s AND stock_id=%s) AS smc_rows
"""

def select_candidates(conn,market,limit):
    if market not in ("twse","tpex") or not 1<=limit<=MAX_PER_MARKET:
        raise ValueError("Unsafe market or indicator catch-up batch")
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL,(market,MIN_VERIFIED_PRICE_DAYS,limit))
        return [dict(row) for row in cur.fetchall()]


def run(database_url: str, *, apply=False, per_market=12) -> list[dict]:
    if not database_url:
        raise ValueError("DATABASE_URL required")
    if not 1<=per_market<=MAX_PER_MARKET:
        raise ValueError("per_market must be 1..20")
    if apply and os.environ.get("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED")!="yes":
        raise ValueError("Indicator calculation writes require explicit opt-in")
    results=[]
    with psycopg.connect(database_url,row_factory=dict_row,connect_timeout=20) as conn:
        for market in ("twse","tpex"):
            selected=select_candidates(conn,market,per_market)
            for stock in selected:
                item={"market":market,"stock_id":stock["stock_id"],
                      "price_days":stock["close_days"],
                      "status":"dry-run"}
                if apply:
                    try:
                        # A single failing symbol must roll back all three
                        # indicator writes without aborting later stocks.
                        # The preceding SELECT has already opened the outer
                        # psycopg transaction; nested .transaction() is a
                        # per-stock SAVEPOINT on PostgreSQL.
                        with conn.transaction():
                            adjusted=build_adjusted_stock(conn,market,stock["stock_id"])
                            technical=calculate_technical_stock(conn,market,stock["stock_id"])
                            smc=calculate_smc_stock(conn,market,stock["stock_id"])
                            with conn.cursor() as cur:
                                cur.execute(VERIFY_SQL,(market,stock["stock_id"],
                                                        market,stock["stock_id"],
                                                        market,stock["stock_id"]))
                                verification=cur.fetchone()
                            if min(adjusted,technical,smc)<MIN_VERIFIED_PRICE_DAYS:
                                raise RuntimeError("Insufficient indicators from verified history")
                            if (verification["adjusted_rows"]<stock["close_days"] or
                                verification["technical_rows"]<stock["close_days"] or
                                verification["smc_rows"]<stock["close_days"]):
                                raise RuntimeError("Stored indicator coverage below valid price history")
                            item.update({"status":"verified",
                                         "technical_rows":verification["technical_rows"],
                                         "smc_rows":verification["smc_rows"]})
                    except Exception as exc:
                        LOGGER.error("Indicator catch-up failed: %s %s (%s)",
                                     market,stock["stock_id"],type(exc).__name__)
                        item.update({"status":"failed","error_type":type(exc).__name__})
                results.append(item)
    return results


def main():
    parser=argparse.ArgumentParser(description="Bounded indicator catch-up after historical price verification")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--per-market",type=int,default=12)
    args=parser.parse_args()
    results=run(os.environ.get("DATABASE_URL",""),apply=args.apply,
                per_market=args.per_market)
    for item in results:
        print(f"{item['market']} {item['stock_id']}: "
              f"{item['status']}; verified_history={item['price_days']}")
    failed=sum(item["status"]=="failed" for item in results)
    if failed:
        raise SystemExit(f"Indicator catch-up incomplete: {failed} of {len(results)} failed")
    if not results:
        print("No eligible 60-session history is waiting for indicator computation")


if __name__=="__main__":
    main()
