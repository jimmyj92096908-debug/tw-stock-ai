"""Guarded TWSE 240-session derived indicators and research-only score refresh.

After independently sourced TWSE history reaches genuine 240-session depth,
refresh adjusted/technical/SMC for at most 20 TWSE stocks per round, and then
recompute ONLY latest research scores for that verified cohort (10 per batch).
No raw OHLCV writes, paid service, LINE messages or trading signals.
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
from batch_indicator_catchup import run as indicator_run
from composite_score import calculate_all

MIN_240_COHORT=500
MIN_VERIFIED_DAYS=240
MAX_ROUNDS=60
MAX_SCORE_BATCHES=120
SCORE_BATCH_SIZE=10
MAX_DATABASE_BYTES=800_000_000

STATE_SQL="""
WITH priced AS (
 SELECT stock_id,
    count(*) FILTER(WHERE close>0 AND volume>=0)::int valid_days,
    max(trade_date) FILTER(WHERE close>0 AND volume>=0) latest_close
 FROM public.daily_prices WHERE market='twse' AND stock_id<>'1808'
 GROUP BY stock_id
), market_latest AS (
 SELECT max(trade_date) max_day FROM public.daily_prices WHERE close>0
), eligible AS (
 SELECT p.stock_id,p.latest_close FROM priced p,market_latest m
 WHERE p.valid_days>=240 AND p.latest_close>=m.max_day-interval '7 days'
), checked AS (
 SELECT e.stock_id,e.latest_close,
    EXISTS(SELECT 1 FROM public.daily_technicals t WHERE t.market='twse'
      AND t.stock_id=e.stock_id AND t.trade_date=e.latest_close) tech,
    EXISTS(SELECT 1 FROM public.daily_smc s WHERE s.market='twse'
      AND s.stock_id=e.stock_id AND s.trade_date=e.latest_close) smc,
    EXISTS(SELECT 1 FROM public.daily_composite_scores c WHERE c.market='twse'
      AND c.stock_id=e.stock_id AND c.as_of_date=e.latest_close
      AND c.total_score IS NOT NULL) score
 FROM eligible e
)
SELECT (SELECT count(*)::bigint FROM public.daily_prices WHERE market='twse')
      AS raw_twse_rows,
       (SELECT count(DISTINCT trade_date)::int FROM public.daily_prices
        WHERE market='twse' AND source='TWSE_MI_INDEX_ALLBUT0999')
      AS verified_source_days,
       (SELECT pg_database_size(current_database())::bigint) database_bytes,
       count(*)::int eligible,
       count(*) FILTER(WHERE tech AND smc)::int current_indicators,
       count(*) FILTER(WHERE tech AND smc AND score)::int current_scores
FROM checked
"""

SCORE_PAGE_SQL="""
WITH priced AS (
 SELECT stock_id,count(*) FILTER(WHERE close>0 AND volume>=0)::int history_days,
        max(trade_date) FILTER(WHERE close>0 AND volume>=0) last_price
 FROM public.daily_prices WHERE market='twse' AND stock_id<>'1808'
 GROUP BY stock_id
), newest AS (
 SELECT max(trade_date) max_day FROM public.daily_prices WHERE close>0
)
SELECT 'twse' AS market,p.stock_id
FROM priced p,newest n
WHERE p.history_days>=240 AND p.last_price>=n.max_day-interval '7 days'
 AND EXISTS(SELECT 1 FROM public.daily_technicals t
    WHERE t.market='twse' AND t.stock_id=p.stock_id
      AND t.trade_date=p.last_price)
 AND EXISTS(SELECT 1 FROM public.daily_smc s
    WHERE s.market='twse' AND s.stock_id=p.stock_id
      AND s.trade_date=p.last_price)
