"""Read-only diagnosis of the entire Taiwan stock-master coverage denominator.

A stock with 1 historical quote is NOT a 60-session analysis candidate.
This module does not guess whether a stopped/missing official quote can be
recovered. No schema mutation, historical backfill, fees, LINE or trades.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
import json
import os
from pathlib import Path
import re

MAX_STOCKS=2500

AUDIT_SQL="""
WITH history AS (
 SELECT sm.market,sm.stock_id,sm.stock_name,
        COUNT(p.trade_date) FILTER(WHERE p.close>0)::int AS price_days,
        MAX(p.trade_date) FILTER(WHERE p.close>0) AS last_close
 FROM public.stock_master sm LEFT JOIN public.daily_prices p
   ON p.market=sm.market AND p.stock_id=sm.stock_id
 GROUP BY sm.market,sm.stock_id,sm.stock_name
), latest AS (
 SELECT MAX(trade_date) AS overall_latest FROM public.daily_prices WHERE close>0
)
SELECT h.market,h.stock_id,h.stock_name,h.price_days,h.last_close,
       latest.overall_latest,
       CASE WHEN h.last_close IS NULL THEN false
            ELSE (h.last_close >= latest.overall_latest-INTERVAL '7 days') END AS recent,
       CASE WHEN h.last_close IS NULL THEN false
            ELSE EXISTS (SELECT 1 FROM public.daily_technicals t
               WHERE t.market=h.market AND t.stock_id=h.stock_id
                 AND t.trade_date=h.last_close) END AS technical_current,
       CASE WHEN h.last_close IS NULL THEN false
            ELSE EXISTS (SELECT 1 FROM public.daily_smc s
               WHERE s.market=h.market AND s.stock_id=h.stock_id
                 AND s.trade_date=h.last_close) END AS smc_current,
       CASE WHEN h.last_close IS NULL THEN false
            ELSE EXISTS (SELECT 1 FROM public.daily_composite_scores c
               WHERE c.market=h.market AND c.stock_id=h.stock_id
                 AND c.as_of_date=h.last_close AND c.total_score IS NOT NULL)
            END AS score_current
