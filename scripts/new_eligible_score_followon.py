"""Explicit, very small stock-only catch-up after verified official history.

Unlike the legacy full-universe calculate_all() path, this reuses the proven
score formula for ONLY 1..5 currently eligible stocks and inserts missing
daily_composite_scores primary keys without changing any previous score rows.
No raw daily_prices writes, no brokerage orders, no LINE.
"""
from __future__ import annotations

import argparse
from datetime import date,datetime,timezone
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from build_adjusted_prices import build as build_adjusted_stock  # noqa: E402
from calculate_technicals import calculate_stock as build_technicals  # noqa: E402
from calculate_smc import calculate_stock as build_smc  # noqa: E402
from composite_score import calculate_all  # noqa: E402
from tdcc_data import normalize_database_url  # noqa: E402

MAX_STOCKS=5
MIN_SESSIONS=60
MAX_DB_BYTES=800_000_000

# Subquery ensures no duplicate generated rows from already stored price days.
MISSING_SQL="""
WITH priced AS (
 SELECT market,stock_id,
        COUNT(*) FILTER(WHERE close>0)::int AS valid_days,
        MAX(trade_date) FILTER(WHERE close>0) AS latest_close
 FROM public.daily_prices GROUP BY market,stock_id
), recent AS (
 SELECT p.market,p.stock_id,p.valid_days,p.latest_close
 FROM priced p
 WHERE p.stock_id<>'1808' AND p.valid_days>=60
   AND p.latest_close >= (
     SELECT MAX(trade_date) FROM public.daily_prices WHERE close>0
   ) - INTERVAL '7 days'
), status AS (
 SELECT r.*,
  EXISTS(SELECT 1 FROM public.daily_technicals t
    WHERE t.market=r.market AND t.stock_id=r.stock_id
      AND t.trade_date=r.latest_close) AS has_tech,
  EXISTS(SELECT 1 FROM public.daily_smc s
    WHERE s.market=r.market AND s.stock_id=r.stock_id
      AND s.trade_date=r.latest_close) AS has_smc,
  EXISTS(SELECT 1 FROM public.daily_composite_scores c
    WHERE c.market=r.market AND c.stock_id=r.stock_id
      AND c.as_of_date=r.latest_close AND c.total_score IS NOT NULL) AS has_score
 FROM recent r
)
SELECT market,stock_id,valid_days,latest_close,has_tech,has_smc,has_score
FROM status
WHERE NOT (has_tech AND has_smc AND has_score)
ORDER BY market,stock_id LIMIT %s
"""
RECHECK_SQL="""
WITH priced AS (
 SELECT market,stock_id,
        COUNT(*) FILTER(WHERE close>0)::int n,
        MAX(trade_date) FILTER(WHERE close>0) d
 FROM public.daily_prices
 WHERE market=%s AND stock_id=%s GROUP BY market,stock_id
)
SELECT p.n,p.d,
 EXISTS(SELECT 1 FROM public.daily_adjusted_prices a
   WHERE a.market=p.market AND a.stock_id=p.stock_id AND a.trade_date=p.d) adj,
 EXISTS(SELECT 1 FROM public.daily_technicals t
   WHERE t.market=p.market AND t.stock_id=p.stock_id AND t.trade_date=p.d) tech,
 EXISTS(SELECT 1 FROM public.daily_smc s
   WHERE s.market=p.market AND s.stock_id=p.stock_id AND s.trade_date=p.d) smc,
 EXISTS(SELECT 1 FROM public.daily_composite_scores c
   WHERE c.market=p.market AND c.stock_id=p.stock_id
     AND c.as_of_date=p.d AND c.total_score IS NOT NULL) score
FROM priced p
"""
BASELINE_SQL="""
SELECT
 (SELECT COUNT(*)::bigint FROM public.daily_prices) AS price_rows,
 (SELECT MAX(trade_date) FROM public.daily_prices WHERE close>0) AS latest_price_date,
 pg_database_size(current_database())::bigint AS database_bytes
"""


def verified_baseline(conn):
    with conn.cursor() as c:
        c.execute(BASELINE_SQL)
        data=dict(c.fetchone())
    if type(data.get("price_rows")) is not int or data["price_rows"]<=0:
        raise RuntimeError("No verified raw price baseline")
    if data.get("latest_price_date") is None:
        raise RuntimeError("No latest valid market close")
    if type(data.get("database_bytes")) is not int or not 0<data["database_bytes"]<MAX_DB_BYTES:
        raise RuntimeError("Free storage stop line exceeded")
    return data


def candidates(conn,limit):
    if type(limit) is not int or not 1<=limit<=MAX_STOCKS:
        raise ValueError("1..5 bounded stock selection required")
    with conn.cursor() as c:
        c.execute(MISSING_SQL,(limit,))
        out=[dict(row) for row in c.fetchall()]
    for x in out:
        if x["market"] not in ("twse","tpex") or not x["stock_id"].isdigit():
            raise RuntimeError("Invalid price history stock key")
        if type(x["valid_days"]) is not int or x["valid_days"]<MIN_SESSIONS:
            raise RuntimeError("No 60 actual valid close sessions")
        if x["latest_close"] is None:
            raise RuntimeError("Cannot use stale/null priced research date")
        for key in ("has_tech","has_smc","has_score"):
            if type(x[key]) is not bool:
                raise RuntimeError("Invalid completeness flag")
    return out


