"""Five-year TPEx official dated MARKET-WIDE source-only backfill.

Finish missing *price keys* before recalculating historical derived features.
Only official market days with >=10 independently stored same-date closes.
INSERT ... ON CONFLICT DO NOTHING, no existing OHLCV, score or LINE mutations.

An unattended job is resumable because already imported official-dated days
are excluded. Abort on errors and free-tier limits; never backfill a guessed day.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import psycopg

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from official_snapshot_ingest import load_allowed,select_candidates,write_missing
from tpex_dated_history import fetch_day,verify_source_date

MAX_DATES=1250
MAX_DB_BYTES=800_000_000
SAFE_DAY_BYTES=5_000_000
MAX_FAILURES=3
MIN_ANCHORS=10
MIN_OFFICIAL_COHORT=500
MIN_PAUSE_SECONDS=1.0
MAX_PAUSE_SECONDS=10.0

# Deliberately count all currently known date anchors, not calendar weekdays.
# Holidays have no independent observations and are NEVER fabricated.
DATE_CANDIDATES_SQL="""
WITH day_counts AS (
 SELECT trade_date,
  COUNT(*) FILTER(WHERE close>0 AND volume>=0)::int AS valid_count,
  COUNT(*) FILTER(WHERE source='TPEX_DATED_OTC_EW')::int AS official_dated
 FROM public.daily_prices
 WHERE market='tpex' AND trade_date>=%s AND trade_date<=%s
 GROUP BY trade_date
)
SELECT trade_date,valid_count,official_dated
FROM day_counts
WHERE valid_count>=10
 AND valid_count<%s
 AND official_dated<%s
