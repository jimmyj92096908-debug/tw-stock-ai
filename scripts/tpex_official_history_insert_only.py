"""Free-tier, insert-only verified TPEx official monthly history enrichment.

Never calls db_storage.upsert_csv: its ON CONFLICT UPDATE can overwrite prices.
Strict hard cap: 1..10 TPEx stocks, <=5 official monthly requests per stock.
All writes are either NEW daily_prices keys or refresh-state metadata.
Running is explicit (--apply + env gate); offline CI has no Neon access.
"""
from __future__ import annotations

import argparse
from datetime import date,datetime
import json
import logging
import math
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import tpex_market_data  # noqa: E402

LOG=logging.getLogger(__name__)
MAX_STOCKS=10
MAX_MONTHS=5
MAX_MONTHLY_SOURCE_CALLS=50
MAX_MONTHLY_ROWS=120
MAX_DATABASE_BYTES=800_000_000
MIN_PRICE_HISTORY=60

CANDIDATES_SQL="""
WITH history AS (
 SELECT sm.market,sm.stock_id,sm.stock_name,
        COUNT(p.trade_date) FILTER(WHERE p.close>0)::int AS valid_days,
        MAX(p.trade_date) FILTER(WHERE p.close>0) AS newest
 FROM public.stock_master sm
 LEFT JOIN public.daily_prices p ON
    sm.market=p.market AND sm.stock_id=p.stock_id
 WHERE sm.market='tpex' AND sm.stock_id<>'1808'
 GROUP BY sm.market,sm.stock_id,sm.stock_name
)
SELECT h.market,h.stock_id,h.stock_name,h.valid_days,h.newest
FROM history h LEFT JOIN public.market_data_refresh_state st
ON st.market=h.market AND st.stock_id=h.stock_id
WHERE h.valid_days BETWEEN 1 AND 59
  AND (st.last_attempt_at IS NULL OR st.last_attempt_at< NOW()-INTERVAL '2 days')
ORDER BY st.last_attempt_at ASC NULLS FIRST,h.valid_days ASC,h.stock_id
LIMIT %s
"""

SIZE_SQL="SELECT pg_database_size(current_database())::bigint AS bytes"
COUNT_SQL="""
SELECT COUNT(*) FILTER(WHERE close>0)::int AS valid_days
FROM public.daily_prices WHERE market='tpex' AND stock_id=%s
"""

# Never change this to ON CONFLICT ... DO UPDATE.
PRICE_INSERT_ONLY_SQL="""
INSERT INTO public.daily_prices
(market,stock_id,trade_date,open,high,low,close,volume,turnover,
 price_change,transactions,source)
VALUES
(%(market)s,%(stock_id)s,%(trade_date)s,%(open)s,%(high)s,%(low)s,
 %(close)s,%(volume)s,%(turnover)s,%(change)s,%(transactions)s,%(source)s)
ON CONFLICT (market,stock_id,trade_date) DO NOTHING
"""

STATE_SQL="""
INSERT INTO public.market_data_refresh_state
(market,stock_id,last_attempt_at,last_status,latest_trade_date,
 rows_downloaded,error_message,updated_at)
VALUES ('tpex',%s,NOW(),%s,%s,%s,%s,NOW())
ON CONFLICT (market,stock_id) DO UPDATE SET
 last_attempt_at=NOW(),last_status=EXCLUDED.last_status,
 latest_trade_date=EXCLUDED.latest_trade_date,
 rows_downloaded=EXCLUDED.rows_downloaded,
 error_message=EXCLUDED.error_message,updated_at=NOW()
"""


def _month_start(day: date)->date:
    return date(day.year,day.month,1)


