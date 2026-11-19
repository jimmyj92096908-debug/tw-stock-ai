"""Safely fill missing daily bars from two official whole-market feeds.

Usage:
  python src/official_snapshot_ingest.py                # fetch/validate, NO WRITES
  STOCK_SNAPSHOT_WRITE_ENABLED=yes python src/official_snapshot_ingest.py --apply

No stock_master creation/deletion, no historical bar replacements, no LINE
messages. The explicit second gate makes accidental production writes harder.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date

import psycopg

from official_market_feed import fetch_latest_snapshot, select_candidates

logger = logging.getLogger(__name__)

INSERT_MISSING_SQL = """
INSERT INTO public.daily_prices (
 market,stock_id,trade_date,open,high,low,close,
 volume,turnover,price_change,transactions,source
) VALUES (
 %(market)s,%(stock_id)s,%(trade_date)s,%(open)s,%(high)s,%(low)s,%(close)s,
 %(volume)s,%(turnover)s,%(price_change)s,%(transactions)s,%(source)s
)
ON CONFLICT (market,stock_id,trade_date) DO NOTHING
"""

ALLOWED_SQL = "SELECT market,stock_id FROM public.stock_master"
DAILY_COUNT_SQL = """
SELECT COUNT(*)::int AS count
FROM public.daily_prices
WHERE market=%s AND trade_date=%s AND close IS NOT NULL
"""


def load_allowed(conn) -> set[tuple[str,str]]:
    with conn.cursor() as cur:
        cur.execute(ALLOWED_SQL)
        return {(str(m),str(s)) for m,s in cur.fetchall()}


def write_missing(conn, market: str, day: date, bars: list[dict]) -> int:
    """Atomically insert a market's missing historical rows only."""
    if market not in ("twse", "tpex") or not bars:
        raise ValueError("Missing or invalid market bars")
    if any(row["market"] != market or row["trade_date"] != day for row in bars):
        raise ValueError("Mixed dates or markets are not allowed")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(DAILY_COUNT_SQL,(market,day))
            before=cur.fetchone()[0]
            for start in range(0,len(bars),200):
                cur.executemany(INSERT_MISSING_SQL,bars[start:start+200])
            cur.execute(DAILY_COUNT_SQL,(market,day))
            after=cur.fetchone()[0]
    if after < before:
        raise RuntimeError("Post-import count decreased unexpectedly")
    return after-before


def collect_batches(conn, *, today: date | None = None,
                    fetcher=fetch_latest_snapshot) -> list[tuple[str,date,list[dict]]]:
    allowed=load_allowed(conn)
    if len(allowed)<100:
        raise ValueError("Candidate universe too small; refusing to import")
    batches=[]
    for market in ("twse","tpex"):
        day,bars=fetcher(market,today=today)
        eligible=sum(1 for m,_ in allowed if m==market)
        minimum=max(100,int(eligible*0.5))
        selected=select_candidates(bars,allowed,minimum=minimum)
        batches.append((market,day,selected))
    return batches


def run(database_url: str, *, apply: bool = False,
        fetcher=fetch_latest_snapshot, today: date | None = None) -> list[dict]:
    if not database_url:
        raise ValueError("Missing DATABASE_URL")
    if apply and os.getenv("STOCK_SNAPSHOT_WRITE_ENABLED") != "yes":
        raise ValueError("Write is disabled without STOCK_SNAPSHOT_WRITE_ENABLED=yes")
    with psycopg.connect(database_url,connect_timeout=20) as conn:
        batches=collect_batches(conn,today=today,fetcher=fetcher)
        result=[]
        for market,day,bars in batches:
            inserted=write_missing(conn,market,day,bars) if apply else 0
            result.append({
                "market":market,
                "trade_date":day.isoformat(),
                "qualified":len(bars),
                "inserted":inserted,
                "mode":"apply" if apply else "dry-run",
            })
        return result


def main() -> None:
    parser=argparse.ArgumentParser(description="官方上市/上櫃市場每日快照；預設只驗證")
    parser.add_argument("--apply",action="store_true",help="明確寫入缺漏日K")
    args=parser.parse_args()
    url=os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set")
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    for row in run(url,apply=args.apply):
        print(
            f"{row['market']} {row['trade_date']}: "
            f"有效候選 {row['qualified']} 檔；"
            f"新增 {row['inserted']} 筆；模式 {row['mode']}"
        )


if __name__=="__main__":
    main()