ORDER BY p.stock_id LIMIT %s OFFSET %s
"""


def capture(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        data=dict(conn.execute(STATE_SQL).fetchone())
    for k in ("raw_twse_rows","verified_source_days","database_bytes",
              "eligible","current_indicators","current_scores"):
        if type(data.get(k)) is not int or data[k]<0:
            raise RuntimeError("Invalid TWSE long-history indicator evidence")
    if data["database_bytes"]>=MAX_DATABASE_BYTES:
        raise RuntimeError("Free Neon storage ceiling; refuse further calculation")
    if not 0<=data["current_scores"]<=data["current_indicators"]<=data["eligible"]:
        raise RuntimeError("Invalid TWSE latest research coverage")
    return data


def score_page(url,offset):
    if type(offset) is not int or not 0<=offset<=1200:
        raise ValueError("Unsafe TWSE score offset")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        rows=conn.execute(SCORE_PAGE_SQL,(SCORE_BATCH_SIZE,offset)).fetchall()
    return [(row["market"],row["stock_id"]) for row in rows]


def assert_no_raw_price_change(before,after):
    if before["raw_twse_rows"]!=after["raw_twse_rows"]:
        raise RuntimeError("Verified TWSE raw market history changed during research catch-up")
    if before["eligible"]!=after["eligible"]:
        raise RuntimeError("Verified 240-day TWSE research cohort changed")
    if (after["current_indicators"]<before["current_indicators"] or
        after["current_scores"]<before["current_scores"]):
        raise RuntimeError("TWSE latest research coverage regressed")


def save(path,report):
    if not path:
        return
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                    encoding="utf-8")
    temp.replace(path)


def execute(url,*,apply=False,max_rounds=MAX_ROUNDS,
            max_score_batches=MAX_SCORE_BATCHES,report_path=None):
    if type(max_rounds) is not int or not 0<=max_rounds<=MAX_ROUNDS:
        raise ValueError("Unsafe TWSE indicator batch bound")
    if (type(max_score_batches) is not int or
        not 0<=max_score_batches<=MAX_SCORE_BATCHES):
        raise ValueError("Unsafe TWSE score batch bound")
    if apply and (
        max_rounds<1 or max_score_batches<1 or
        os.environ.get("STOCK_TWSE_240_RESEARCH_WRITE_ENABLED")!="yes" or
        os.environ.get("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED")!="yes" or
        os.environ.get("STOCK_TWSE_240_SCORE_RECALC_ENABLED")!="yes"
    ):
        raise ValueError("Three independent research-only write gates required")
    before=capture(url)
    report={
        "scope":"TWSE_SOURCE_VERIFIED_240_SESSION_RESEARCH_ONLY",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "baseline":before,"latest":before,"rounds":[],"score_batches":[],
        "raw_prices_modified":False,"trading_enabled":False,
        "line_messages_sent":False,"paid_upgrade_requested":False,
        "completed":False,
    }
    save(report_path,report)
    if not apply:
        return report
    if (before["verified_source_days"]<MIN_VERIFIED_DAYS or
        before["eligible"]<MIN_240_COHORT):
        raise RuntimeError("Official TWSE 240-day cohort not independently verified")

    current=before
    for i in range(max_rounds):
        if current["current_indicators"]==current["eligible"]:
            break
        items=indicator_run(url,apply=True,per_market=20,
                            markets=("twse",),min_verified_price_days=240)
        failed=sum(x["status"]=="failed" for x in items)
        verified=sum(x["status"]=="verified" for x in items)
        updated=capture(url)
        assert_no_raw_price_change(current,updated)
        report["rounds"].append({
            "batch":i+1,"selected":len(items),"verified":verified,
            "failed":failed,"current_indicators":updated["current_indicators"]
        })
        report["latest"]=updated
        save(report_path,report)
        if failed or verified<=0 or updated["current_indicators"]<=current["current_indicators"]:
            raise RuntimeError("TWSE 240-session indicator batch made no verified progress")
        current=updated
    if current["current_indicators"]!=current["eligible"]:
        raise RuntimeError("TWSE 240-session indicator rounds exhausted")

    processed=0
    for i in range(max_score_batches):
        stocks=score_page(url,processed)
        if not stocks:
            break
        n=calculate_all(url,stocks=stocks,missing_only=False)
        if n!=len(stocks):
            raise RuntimeError("Incomplete exact stock-scoped 240-session score refresh")
        processed+=len(stocks)
        updated=capture(url)
        assert_no_raw_price_change(current,updated)
        report["score_batches"].append({
            "batch":i+1,"processed":n,
            "total_processed":processed,
            "current_scores":updated["current_scores"]
        })
        report["latest"]=updated
        save(report_path,report)
        current=updated
    report["completed"]=(
        current["eligible"]>=MIN_240_COHORT and
        current["current_indicators"]==current["eligible"] and
        current["current_scores"]==current["eligible"] and
        processed==current["eligible"]
    )
    save(report_path,report)
    if not report["completed"]:
        raise RuntimeError("TWSE 240-session latest same-day research cohort incomplete")
    return report


def main():
    parser=argparse.ArgumentParser(description="TWSE verified 240-session research enrichment")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--max-rounds",type=int,default=MAX_ROUNDS)
    parser.add_argument("--max-score-batches",type=int,default=MAX_SCORE_BATCHES)
    parser.add_argument("--report",type=Path,default=Path("twse-240-research-evidence.json"))
    args=parser.parse_args()
    out=execute(os.getenv("DATABASE_URL",""),apply=args.apply,
                max_rounds=args.max_rounds,
                max_score_batches=args.max_score_batches,
                report_path=args.report)
    print(json.dumps({
        "scope":out["scope"],"eligible":out["latest"]["eligible"],
        "matched":out["latest"]["current_scores"],
        "completed":out["completed"],"trading_enabled":False,
        "line_messages_sent":False
    },ensure_ascii=False))


if __name__=="__main__":
    main()
