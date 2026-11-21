"""TPEx verified backward-month price ladder: bounded, insert-only canary.

Starts from a stock's FIRST OBSERVED valid price month, verifies overlap with
independent saved closes, then imports at most four earlier official months.
This extends real observed dates, not listings or five-year completeness.
Manual opt-in only, at most two stocks and ten official source calls per run.
No derived factor changes, LINE, billing, orders or existing price overwrites.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from scripts import tpex_official_history_insert_only as existing
import tpex_market_data

MAX_STOCKS = 2
MAX_MONTHS = 5
MAX_SOURCE_CALLS = MAX_STOCKS * MAX_MONTHS
MIN_ANCHOR_MATCHES = 2
MAX_DB_BYTES = existing.MAX_DATABASE_BYTES

CANDIDATES_SQL = """
WITH latest_market AS (
 SELECT MAX(trade_date) AS latest_date FROM public.daily_prices WHERE close>0
), stock_history AS (
 SELECT sm.market, sm.stock_id,
        COUNT(p.trade_date) FILTER(WHERE p.close>0 AND p.volume>=0)::int valid_days,
        MIN(p.trade_date) FILTER(WHERE p.close>0 AND p.volume>=0) first_observed,
        MAX(p.trade_date) FILTER(WHERE p.close>0 AND p.volume>=0) last_observed
 FROM public.stock_master sm
 LEFT JOIN public.daily_prices p ON p.market=sm.market AND p.stock_id=sm.stock_id
 WHERE sm.market='tpex' AND sm.stock_id<>'1808'
 GROUP BY sm.market,sm.stock_id
)
SELECT h.market,h.stock_id,h.valid_days,h.first_observed,h.last_observed
FROM stock_history h CROSS JOIN latest_market lm
LEFT JOIN public.market_data_refresh_state st
 ON st.market=h.market AND st.stock_id=h.stock_id
WHERE h.valid_days BETWEEN 60 AND 999
 AND h.last_observed>=lm.latest_date-INTERVAL '7 days'
 AND h.first_observed>lm.latest_date-INTERVAL '5 years'
 AND (st.last_attempt_at IS NULL OR st.last_attempt_at<NOW()-INTERVAL '2 days')
ORDER BY h.valid_days ASC,st.last_attempt_at ASC NULLS FIRST,h.stock_id
LIMIT %s
"""

COUNTS_SQL = """
SELECT COUNT(*) FILTER(WHERE close>0 AND volume>=0)::int days,
       MIN(trade_date) FILTER(WHERE close>0 AND volume>=0) first_observed,
       MAX(trade_date) FILTER(WHERE close>0 AND volume>=0) last_observed
FROM public.daily_prices WHERE market='tpex' AND stock_id=%s
"""

ANCHOR_SQL = """
SELECT trade_date,close
FROM public.daily_prices
WHERE market='tpex' AND stock_id=%s
 AND trade_date >= %s AND trade_date < %s
 AND close>0 AND volume>=0