def _shift_month(day: date,delta: int)->date:
    m=day.year*12+day.month-1+delta
    return date(m//12,m%12+1,1)


def months_to_fetch(today: date,*,number=MAX_MONTHS):
    if not isinstance(today,date) or type(number) is not int or not 1<=number<=MAX_MONTHS:
        raise ValueError("Source request months must be bounded and anchored")
    month=_month_start(today)
    return [_shift_month(month,i) for i in range(1-number,1)]


def _valid(value,name,*,nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
        raise ValueError("Invalid nonnegative official field: "+name)
    return value


def validate_official_month(stock_id,month,rows,*,today):
    """Reject wrong ticker/date, duplicate OHLC, and implausible source rows."""
    if not isinstance(stock_id,str) or len(stock_id)!=4 or not stock_id.isdigit():
        raise ValueError("Invalid TPEx stock id")
    if not isinstance(month,date) or not isinstance(today,date):
        raise ValueError("Invalid official source month")
    if not isinstance(rows,list) or len(rows)>MAX_MONTHLY_ROWS:
        raise ValueError("Unbounded or invalid official monthly response")
    accepted=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or row.get("stock_id")!=stock_id or row.get("source")!="TPEX_TRADING_STOCK":
            raise ValueError("Mismatched official market source")
        d=row.get("trade_date")
        if not isinstance(d,str) or len(d)!=10:
            raise ValueError("Missing official source trade date")
        day=date.fromisoformat(d)
        if (day.year,day.month)!=(month.year,month.month) or day>today:
            raise ValueError("Official trade date mismatched requested month or future")
        if day in seen:
            raise ValueError("Duplicate trade date in official source")
        seen.add(day)
        o,h,l,c=[_valid(row.get(k),k,nullable=True) for k in ("open","high","low","close")]
        # A non-traded source row is not a true price history observation.
        if c is None or c<=0:
            continue
        if any(x is None or x<=0 for x in (o,h,l)) or h<max(o,c) or l>min(o,c):
            raise ValueError("Invalid official OHLC; refusing stock import")
        v=_valid(row.get("volume"),"volume",nullable=True)
        turnover=_valid(row.get("turnover"),"turnover",nullable=True)
        trans=_valid(row.get("transactions"),"transactions",nullable=True)
        change=row.get("change")
        if change is not None:
            if isinstance(change,bool) or not isinstance(change,(int,float)) or not math.isfinite(change):
                raise ValueError("Invalid official close change")
        accepted.append({
            "market":"tpex","stock_id":stock_id,"trade_date":d,
            "open":o,"high":h,"low":l,"close":c,
            "volume":v,"turnover":turnover,
            "change":change,"transactions":trans,
            "source":"TPEX_TRADING_STOCK",
        })
    return accepted


def fetch_verified_history(stock_id,*,today,months=MAX_MONTHS,pause_seconds=2.0):
    if not 0<=pause_seconds<=5:
        raise ValueError("Unsafe TPEx official request pause")
    records=[]
    for i,month in enumerate(months_to_fetch(today,number=months)):
        if i:
            time.sleep(pause_seconds)
        source=tpex_market_data.fetch_month(stock_id,month.year,month.month)
        records.extend(validate_official_month(stock_id,month,source,today=today))
    return sorted(records,key=lambda x:x["trade_date"])


def select_candidates(conn,limit):
    if type(limit) is not int or not 1<=limit<=MAX_STOCKS:
        raise ValueError("TPEx daily selected-stock limit must be 1..10")
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL,(limit,))
        return [dict(x) for x in cur.fetchall()]


def _size_guard(conn):
    with conn.cursor() as cur:
        cur.execute(SIZE_SQL)
        n=cur.fetchone()["bytes"]
    if type(n) is not int or not 0<=n<MAX_DATABASE_BYTES:
        raise RuntimeError("Neon free storage guard reached; stop without upgrades")
    return n


def _count(conn,stock_id):
    with conn.cursor() as cur:
        cur.execute(COUNT_SQL,(stock_id,))
        return cur.fetchone()["valid_days"]


def _state(conn,stock_id,status,last_day,rows_downloaded,error):
    with conn.cursor() as cur:
        cur.execute(STATE_SQL,(stock_id,status,last_day,rows_downloaded,error))


def run(url,*,apply=False,limit=2,months=MAX_MONTHS,
        pause_seconds=2.0,today=None,report_path=None):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    if type(limit) is not int or not 1<=limit<=MAX_STOCKS:
        raise ValueError("Unsafe request stock cap")
    if type(months) is not int or not 1<=months<=MAX_MONTHS or limit*months>MAX_MONTHLY_SOURCE_CALLS:
        raise ValueError("More than 50 official monthly requests are prohibited")
    if apply and os.environ.get("STOCK_TPEX_INSERT_ONLY_HISTORY_ENABLED")!="yes":
        raise PermissionError("Explicit owner-authorized history insert-only gate required")
    today=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    results=[]
    with psycopg.connect(url,autocommit=True,connect_timeout=15,row_factory=dict_row) as conn:
        size=_size_guard(conn)
        selected=select_candidates(conn,limit)
        for item in selected:
            row={"market":"tpex","stock_id":item["stock_id"],
                 "valid_days_before":item["valid_days"],
                 "status":"dry-run","requested_source_months":months}
            if apply:
                try:
                    official=fetch_verified_history(item["stock_id"],today=today,
                                                    months=months,pause_seconds=pause_seconds)
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute("SET LOCAL statement_timeout = '20000ms'")
                            prior=_count(conn,item["stock_id"])
                            if prior!=item["valid_days"]:
                                raise RuntimeError("Source stock price changed during selected batch")
                            if official:
                                cur.executemany(PRICE_INSERT_ONLY_SQL,official)
                            after=_count(conn,item["stock_id"])
                            if after<prior:
                                raise RuntimeError("Verified positive price history regressed")
                            status="success" if after>prior else "failed"
                            error=None if after>prior else "NO_VERIFIED_NEW_PRICES"
                            _state(conn,item["stock_id"],status,item["newest"],
                                   len(official),error)
                    row.update({
                        "status":"new_official_history" if after>prior else "no_verified_new_prices",
                        "source_price_rows":len(official),
                        "valid_days_after":after,
                        "new_valid_days":after-prior,
                        "new_60_session_eligible":prior<MIN_PRICE_HISTORY<=after,
                    })
                except Exception as exc:
                    LOG.warning("Official TPEx stock import refused: %s (%s)",item["stock_id"],type(exc).__name__)
                    with conn.transaction():
                        _state(conn,item["stock_id"],"failed",item["newest"],0,
                               type(exc).__name__)
                    row.update({"status":"failed","error_type":type(exc).__name__})
                # Every selected stock is eligible for gradual rotation only
                # after its own source/reconciliation attempt finishes.
            results.append(row)
        if apply:
            _size_guard(conn)
    report={
        "schema_version":1,"research_history_source":"TPEx official monthly tradingStock",
        "date":today.isoformat(),"selected":len(selected),
        "max_stocks":MAX_STOCKS,"max_monthly_requests":MAX_MONTHLY_SOURCE_CALLS,
        "month_count":months,
        "new_price_stocks":sum(x["status"]=="new_official_history" for x in results),
        "new_60_session_stocks":sum(x.get("new_60_session_eligible",False) for x in results),
        "rejected":sum(x["status"]=="failed" for x in results),
        "no_growth":sum(x["status"]=="no_verified_new_prices" for x in results),
        "baseline_database_bytes":size,
        "price_existing_keys_overwritten":False,
        "no_synthetic_prices":True,
        "not_claimed_full_market_100pct":True,
        "paid_upgrade_requested":False,
        "line_messages_sent":False,"trading_enabled":False,
        "stocks":results
    }
    if report_path:
        path=Path(report_path)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser(description="No-overwrite bounded official TPEx monthly history")
    p.add_argument("--apply",action="store_true")
    p.add_argument("--limit",type=int,default=2)
    p.add_argument("--months",type=int,default=5)
    p.add_argument("--report",type=Path,default=Path("tpex-official-history-evidence.json"))
    a=p.parse_args()
    result=run(os.environ.get("DATABASE_URL",""),apply=a.apply,limit=a.limit,
               months=a.months,report_path=a.report)
    print(json.dumps({k:result[k] for k in ("selected","new_price_stocks","new_60_session_stocks",
          "rejected","no_growth","price_existing_keys_overwritten","paid_upgrade_requested")},
          ensure_ascii=False))
    if result["rejected"]:
        raise SystemExit("At least one official source failed validation; inspect evidence")


if __name__=="__main__":
    main()