ORDER BY trade_date DESC
LIMIT %s
"""
SIZE_SQL="SELECT pg_database_size(current_database())::bigint"
DATE_PRICE_SQL="""SELECT COUNT(*)::int FROM public.daily_prices
WHERE market='tpex' AND trade_date=%s"""

def floor_five_years(ending:date) -> date:
    if not isinstance(ending,date):
        raise ValueError("Invalid official last market date")
    try:
        return ending.replace(year=ending.year-5)
    except ValueError:
        return ending.replace(year=ending.year-5,day=28)

def ensure_size(conn):
    with conn.cursor() as cur:
        cur.execute(SIZE_SQL)
        size=cur.fetchone()[0]
    if type(size) is not int or size<1 or size+SAFE_DAY_BYTES>=MAX_DB_BYTES:
        raise RuntimeError("Neon Free guard: preserve >=5MB headroom under 800MB")
    return size

def select_sparse_days(conn, *, last_day:date,allowed_count:int,max_days:int):
    if type(max_days) is not int or not 1<=max_days<=MAX_DATES:
        raise ValueError("Unsafe official daily request count")
    if type(allowed_count) is not int or allowed_count<700:
        raise RuntimeError("TPEx stock_master universe is too small")
    cutoff=max(MIN_OFFICIAL_COHORT, int(allowed_count*.8))
    first=floor_five_years(last_day)
    with conn.cursor() as cur:
        cur.execute(DATE_CANDIDATES_SQL,
                    (first,last_day,cutoff,MIN_OFFICIAL_COHORT,max_days))
        rows=cur.fetchall()
    chosen=[{"trade_date":d,"saved_closes":valid,"previous_official":official}
            for d,valid,official in rows]
    if (len(chosen)>max_days or
        len({x["trade_date"] for x in chosen})!=len(chosen) or
        any(x["trade_date"]<first or x["trade_date"]>last_day
            or x["saved_closes"]<MIN_ANCHORS for x in chosen)):
        raise RuntimeError("Invalid proposed five-year official source days")
    return chosen

def verified_source_bars(conn,day,allowed,*,fetcher=fetch_day):
    snapshot=fetcher(day)
    if not isinstance(snapshot,dict) or "bars" not in snapshot:
        raise ValueError("Official TPEx whole-market payload missing actual bars")
    minimum=max(MIN_OFFICIAL_COHORT,int(sum(m=="tpex" for m,s in allowed)*.6))
    permitted=select_candidates(snapshot["bars"],allowed,minimum=minimum)
    proof=verify_source_date(conn,day,permitted)
    if proof["compared"]<MIN_ANCHORS or proof["matched"]*100<98*proof["compared"]:
        raise ValueError("Insufficient old-date independent official market close proof")
    return permitted,proof

def get_latest_day(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(trade_date) FROM public.daily_prices WHERE market='tpex' AND close>0")
        day=cur.fetchone()[0]
    if day is None:
        raise RuntimeError("No TPEx latest session")
    return day

def report_to(path,data):
    if path is not None:
        target=Path(path)
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_suffix(target.suffix+".tmp")
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
        temp.replace(target)

def run(url,*,apply=False,max_days=10,pause_seconds=2.0,
        report_path=None,fetcher=fetch_day):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    if type(max_days) is not int or not 1<=max_days<=MAX_DATES:
        raise ValueError("Batch request count must be in 1..1250")
    if not MIN_PAUSE_SECONDS<=pause_seconds<=MAX_PAUSE_SECONDS:
        raise ValueError("Unsafe TPEx source request spacing")
    if apply and (
        os.environ.get("STOCK_TPEX_FIVE_YEAR_SOURCE_WRITE_ENABLED")!="yes" or
        os.environ.get("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED")!="yes"
    ):
        raise PermissionError("Two explicit official-source write gates required")
    result={"schema_version":1,
            "scope":"TPEX_FIVE_YEAR_REAL_DATED_MARKET_OHLCV_INSERT_ONLY",
            "as_of_utc":datetime.now(ZoneInfo("UTC")).isoformat(),
            "apply":bool(apply),"source_requests":0,"max_requests":max_days,
            "date_anchors_checked":0,"verified_days":0,
            "new_price_rows":0,"failures":[],
            "processed_dates":[],
            "unprocessed_dates":None,
            "full_five_year_official_history_verified":False,
            "all_historical_derived_factors_recalculated":False,
            "raw_existing_price_keys_overwritten":False,
            "LINE_messages_sent":False,"orders_enabled":False,
            "paid_plan_requested":False}
    report_to(report_path,result)
    with psycopg.connect(url,connect_timeout=20,autocommit=True) as conn:
        before=ensure_size(conn)
        allowed=load_allowed(conn)
        actual={code for market,code in allowed if market=="tpex"}
        last_day=get_latest_day(conn)
        if last_day>datetime.now(ZoneInfo("Asia/Taipei")).date():
            raise RuntimeError("Future-dated TPEx price rows are not eligible")
        chosen=select_sparse_days(conn,last_day=last_day,
                                  allowed_count=len(actual),max_days=max_days)
        result["last_market_session"]=last_day.isoformat()
        result["five_year_floor"]=floor_five_years(last_day).isoformat()
        result["source_universe_size"]=len(actual)
        result["database_bytes_before"]=before
        result["preview_dates"]=[x["trade_date"].isoformat() for x in chosen[:12]]
        result["candidate_dates_in_this_batch"]=len(chosen)
        report_to(report_path,result)
        if not apply:
            return result
        # Validate each source response BEFORE any official price insert.
        for entry in chosen:
            day=entry["trade_date"]
            observed={"date":day.isoformat(),"stored_before":entry["saved_closes"],
                      "previous_official":entry["previous_official"],"status":"started"}
            try:
                ensure_size(conn)
                result["source_requests"]+=1
                bars,proof=verified_source_bars(conn,day,allowed,fetcher=fetcher)
                result["date_anchors_checked"]+=1
                # Captured fact rows are for exactly the requested day.
                if any(x["market"]!="tpex" or x["trade_date"]!=day for x in bars):
                    raise RuntimeError("Mixed market/dates in official source")
                inserted=write_missing(conn,"tpex",day,bars)
                after=ensure_size(conn)
                observed.update({"status":"verified","qualified":len(bars),
                                 "inserted":inserted,"same_day_closes":proof["compared"],
                                 "close_matches":proof["matched"],
                                 "close_mismatches":proof["mismatched"],
                                 "database_bytes_after":after})
                result["verified_days"]+=1
                result["new_price_rows"]+=inserted
            except Exception as ex:
                observed.update({"status":"rejected","error_type":type(ex).__name__})
                result["failures"].append({"date":day.isoformat(),
                                          "error_type":type(ex).__name__})
                # Respect TPEx server; do not flood invalid/blocked requests.
                if len(result["failures"])>=MAX_FAILURES:
                    result["processed_dates"].append(observed)
                    report_to(report_path,result)
                    raise RuntimeError(">=3 invalid TPEx historical source dates; stop safely") from ex
            result["processed_dates"].append(observed)
            report_to(report_path,result)
            print(json.dumps({"official_day":day.isoformat(),
                "status":observed["status"],"inserted":observed.get("inserted",0),
                "verified_days":result["verified_days"],
                "database_bytes_after":observed.get("database_bytes_after")}),
                flush=True)
            if pause_seconds:
                time.sleep(pause_seconds)
        result["database_bytes_after"]=ensure_size(conn)
        # A one-shot batch may leave unprocessed dates; make this visible.
        remaining=select_sparse_days(conn,last_day=last_day,
                                      allowed_count=len(actual),max_days=MAX_DATES)
        result["unprocessed_dates"]=len(remaining)
        result["complete_source_date_coverage"]=not remaining and not result["failures"]
        report_to(report_path,result)
    return result

def main():
    p=argparse.ArgumentParser(description="Strict official TPEx 5-year all-market backfill")
    p.add_argument("--apply",action="store_true")
    p.add_argument("--max-days",type=int,default=10)
    p.add_argument("--pause-seconds",type=float,default=2.0)
    p.add_argument("--report",type=Path,default=Path("tpex-five-year-market-batch.json"))
    args=p.parse_args()
    r=run(os.getenv("DATABASE_URL",""),apply=args.apply,
          max_days=args.max_days,pause_seconds=args.pause_seconds,
          report_path=args.report)
    print(json.dumps({k:v for k,v in r.items()
        if k in ("scope","apply","source_requests","verified_days",
                 "new_price_rows","candidate_dates_in_this_batch",
                 "unprocessed_dates","complete_source_date_coverage",
                 "full_five_year_official_history_verified","database_bytes_after")},
        ensure_ascii=False))
    if args.apply and (r["candidate_dates_in_this_batch"]==0
                      or r["verified_days"]!=r["candidate_dates_in_this_batch"]):
        raise SystemExit("TPEx five-year source batch incomplete; inspect evidence")

if __name__=="__main__":
    main()
