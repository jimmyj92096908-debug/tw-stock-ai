"""Bounded catch-up for previously stale, high-priority Taiwan stocks.

Only the two reviewed stocks (2330 and 6488). Each run requests at most
4 archive/recent months per stock, never attempts all-market 5-year HTTP loops.
Does not push LINE. Requires an explicit two-step gate before any DB write.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from full_market_refresh import (
    plan_download_windows, refresh_one,
)
from build_adjusted_prices import build as build_adjusted_stock
from calculate_technicals import calculate_stock as calculate_technical_stock
from calculate_smc import calculate_stock as calculate_smc_stock

TARGETS = (("twse","2330"),("tpex","6488"))
QUERY = """
SELECT sm.market,sm.stock_id,sm.stock_name,
       MIN(p.trade_date) FILTER (WHERE p.close IS NOT NULL) AS earliest_trade_date,
       MAX(p.trade_date) FILTER (WHERE p.close IS NOT NULL) AS latest_trade_date
FROM public.stock_master sm
LEFT JOIN public.daily_prices p
  ON p.market=sm.market AND p.stock_id=sm.stock_id
WHERE sm.market=%s AND sm.stock_id=%s
GROUP BY sm.market,sm.stock_id,sm.stock_name
"""


def execute(database_url: str, *, apply: bool = False, today=None) -> list[dict]:
    if not database_url:
        raise ValueError("DATABASE_URL must be configured")
    if apply and os.getenv("STOCK_HISTORY_WRITE_ENABLED") != "yes":
        raise ValueError("Historical writes remain disabled until explicitly gated")
    today=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    result=[]
    with psycopg.connect(database_url,row_factory=dict_row,connect_timeout=20) as conn:
        for market,code in TARGETS:
            with conn.cursor() as cur:
                cur.execute(QUERY,(market,code))
                row=cur.fetchone()
            if not row:
                raise ValueError(f"Target stock not in stock_master: {market}/{code}")
            plan=plan_download_windows(row,today)
            months=sum(
                (end.year-start.year)*12 + end.month-start.month + 1
                for start,end in plan
            )
            if months>5 or months<1:
                raise ValueError("Unsafe monthly request bound")
            record={"market":market,"code":code,
                    "months":months,"windows":[
                        f"{start:%Y-%m}..{end:%Y-%m}" for start,end in plan
                    ]}
            if apply:
                refresh_one(conn,row,today)
                adjusted=build_adjusted_stock(conn,market,code)
                technical=calculate_technical_stock(conn,market,code)
                smc=calculate_smc_stock(conn,market,code)
                if min(adjusted,technical,smc) <= 0:
                    raise RuntimeError("Historical data/indicators are still insufficient")
                record["computed"]={"adjusted":adjusted,"technical":technical,"smc":smc}
            result.append(record)
    return result


def main():
    parser=argparse.ArgumentParser(description="Bounded history catch-up for 2330/6488")
    parser.add_argument("--apply",action="store_true",help="Apply only when gated")
    args=parser.parse_args()
    result=execute(os.getenv("DATABASE_URL",""),apply=args.apply)
    for x in result:
        print(
            f"{x['market']} {x['code']}: {x['months']} months "
            f"({', '.join(x['windows'])}); "
            f"{'applied' if args.apply else 'dry-run'}"
        )
        if "computed" in x:
            print("Adjusted, technical and SMC row counts: "
                  + ", ".join(f"{k}={v}" for k,v in x["computed"].items()))


if __name__=="__main__":
    main()
