"""One-time gated research coverage catch-up to 100% of *currently eligible* stocks.

This is NOT a promise of 100% of the official stock list: stocks without 60
verified positive closes, with stale/nonexistent prices, or the deliberately
excluded symbol 1808 are not in this eligible group. The job never fabricates
prices, writes raw prices, touches LINE or enables trading.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from batch_indicator_catchup import run as indicator_run  # noqa: E402
from composite_score import calculate_all  # noqa: E402

MAX_ROUNDS=9
MAX_PER_MARKET=20
MIN_PRICE_DAYS=60
MAX_DATABASE_BYTES=800_000_000

SNAPSHOT_SQL="""
WITH priced AS (
 SELECT market,stock_id,COUNT(*) FILTER(WHERE close>0)::int AS valid_days,
        MAX(trade_date) FILTER (WHERE close>0) AS last_valid
 FROM public.daily_prices GROUP BY market,stock_id
), latest AS (
 SELECT MAX(trade_date) AS latest_valid FROM public.daily_prices WHERE close>0
), eligible AS (
 SELECT p.market,p.stock_id,p.last_valid
 FROM priced p CROSS JOIN latest l
 WHERE p.stock_id<>'1808' AND p.valid_days>=60
   AND p.last_valid >= l.latest_valid-INTERVAL '7 days'
), coverage AS (
 SELECT e.market,e.stock_id,
 EXISTS(SELECT 1 FROM public.daily_technicals t WHERE
    t.market=e.market AND t.stock_id=e.stock_id
    AND t.trade_date=e.last_valid) AS technical,
 EXISTS(SELECT 1 FROM public.daily_smc s WHERE
    s.market=e.market AND s.stock_id=e.stock_id
    AND s.trade_date=e.last_valid) AS smc,
 EXISTS(SELECT 1 FROM public.daily_composite_scores c WHERE
    c.market=e.market AND c.stock_id=e.stock_id
    AND c.as_of_date=e.last_valid AND c.total_score IS NOT NULL) AS scored
 FROM eligible e
)
SELECT
 (SELECT COUNT(*)::int FROM public.stock_master) AS stock_master_total,
 (SELECT COUNT(*)::bigint FROM public.daily_prices) AS raw_price_rows,
 (SELECT MAX(trade_date) FROM public.daily_prices WHERE close>0) AS latest_price_date,
 (SELECT pg_database_size(current_database())::bigint) AS database_bytes,
 COUNT(*)::int AS eligible,
 COUNT(*) FILTER(WHERE technical)::int AS technical_current,
 COUNT(*) FILTER(WHERE smc)::int AS smc_current,
 COUNT(*) FILTER(WHERE technical AND smc)::int AS both_current,
 COUNT(*) FILTER(WHERE scored)::int AS scored_current,
 COUNT(*) FILTER(WHERE technical AND smc AND scored)::int AS matched_current