FROM history h CROSS JOIN latest
ORDER BY h.market,h.stock_id
LIMIT 2501
"""
CATEGORY=(
    "NO_VERIFIED_PRICE",
    "RESEARCH_EXCLUDED",
    "STALE_LAST_VALID_PRICE",
    "LESS_THAN_60_VALID_SESSIONS",
    "MISSING_LATEST_TECHNICAL",
    "MISSING_LATEST_SMC",
    "MISSING_LATEST_COMPOSITE",
    "LATEST_RESEARCH_COHORT_COMPLETE",
)


def _date(value):
    if value is None:
        return None
    if isinstance(value,datetime):
        raise ValueError("Trade date may not be a timestamp")
    if isinstance(value,date):
        return value.isoformat()
    if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):
        raise ValueError("Explicit YYYY-MM-DD trade date required")
    return date.fromisoformat(value).isoformat()


def classify(row):
    """Exactly one primary blocker; preserve component gap booleans too."""
    if not isinstance(row,dict):
        raise ValueError("Expected stock audit object")
    market=row.get("market")
    stock=row.get("stock_id")
    if market not in ("twse","tpex") or not isinstance(stock,str) or not re.fullmatch(r"[0-9]{4,6}",stock):
        raise ValueError("Bad stock key")
    n=row.get("price_days")
    if type(n) is not int or n<0:
        raise ValueError("Invalid positive price-day count")
    latest=_date(row.get("overall_latest"))
    last=_date(row.get("last_close"))
    if latest is None:
        raise ValueError("Cannot infer any valid latest close date")
    for field in ("recent","technical_current","smc_current","score_current"):
        if type(row.get(field)) is not bool:
            raise ValueError("Missing independently checked flag: "+field)
    if (n==0) != (last is None) or (last is not None and last>latest):
        raise ValueError("Inconsistent verified price history")
    if last is None and (row["recent"] or row["technical_current"]
                         or row["smc_current"] or row["score_current"]):
        raise ValueError("A stock without a valid close cannot have current analysis")
    if last is not None:
        expected_recent=(date.fromisoformat(last) >=
                         date.fromisoformat(latest)-timedelta(days=7))
        if row["recent"]!=expected_recent:
            raise ValueError("Inconsistent recency evidence")
    if n==0:
        status=CATEGORY[0]
    elif stock=="1808" and market=="twse":
        status=CATEGORY[1]
    elif not row["recent"]:
        status=CATEGORY[2]
    elif n<60:
        status=CATEGORY[3]
    elif not row["technical_current"]:
        status=CATEGORY[4]
    elif not row["smc_current"]:
        status=CATEGORY[5]
    elif not row["score_current"]:
        status=CATEGORY[6]
    else:
        status=CATEGORY[7]
    return {
        "market":market,"stock_id":stock,"status":status,
        "valid_sessions":n,"last_close":last,
        "current_technical":row["technical_current"],
        "current_smc":row["smc_current"],
        "current_composite":row["score_current"],
    }


def summarize(rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_STOCKS:
        raise ValueError("Audit must have 1..2500 verified stock records")
    unique=set()
    stats=Counter()
    markets=defaultdict(Counter)
    stocks=[]
    latest=None
    for raw in rows:
        record=classify(raw)
        if latest is None:
            latest=_date(raw["overall_latest"])
        elif latest!=_date(raw["overall_latest"]):
            raise ValueError("Audit has mixed overall latest sessions")
        key=(record["market"],record["stock_id"])
        if key in unique:
            raise ValueError("Duplicate stock master primary key")
        unique.add(key)
        category=record["status"]
        stats[category]+=1
        markets[record["market"]][category]+=1
        stocks.append(record)
    totals={key:stats[key] for key in CATEGORY}
    if sum(totals.values())!=len(rows):
        raise AssertionError("Stock coverage cohorts not exhaustive")
    ready=stats["LATEST_RESEARCH_COHORT_COMPLETE"]
    eligible=sum(stats[k] for k in (
        "MISSING_LATEST_TECHNICAL","MISSING_LATEST_SMC",
        "MISSING_LATEST_COMPOSITE","LATEST_RESEARCH_COHORT_COMPLETE"))
    return {
        "schema_version":1,
        "as_of_latest_valid_market_session":latest,
        "stock_master_count":len(rows),
        "currently_eligible_60_day_research_cohort":eligible,
        "currently_eligible_matched_composite_stocks":ready,
        "currently_eligible_fraction":round(ready/eligible,6) if eligible else None,
        "full_master_matched_composite_fraction":round(ready/len(rows),6),
        "status_counts":totals,
        "by_market":{m:{k:markets[m][k] for k in CATEGORY} for m in sorted(markets)},
        "stocks":stocks,
        "official_source_has_backfillable_history_proven":False,
        "new_listing_or_suspension_reason_verified":False,
        "100_percent_all_listed_stocks_claimed":False,
        "database_written":False,
        "orders_enabled":False,
        "line_messages_sent":False,
    }


def read_only_snapshot(url):
    if not url:
        raise ValueError("Protected database read-only URL required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url,connect_timeout=12,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '20000ms'")
                cur.execute(AUDIT_SQL)
                rows=[dict(r) for r in cur.fetchmany(MAX_STOCKS+1)]
                if len(rows)>MAX_STOCKS:
                    raise ValueError("Stock master grew beyond free-tier bounded audit")
    return summarize(rows)


def main():
    p=argparse.ArgumentParser(description="Read-only full stock-master coverage diagnosis")
    p.add_argument("--source-json",type=Path,
                   help="Offline saved verified SQL rows; no Neon connection")
    p.add_argument("--read-neon",action="store_true",
                   help="Explicit read-only current Neon snapshot, bounded query")
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if bool(a.source_json)==bool(a.read_neon):
        p.error("Choose exactly one of --source-json or --read-neon")
    if a.read_neon:
        if os.environ.get("STOCK_100_AUDIT_READONLY")!="yes":
            raise PermissionError("Explicit STOCK_100_AUDIT_READONLY=yes required")
        result=read_only_snapshot(os.environ.get("DATABASE_URL",""))
    else:
        result=summarize(json.loads(a.source_json.read_text(encoding="utf-8")))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False,
                                   allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({
        "stock_master":result["stock_master_count"],
        "eligible":result["currently_eligible_60_day_research_cohort"],
        "matched":result["currently_eligible_matched_composite_stocks"],
        "status_counts":result["status_counts"],
        "live_stock_recommendation_enabled":False
    },ensure_ascii=False))


if __name__=="__main__":
    main()