"""

def _month_floor(today: date) -> date:
    return date(today.year - 5, today.month, 1)


def plan_months(first_observed: date, *, today: date, months: int = MAX_MONTHS):
    if (not isinstance(first_observed,date) or not isinstance(today,date)
            or first_observed>today or type(months) is not int
            or not 1<=months<=MAX_MONTHS):
        raise ValueError("Invalid dated history ladder anchor or month cap")
    anchor=existing._month_start(first_observed)
    floor=_month_floor(today)
    if anchor<=floor:
        return []
    window=[m for m in existing.months_to_fetch(anchor,number=months)
            if m>=floor]
    if not window or window[-1]!=anchor:
        raise RuntimeError("Missing real observed anchor month")
    return window


def official_months(stock_id: str, months: list[date], *, today: date,
                    pause_seconds: float = 2):
    if (not months or len(months)>MAX_MONTHS
            or not 0<=pause_seconds<=5
            or any(m>today for m in months)):
        raise ValueError("Unbounded official history source request")
    prices=[]
    for i,month in enumerate(months):
        if i:
            time.sleep(pause_seconds)
        raw=tpex_market_data.fetch_month(stock_id,month.year,month.month)
        prices.extend(existing.validate_official_month(stock_id,month,raw,today=today))
    return prices


def verify_existing_anchor(conn, stock_id: str, month: date, bars: list[dict]):
    """Require independently stored same-month closes; reject mismatches."""
    future=existing._shift_month(month,1)
    by_day={date.fromisoformat(b["trade_date"]):Decimal(str(b["close"]))
            for b in bars if date.fromisoformat(b["trade_date"])>=month
            and date.fromisoformat(b["trade_date"])<future}
    if not by_day:
        raise ValueError("Official anchor month has no valid OHLC")
    with conn.cursor() as cur:
        cur.execute(ANCHOR_SQL,(stock_id,month,future))
        known=cur.fetchall()
    overlap=[(day,close) for day,close in known if day in by_day]
    if len(overlap)<MIN_ANCHOR_MATCHES:
        raise ValueError("Insufficient independently stored TPEx anchor closes")
    if any(Decimal(str(close))!=by_day[day] for day,close in overlap):
        raise ValueError("Official TPEx anchor close mismatch")
    return len(overlap)


def _stock_state(conn,stock_id):
    with conn.cursor() as cur:
        cur.execute(COUNTS_SQL,(stock_id,))
        row=cur.fetchone()
    return dict(row)


def _select(conn,limit):
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL,(limit,))
        return [dict(x) for x in cur.fetchall()]


def run(url: str, *, apply=False, limit=2, months=5,
        today=None, pause_seconds=2, report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    if type(limit) is not int or not 1<=limit<=MAX_STOCKS:
        raise ValueError("Only two bounded TPEx stocks per canary")
    if type(months) is not int or not 1<=months<=MAX_MONTHS or limit*months>MAX_SOURCE_CALLS:
        raise ValueError("Unsafe TPEx official monthly request count")
    if apply and os.environ.get("STOCK_TPEX_LONG_HISTORY_ENABLED")!="yes":
        raise PermissionError("Independent TPEx long-history apply gate required")
    today=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    records=[]
    calls=0
    with psycopg.connect(url,autocommit=True,connect_timeout=15,row_factory=dict_row) as conn:
        existing._size_guard(conn)
        stocks=_select(conn,limit)
        for stock in stocks:
            window=plan_months(stock["first_observed"],today=today,months=months)
            record={"market":"tpex","stock_id":stock["stock_id"],
                    "valid_days_before":stock["valid_days"],
                    "first_observed_before":stock["first_observed"].isoformat(),
                    "months_to_request":[x.strftime("%Y-%m") for x in window],
                    "status":"dry_run","new_valid_days":0}
            if apply and window:
                # A capacity stop must abort the run, not silently proceed to
                # another stock. Per-stock transaction rolls back on guard fail.
                existing._size_guard(conn)
                try:
                    raw=official_months(stock["stock_id"],window,today=today,
                                        pause_seconds=pause_seconds)
                    calls+=len(window)
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute("SET LOCAL statement_timeout='20000ms'")
                        before=_stock_state(conn,stock["stock_id"])
                        if (before["days"]!=stock["valid_days"] or
                                before["first_observed"]!=stock["first_observed"]):
                            raise ValueError("Concurrent stock price history change")
                        matches=verify_existing_anchor(conn,stock["stock_id"],window[-1],raw)
                        with conn.cursor() as cur:
                            if raw:
                                cur.executemany(existing.PRICE_INSERT_ONLY_SQL,raw)
                        after=_stock_state(conn,stock["stock_id"])
                        if (after["days"]<before["days"] or
                            after["last_observed"]!=before["last_observed"] or
                            (after["days"]>before["days"] and
                             after["first_observed"]>=before["first_observed"])):
                            raise RuntimeError("Unexpected historical date growth")
                        existing._size_guard(conn)
                        growth=after["days"]-before["days"]
                        existing._state(conn,stock["stock_id"],
                                        "success" if growth else "failed",
                                        stock["last_observed"],len(raw),
                                        None if growth else "NO_EARLIER_OFFICIAL_BARS")
                    record.update({"status":"new_official_history" if growth else "no_growth",
                                   "new_valid_days":growth,"valid_days_after":after["days"],
                                   "first_observed_after":after["first_observed"].isoformat(),
                                   "matching_anchor_closes":matches})
                except Exception as exc:
                    # Do not mark the entire stock cohort verified. A refused
                    # stock is safe to retry after the existing two-day cooldown.
                    with conn.transaction():
                        existing._state(conn,stock["stock_id"],"failed",
                                        stock["last_observed"],0,type(exc).__name__)
                    record.update({"status":"failed","error_type":type(exc).__name__})
            records.append(record)
    report={"schema_version":1,"scope":"TPEX_BACKWARD_OFFICIAL_MONTHLY_PRICES",
            "date":today.isoformat(),"apply":bool(apply),"stocks_selected":len(records),
            "max_stocks":MAX_STOCKS,"max_months_each":MAX_MONTHS,
            "source_calls_actual":calls if apply else 0,
            "new_valid_days":sum(x["new_valid_days"] for x in records),
            "existing_price_keys_overwritten":False,
            "complete_five_year_official_history_verified":False,
            "model_retrained":False,"LINE_or_trading_enabled":False,
            "paid_upgrade_requested":False,"stocks":records}
    if report_path:
        dest=Path(report_path)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    a=argparse.ArgumentParser(description="Bounded TPEx official backward month canary")
    a.add_argument("--apply",action="store_true")
    a.add_argument("--limit",type=int,default=2)
    a.add_argument("--months",type=int,default=5)
    a.add_argument("--report",type=Path,default=Path("tpex-long-history-canary.json"))
    args=a.parse_args()
    result=run(os.getenv("DATABASE_URL",""),apply=args.apply,limit=args.limit,
               months=args.months,report_path=args.report)
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