FROM coverage
"""


def snapshot(url: str) -> dict:
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '20000ms'")
                cur.execute(SNAPSHOT_SQL)
                data=dict(cur.fetchone())
    data["latest_price_date"]=str(data["latest_price_date"]) if data["latest_price_date"] else None
    # JSON numbers for psycopg int8 are ordinary Python int values.
    for key in ("stock_master_total","raw_price_rows","database_bytes","eligible",
                "technical_current","smc_current","both_current","scored_current","matched_current"):
        v=data.get(key)
        if type(v) is not int or v<0:
            raise RuntimeError("Invalid verified count: "+key)
    if data["stock_master_total"]<=0 or data["eligible"]<=0 or not data["latest_price_date"]:
        raise RuntimeError("No verifiable eligible research group")
    if data["database_bytes"]>=MAX_DATABASE_BYTES:
        raise RuntimeError("Database approaching free storage guard; no further writes")
    if any(data[k]>data["eligible"] for k in ("technical_current","smc_current",
          "both_current","scored_current","matched_current")):
        raise RuntimeError("Invalid same-date eligible stock subset")
    if data["matched_current"]>min(data["both_current"],data["scored_current"]):
        raise RuntimeError("Invalid matching cohort")
    return data


def unchanged_market_data(before,after):
    for key in ("stock_master_total","raw_price_rows","latest_price_date","eligible"):
        if before[key]!=after[key]:
            raise RuntimeError("Raw market data / eligible population changed mid-run: "+key)
    if after["database_bytes"]>=MAX_DATABASE_BYTES:
        raise RuntimeError("Database free-storage ceiling reached; refusing further work")
    for key in ("technical_current","smc_current","both_current","scored_current","matched_current"):
        if after[key]<before[key]:
            raise RuntimeError("Analysis data coverage regressed: "+key)


def save(path,content):
    if not path:
        return
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(content,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)


def execute(url,*,apply=False,max_rounds=0,report_path=None):
    if type(max_rounds) is not int or not 0<=max_rounds<=MAX_ROUNDS:
        raise ValueError("Unsafe batch round count")
    if apply and (max_rounds<1 or
                  os.environ.get("STOCK_ELIGIBLE_100_COVERAGE_WRITE_ENABLED")!="yes" or
                  os.environ.get("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED")!="yes"):
        raise ValueError("Both owner-approved production write gates required")
    before=snapshot(url)
    report={
        "schema_version":1,"scope":"CURRENT_RECENT_60_SESSION_ELIGIBLE_STOCKS_ONLY",
        "not_all_1991_master_stocks":True,
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
        "baseline":before,"latest":before,"rounds":[],
        "indicator_writes_attempted":False,"score_rebuild_attempted":False,
        "eligible_complete":before["matched_current"]==before["eligible"],
        "raw_prices_modified":False,"line_messages_sent":False,
        "trading_approved":False,"paid_upgrade_requested":False,
    }
    save(report_path,report)
    if not apply:
        return report
    previous=before
    while previous["both_current"]<before["eligible"] and len(report["rounds"])<max_rounds:
        results=indicator_run(url,apply=True,per_market=MAX_PER_MARKET)
        report["indicator_writes_attempted"]=True
        failed=[r for r in results if r["status"]=="failed"]
        verified=sum(r["status"]=="verified" for r in results)
        current=snapshot(url)
        unchanged_market_data(previous,current)
        round_evidence={
            "round":len(report["rounds"])+1,
            "selected":len(results),"verified":verified,"failed":len(failed),
            "both_before":previous["both_current"],
            "both_after":current["both_current"],
            "matched_after":current["matched_current"],
        }
        report["rounds"].append(round_evidence)
        report["latest"]=current
        save(report_path,report)
        if failed or not verified or current["both_current"]<=previous["both_current"]:
            raise RuntimeError("Bounded indicator batch failed or did not increase coverage")
        previous=current
    if previous["both_current"]<before["eligible"]:
        raise RuntimeError("Hard round ceiling before 100% of currently eligible indicators")

    if previous["matched_current"]<before["eligible"]:
        report["score_rebuild_attempted"]=True
        save(report_path,report)
        report["score_rows_processed"]=calculate_all(url)
        final=snapshot(url)
        unchanged_market_data(previous,final)
        report["latest"]=final
    else:
        final=previous

    report["eligible_complete"]=(
        final["both_current"]==before["eligible"] and
        final["scored_current"]==before["eligible"] and
        final["matched_current"]==before["eligible"]
    )
    save(report_path,report)
    if not report["eligible_complete"]:
        raise RuntimeError("100% eligible same-stock matched composite coverage not verified")
    return report


def main():
    p=argparse.ArgumentParser(description="Guarded 100% currently-eligible research coverage")
    p.add_argument("--apply",action="store_true")
    p.add_argument("--max-rounds",type=int,default=0)
    p.add_argument("--report",type=Path,default=Path("eligible-100-evidence.json"))
    a=p.parse_args()
    out=execute(os.environ.get("DATABASE_URL",""),apply=a.apply,
                max_rounds=a.max_rounds,report_path=a.report)
    cur=out["latest"]
    print(json.dumps({"scope":out["scope"],"eligible":cur["eligible"],
                      "matched":cur["matched_current"],
                      "100pct_eligible_verified":out["eligible_complete"],
                      "paid_upgrade_requested":False,
                      "not_all_1991_master_stocks":True},ensure_ascii=False))


if __name__=="__main__":
    main()
