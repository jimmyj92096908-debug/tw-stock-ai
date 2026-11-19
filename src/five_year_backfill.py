"""Incremental five-year history backfill; selects stocks with incomplete coverage."""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date
import calendar
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

import market_data
import stock_list
import tpex_market_data
from db_storage import upsert_csv, read_history_csv
from build_adjusted_prices import build as build_adjusted_stock
from calculate_technicals import calculate_stock as calculate_technical_stock
from calculate_smc import calculate_stock as calculate_smc_stock

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data" / "history"
MARKET_MAP = {"上市": "twse", "上櫃": "tpex"}
LOG = logging.getLogger("five_year_backfill")


def five_year_start(today: date) -> date:
    """Stable month boundary: backfill from first day of month five years ago."""
    return date(today.year - 5, today.month, 1)


def target_month_end(today: date) -> date:
    """Stable target boundary for monthly progress keys."""
    return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])


def select_incomplete(universe: list[dict], coverage: dict, completed: set, market_filter: str = "both", start_date: date | None = None) -> list[dict]:
    """Prioritize stocks with no price rows, then the shortest existing history."""
    rows = [row for row in universe if market_filter == "both" or MARKET_MAP[row["market"]] == market_filter]
    rows = [row for row in rows if (MARKET_MAP[row["market"]], row["stock_id"]) not in completed]
    if start_date is not None:
        rows = [row for row in rows if coverage.get((MARKET_MAP[row["market"]], row["stock_id"])) is None or coverage[(MARKET_MAP[row["market"]], row["stock_id"])] > start_date]
    rows.sort(key=lambda row: (
        0 if coverage.get((MARKET_MAP[row["market"]], row["stock_id"])) is None else 1,
        coverage.get((MARKET_MAP[row["market"]], row["stock_id"])) or date.max,
        MARKET_MAP[row["market"]],
        row["stock_id"],
    ))
    return rows


def sync_universe(conn, universe: list[dict]) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO stock_master (market, stock_id, stock_name, industry)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (market,stock_id) DO UPDATE SET
                     stock_name=EXCLUDED.stock_name, industry=EXCLUDED.industry,
                     updated_at=NOW()""",
                [(MARKET_MAP[r["market"]],r["stock_id"],r["stock_name"],r["industry"]) for r in universe],
            )


def load_coverage(conn) -> tuple[dict, set]:
    with conn.cursor() as cur:
        cur.execute("""SELECT market,stock_id,MIN(trade_date) AS first_date
                       FROM daily_prices GROUP BY market,stock_id""")
        coverage = {(r["market"],r["stock_id"]):r["first_date"] for r in cur.fetchall()}
        cur.execute("""SELECT market,stock_id FROM backfill_progress
                       WHERE status='success' AND start_date=%s AND end_date=%s""",
                    (five_year_start(date.today()),target_month_end(date.today())))
        completed = {(r["market"],r["stock_id"]) for r in cur.fetchall()}
    return coverage, completed


def record_progress(conn, market: str, stock_id: str, start: date, end: date,
                    status: str, count: int, first_date, last_date, error: str | None):
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO backfill_progress
                (market,stock_id,start_date,end_date,status,rows_downloaded,
                 first_trade_date,last_trade_date,finished_at,github_run_id,error_message,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,%s,NOW())
                ON CONFLICT (market,stock_id,start_date,end_date) DO UPDATE SET
                status=EXCLUDED.status,rows_downloaded=EXCLUDED.rows_downloaded,
                first_trade_date=EXCLUDED.first_trade_date,last_trade_date=EXCLUDED.last_trade_date,
                finished_at=NOW(),github_run_id=EXCLUDED.github_run_id,
                error_message=EXCLUDED.error_message,updated_at=NOW()""",
                (market,stock_id,start,end,status,count,first_date,last_date,
                 os.environ.get("GITHUB_RUN_ID"),error))


def backfill_one(conn, stock: dict, start: date, end: date) -> int:
    market = MARKET_MAP[stock["market"]]
    stock_id = stock["stock_id"]
    module = market_data if market == "twse" else tpex_market_data
    directory = HISTORY_DIR / market
    path = directory / f"{stock_id}.csv"
    directory.mkdir(parents=True,exist_ok=True)
    LOG.info("開始 %s %s (%s) %s 至 %s",market,stock_id,stock.get("stock_name"),start,end)
    count = module.download_range(stock_id,start.year,end.year,start.month,end.month)
    if not path.exists():
        raise RuntimeError("下載器未產生 CSV 檔")
    rows = read_history_csv(path,market)
    relevant = [r for r in rows if start.isoformat() <= str(r["trade_date"]) <= end.isoformat()]
    if not relevant:
        raise RuntimeError("五年區間內沒有有效歷史行情")
    upsert_csv(conn,path,market)
    with conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*) AS n, MIN(trade_date) AS first_date,
                       MAX(trade_date) AS last_date FROM daily_prices
                       WHERE market=%s AND stock_id=%s AND trade_date BETWEEN %s AND %s""",
                    (market,stock_id,start,end))
        verified=cur.fetchone()
    if verified["n"] <= 0:
        raise RuntimeError("Neon 寫入驗證未通過")
    record_progress(conn,market,stock_id,start,end,"success",verified["n"],
                    verified["first_date"],verified["last_date"],None)
    try:
        adj=build_adjusted_stock(conn,market,stock_id)
        technical=calculate_technical_stock(conn,market,stock_id)
        smc=calculate_smc_stock(conn,market,stock_id)
        LOG.info("指標完成 %s %s: adjusted=%s technical=%s smc=%s",market,stock_id,adj,technical,smc)
    except Exception:
        LOG.exception("行情寫入已驗證，但指標重算暫時失敗 %s %s",market,stock_id)
    LOG.info("完成 %s %s: %s rows; Neon verified %s (%s-%s)",market,stock_id,count,
             verified["n"],verified["first_date"],verified["last_date"])
    return int(verified["n"])


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--batch-size",type=int,default=2,help="每次最多處理股票數，1-10")
    p.add_argument("--market",choices=["both","twse","tpex"],default="both")
    args=p.parse_args()
    if not 1<=args.batch_size<=10:
        p.error("batch-size 必須介於 1 到 10")
    url=os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL secret missing")
    start=five_year_start(date.today())
    end=target_month_end(date.today())
    universe=stock_list.build_stock_list()
    success=0; failures=[]
    with psycopg.connect(url,row_factory=dict_row,connect_timeout=20) as conn:
        sync_universe(conn,universe)
        coverage,completed=load_coverage(conn)
        batch=select_incomplete(universe,coverage,completed,args.market,start)[:args.batch_size]
        if not batch:
            LOG.info("所選市場目前沒有待回補股票。")
            return
        LOG.info("本次選取 %d 檔；市場=%s；回補範圍=%s 至 %s",len(batch),args.market,start,end)
        for idx,stock in enumerate(batch):
            market=MARKET_MAP[stock["market"]]
            sid=stock["stock_id"]
            try:
                backfill_one(conn,stock,start,end)
                success+=1
            except Exception as exc:
                LOG.exception("回補失敗 %s %s",market,sid)
                record_progress(conn,market,sid,start,end,"failed",0,None,None,str(exc)[:2000])
                failures.append(f"{market} {sid}: {exc}")
            if idx < len(batch)-1:
                time.sleep(3 if market=="twse" else 2)
    LOG.info("批次結束：成功 %d / %d；失敗 %d",success,len(batch),len(failures))
    if failures:
        raise SystemExit("部分回補失敗: "+"; ".join(failures))


if __name__=="__main__":
    main()
