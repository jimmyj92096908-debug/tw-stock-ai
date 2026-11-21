"""Read-only prerequisites for independent scheduled TWSE 240-day campaigns.

GitHub limits workflow_run nesting to three levels, so post-TPEx TWSE
long-history and research follow-on workflows are independent scheduled roots.
These SELECT-only gates prevent premature writes, unnecessary repeats, and
overlapping source/research quality assumptions. No GitHub tokens or LINE.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

MAX_DATABASE_BYTES=800_000_000
MIN_TPEX_SOURCE_DAYS=80
MIN_TPEX_ELIGIBLE=700
MIN_TWSE_LONG_SOURCE_DAYS=240
MIN_TWSE_LONG_ELIGIBLE=500

STATE_SQL="""
WITH last_market AS (
 SELECT max(trade_date) latest FROM public.daily_prices WHERE close>0
), sourced AS (
 SELECT
   count(DISTINCT trade_date) FILTER(WHERE market='tpex'
        AND source='TPEX_DATED_OTC_EW')::int tpex_source_days,
   count(DISTINCT trade_date) FILTER(WHERE market='twse'
        AND source='TWSE_MI_INDEX_ALLBUT0999')::int twse_source_days
 FROM public.daily_prices
), legacy AS (
 SELECT count(*)::bigint legacy_rows,
        count(*) FILTER(WHERE p.volume IS NOT NULL AND (
           a.volume IS NULL OR a.share_adjustment_factor IS NULL
           OR abs(a.volume-p.volume::numeric*1000*a.share_adjustment_factor)>
              greatest(1,abs(p.volume::numeric*1000*a.share_adjustment_factor)*0.00001)
        ))::bigint bad_legacy_volume,
        count(*) FILTER(WHERE p.turnover IS NOT NULL AND (
           a.turnover IS NULL OR abs(a.turnover-p.turnover*1000)>0.02
        ))::bigint bad_legacy_turnover
 FROM public.daily_prices p
 LEFT JOIN public.daily_adjusted_prices a USING(market,stock_id,trade_date)
 WHERE p.market='tpex' AND p.source='TPEX_TRADING_STOCK'
), prices AS (
 SELECT p.market,p.stock_id,count(*) FILTER(WHERE close>0 AND volume>=0)::int days,
        max(trade_date) FILTER(WHERE close>0 AND volume>=0) latest_close
 FROM public.daily_prices p
 WHERE p.stock_id<>'1808'
 GROUP BY p.market,p.stock_id
), eligible AS (
 SELECT p.market,p.stock_id,p.days,p.latest_close FROM prices p,last_market l
 WHERE p.latest_close>=l.latest-interval '7 days'
   AND ((p.market='tpex' AND p.days>=60) OR
        (p.market='twse' AND p.days>=240))
), coverage AS (
 SELECT e.market,e.stock_id,e.days,e.latest_close,
   EXISTS(SELECT 1 FROM public.daily_technicals t
     WHERE t.market=e.market AND t.stock_id=e.stock_id
       AND t.trade_date=e.latest_close) tech_latest,
   EXISTS(SELECT 1 FROM public.daily_smc s
     WHERE s.market=e.market AND s.stock_id=e.stock_id
       AND s.trade_date=e.latest_close) smc_latest,
   EXISTS(SELECT 1 FROM public.daily_composite_scores c
     WHERE c.market=e.market AND c.stock_id=e.stock_id
       AND c.as_of_date=e.latest_close AND c.total_score IS NOT NULL) scored,
   (SELECT count(*) FROM public.daily_adjusted_prices a
     WHERE a.market=e.market AND a.stock_id=e.stock_id) adjusted_days,
   (SELECT count(*) FROM public.daily_technicals t
     WHERE t.market=e.market AND t.stock_id=e.stock_id) tech_days,
   (SELECT count(*) FROM public.daily_smc s
     WHERE s.market=e.market AND s.stock_id=e.stock_id) smc_days,
   EXISTS(SELECT 1 FROM public.daily_technicals t
     WHERE t.market=e.market AND t.stock_id=e.stock_id
       AND t.trade_date=e.latest_close AND t.ma240 IS NOT NULL) has_ma240
 FROM eligible e
)
SELECT s.tpex_source_days,s.twse_source_days,
       l.legacy_rows,l.bad_legacy_volume,l.bad_legacy_turnover,
       (SELECT pg_database_size(current_database())::bigint) database_bytes,
       count(*) FILTER(WHERE c.market='tpex')::int tpex_eligible,
       count(*) FILTER(WHERE c.market='tpex' AND c.tech_latest
         AND c.smc_latest AND c.scored)::int tpex_matched,
       count(*) FILTER(WHERE c.market='twse')::int twse_240_eligible,
       count(*) FILTER(WHERE c.market='twse' AND c.tech_latest
         AND c.smc_latest AND c.has_ma240
         AND c.adjusted_days>=c.days AND c.tech_days>=c.days
         AND c.smc_days>=c.days)::int twse_full_indicators,
       count(*) FILTER(WHERE c.market='twse' AND c.tech_latest
         AND c.smc_latest AND c.has_ma240
         AND c.adjusted_days>=c.days AND c.tech_days>=c.days
         AND c.smc_days>=c.days AND c.scored)::int twse_complete_scores