def recheck(conn,item):
    with conn.cursor() as c:
        c.execute(RECHECK_SQL,(item["market"],item["stock_id"]))
        found=c.fetchone()
    if not found:
        raise RuntimeError("Selected research stock disappeared")
    item_status=dict(found)
    if item_status["n"]<MIN_SESSIONS or item_status["d"]!=item["latest_close"]:
        raise RuntimeError("Verified price history changed during score catch-up")
    return item_status


def execute(url,*,apply=False,limit=2,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    if type(limit) is not int or not 1<=limit<=MAX_STOCKS:
        raise ValueError("Stock follow-on limit must be 1..5")
    if apply and os.environ.get("STOCK_NEW_ELIGIBLE_SCORE_WRITE_ENABLED")!="yes":
        raise PermissionError("Explicit small-cohort score write authorization missing")
    url=normalize_database_url(url)
    with psycopg.connect(url,row_factory=dict_row,connect_timeout=15) as conn:
        # Enforce all selection and source-baseline queries as read-only before
        # attempting any stock-level adjusted/indicator insert/upsert.
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '20000ms'")
            before=verified_baseline(conn)
            selected=candidates(conn,limit)
    report={
        "schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
        "scope":"AT_MOST_FIVE_RECENT_60_SESSION_RESEARCH_STOCKS",
        "selected":[{"market":x["market"],"stock_id":x["stock_id"],
                     "valid_sessions":x["valid_days"],
                     "had_latest_tech":x["has_tech"],
                     "had_latest_smc":x["has_smc"],
                     "had_latest_score":x["has_score"]} for x in selected],
        "baseline_raw_price_rows":before["price_rows"],
        "indicator_stocks_computed":0,"new_composite_rows":0,
        "complete":len(selected)==0,
        "raw_prices_modified":False,"existing_composite_rows_overwritten":False,
        "database_schema_modified":False,"line_messages_sent":False,
        "orders_enabled":False,"paid_plan_requested":False
    }
    _save(report_path,report)
    if not apply:
        return report
    for item in selected:
        if item["has_tech"] and item["has_smc"]:
            continue
        with psycopg.connect(url,row_factory=dict_row,connect_timeout=15) as conn:
            with conn.transaction():
                if verified_baseline(conn)["price_rows"]!=before["price_rows"]:
                    raise RuntimeError("Raw price database changed; cannot safely continue")
                adjusted=build_adjusted_stock(conn,item["market"],item["stock_id"])
                technical=build_technicals(conn,item["market"],item["stock_id"])
                smc=build_smc(conn,item["market"],item["stock_id"])
                verify=recheck(conn,item)
                if (min(adjusted,technical,smc)<MIN_SESSIONS or
                    not all(verify[k] for k in ("adj","tech","smc"))):
                    raise RuntimeError("Latest eligible indicator rebuild not verified")
        report["indicator_stocks_computed"]+=1
        _save(report_path,report)
    targets=[(item["market"],item["stock_id"]) for item in selected]
    if targets:
        # Same score formula as the main pipeline, but no full-table scan or
        # ON CONFLICT UPDATE of scores already present. One bounded commit.
        report["new_composite_rows"]=calculate_all(url,stocks=targets,missing_only=True)
    with psycopg.connect(url,row_factory=dict_row,connect_timeout=15) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '20000ms'")
            final=verified_baseline(conn)
            checked=[recheck(conn,item) for item in selected]
    if (before["price_rows"]!=final["price_rows"] or
        before["latest_price_date"]!=final["latest_price_date"]):
        raise RuntimeError("Raw price facts changed during bounded processing")
    report["complete"]=all(
        row["adj"] and row["tech"] and row["smc"] and row["score"]
        for row in checked
    )
    _save(report_path,report)
    if not report["complete"]:
        raise RuntimeError("Not all selected same-day scores verified")
    return report


def _save(path,data):
    if path is not None:
        out=Path(path)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(data,ensure_ascii=False,indent=2,
                                  default=str)+"\n",encoding="utf-8")


def main():
    a=argparse.ArgumentParser(description="Tiny new-eligible price-to-score follow-on")
    a.add_argument("--apply",action="store_true")
    a.add_argument("--limit",type=int,default=2)
    a.add_argument("--report",type=Path,default=Path("new-eligible-followon-evidence.json"))
    opts=a.parse_args()
    result=execute(os.environ.get("DATABASE_URL",""),apply=opts.apply,
                   limit=opts.limit,report_path=opts.report)
    print(json.dumps({
       "selected":len(result["selected"]),
       "new_composites":result["new_composite_rows"],
       "complete":result["complete"],
       "existing_scores_overwritten":result["existing_composite_rows_overwritten"],
       "raw_prices_modified":False
    },ensure_ascii=False))


if __name__=="__main__":
    main()