FROM sourced s CROSS JOIN legacy l LEFT JOIN coverage c ON true
GROUP BY s.tpex_source_days,s.twse_source_days,l.legacy_rows,
         l.bad_legacy_volume,l.bad_legacy_turnover
"""


def snapshot(url):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        result=dict(conn.execute(STATE_SQL).fetchone())
    for key in (
        "tpex_source_days","twse_source_days","legacy_rows",
        "bad_legacy_volume","bad_legacy_turnover","database_bytes",
        "tpex_eligible","tpex_matched","twse_240_eligible",
        "twse_full_indicators","twse_complete_scores"
    ):
        if type(result.get(key)) is not int or result[key]<0:
            raise RuntimeError("Invalid read-only source/score prerequisite")
    if result["database_bytes"]>=MAX_DATABASE_BYTES:
        raise RuntimeError("Free Neon database storage limit guard")
    if result["tpex_matched"]>result["tpex_eligible"]:
        raise RuntimeError("Invalid TPEx score scope")
    if not (result["twse_complete_scores"]<=result["twse_full_indicators"]
            <=result["twse_240_eligible"]):
        raise RuntimeError("Invalid TWSE long-horizon coverage")
    return result


def decide(mode,state):
    if mode not in ("source","research"):
        raise ValueError("Unknown independent schedule mode")
    if mode=="source":
        ready=(
            state["tpex_source_days"]>=MIN_TPEX_SOURCE_DAYS and
            state["tpex_eligible"]>=MIN_TPEX_ELIGIBLE and
            state["tpex_matched"]==state["tpex_eligible"] and
            state["legacy_rows"]>=1000 and
            state["bad_legacy_volume"]==0 and
            state["bad_legacy_turnover"]==0 and
            100<=state["twse_source_days"]<MIN_TWSE_LONG_SOURCE_DAYS
        )
    else:
        ready=(
            state["twse_source_days"]>=MIN_TWSE_LONG_SOURCE_DAYS and
            state["twse_240_eligible"]>=MIN_TWSE_LONG_ELIGIBLE and
            (state["twse_full_indicators"]<state["twse_240_eligible"] or
             state["twse_complete_scores"]<state["twse_240_eligible"])
        )
    return bool(ready)


def main():
    parser=argparse.ArgumentParser(description="Read-only TWSE independent schedule gate")
    parser.add_argument("--mode",choices=("source","research"),required=True)
    args=parser.parse_args()
    proof=snapshot(os.environ.get("DATABASE_URL",""))
    ready=decide(args.mode,proof)
    result={"mode":args.mode,"should_run":ready,"evidence":proof,
            "read_only":True,"trading_enabled":False,"line_messages_sent":False}
    print(json.dumps(result,ensure_ascii=False))
    output=os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a",encoding="utf-8") as writer:
            writer.write("should_run="+("true" if ready else "false")+"\n")
    summary=os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a",encoding="utf-8") as writer:
            writer.write("### TWSE verified independent "+args.mode+" gate\n")
            writer.write("Read-only proof, should_run="+str(ready).lower()+"\n")


if __name__=="__main__":
    main()
