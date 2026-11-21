"""Read-only market-year and per-stock five-year data maturity evidence.

Official market-day completeness != five years for each currently listed TPEx
stock. Current stock_master is NOT the historical listing/delisting universe.
No derived-row INSERTs, no date inference, no price rewrites, no trades.
"""
from __future__ import annotations

from datetime import date,datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

SAFETY_STOP_BYTES=800_000_000
BUCKETS=("days0","days1_59","days60_119","days120_239","days240_479",
         "days480_719","days720_999","days1000_plus")

STOCK_DAYS_SQL="""WITH latest AS (
 SELECT MAX(trade_date) d FROM public.daily_prices
 WHERE market='tpex' AND close>0
),per_stock AS (
 SELECT sm.stock_id,
 COUNT(dp.trade_date) FILTER(WHERE dp.close>0 AND dp.volume>=0)::int AS days
 FROM public.stock_master sm CROSS JOIN latest l
 LEFT JOIN public.daily_prices dp ON dp.market='tpex' AND dp.stock_id=sm.stock_id
 AND dp.trade_date >= (l.d-INTERVAL '5 years') AND dp.trade_date <= l.d
 WHERE sm.market='tpex' GROUP BY sm.stock_id
)
SELECT COUNT(*)::int current_master,
 COUNT(*) FILTER(WHERE days=0)::int days0,
 COUNT(*) FILTER(WHERE days BETWEEN 1 AND 59)::int days1_59,
 COUNT(*) FILTER(WHERE days BETWEEN 60 AND 119)::int days60_119,
 COUNT(*) FILTER(WHERE days BETWEEN 120 AND 239)::int days120_239,
 COUNT(*) FILTER(WHERE days BETWEEN 240 AND 479)::int days240_479,
 COUNT(*) FILTER(WHERE days BETWEEN 480 AND 719)::int days480_719,
 COUNT(*) FILTER(WHERE days BETWEEN 720 AND 999)::int days720_999,
 COUNT(*) FILTER(WHERE days>=1000)::int days1000_plus
 FROM per_stock
"""
YEARLY_SQL="""WITH latest AS (
 SELECT MAX(trade_date) d FROM public.daily_prices
 WHERE market='tpex' AND close>0
),day_group AS (
 SELECT dp.trade_date,
 COUNT(*) FILTER(WHERE dp.close>0 AND dp.volume>=0)::int valid,
 COUNT(*) FILTER(WHERE dp.close>0 AND dp.volume>=0 AND
   dp.source='TPEX_DATED_OTC_EW')::int dated,
 COUNT(*) FILTER(WHERE dp.close>0 AND dp.volume>=0 AND
   dp.source='TPEX_DAILY_CLOSE_OPENAPI')::int openapi
 FROM public.daily_prices dp CROSS JOIN latest l
 WHERE dp.market='tpex' AND dp.trade_date >= (l.d-INTERVAL '5 years')
 AND dp.trade_date<=l.d GROUP BY dp.trade_date
)
SELECT EXTRACT(YEAR FROM trade_date)::int year,
 COUNT(*) FILTER(WHERE valid>=10)::int anchored_sessions,
 COUNT(*) FILTER(WHERE valid>=10 AND
   GREATEST(dated,openapi)>=500)::int official_full_market_sessions
 FROM day_group GROUP BY 1 ORDER BY year
"""
META_SQL="""SELECT pg_database_size(current_database())::bigint AS bytes,
(SELECT MAX(trade_date) FROM public.daily_prices
 WHERE market='tpex' AND close>0) AS latest_session"""

def assess(stock_summary,year_summary,meta):
    if not isinstance(stock_summary,dict) or not isinstance(year_summary,list) or not isinstance(meta,dict):
        raise ValueError("Audited stock, year and storage snapshots are mandatory")
    if (type(stock_summary.get("current_master")) is not int or
        stock_summary["current_master"]<700):
        raise ValueError("Invalid current TPEx stock-master denominator")
    if any(type(stock_summary.get(k)) is not int or stock_summary[k]<0 for k in BUCKETS):
        raise ValueError("Impossible negative/missing stock history bucket")
    if sum(stock_summary[k] for k in BUCKETS)!=stock_summary["current_master"]:
        raise ValueError("Stock history buckets do not sum to actual TPEx master")
    if type(meta.get("latest_session")) is not date or (
        type(meta.get("bytes")) is not int or meta["bytes"]<=0):
        raise ValueError("Invalid real observed latest source session or Neon size")
    if len(year_summary)!=6:
        raise ValueError("Five-year rolling period must include six calendar-year segments")
    years=set()
    annual=[]
    for year in year_summary:
        yr=year.get("year")
        known=year.get("anchored_sessions")
        official=year.get("official_full_market_sessions")
        if (type(yr) is not int or type(known) is not int or
            type(official) is not int or yr in years or
            yr<2010 or yr>meta["latest_session"].year or
            known<=0 or official<0 or official>known):
            raise ValueError("Invalid/duplicate year or independently anchored market day count")
        years.add(yr)
        annual.append({"year":yr,"observed_anchored_sessions":known,
                       "official_full_market_sessions":official,
                       "unfilled_market_sessions":known-official,
                       "official_market_coverage_percent":round(official/known*100,2)})
    annual.sort(key=lambda item:item["year"])
    if (annual[0]["year"]!=meta["latest_session"].year-5 or
        annual[-1]["year"]!=meta["latest_session"].year or not all(
        annual[i+1]["year"]==annual[i]["year"]+1 for i in range(len(annual)-1)
    )):
        raise ValueError("Missing real calendar year from a five-year stock-source report")
    total=sum(x["observed_anchored_sessions"] for x in annual)
    official=sum(x["official_full_market_sessions"] for x in annual)
    if total<900:
        raise RuntimeError("Insufficient real known market sessions for five-year research audit")
    minimum_240=(stock_summary["days240_479"]+stock_summary["days480_719"]+
                 stock_summary["days720_999"]+stock_summary["days1000_plus"])
    minimum_480=(stock_summary["days480_719"]+stock_summary["days720_999"]+
                 stock_summary["days1000_plus"])
    return {
       "schema_version":1,
       "scope":"TPEX_FIVE_YEAR_SOURCE_DEPTH_READ_ONLY_RESEARCH_READINESS",
       "latest_trading_session":meta["latest_session"].isoformat(),
       "five_year_stock_master_today":stock_summary["current_master"],
       "market_years":annual,
       "total_independently_anchored_market_sessions":total,
       "source_proven_full_market_sessions":official,
       "market_wide_anchored_day_coverage_pct":round(official/total*100,2),
       "still_unfilled_anchored_market_sessions":total-official,
       "stock_valid_session_distribution":{k:stock_summary[k] for k in BUCKETS},
       "current_stock_master_with_at_least_240_valid_days":minimum_240,
       "current_stock_master_with_at_least_480_valid_days":minimum_480,
       "current_stock_master_with_at_least_1000_valid_days":
           stock_summary["days1000_plus"],
       "database_bytes":meta["bytes"],
       "free_internal_stop_bytes":SAFETY_STOP_BYTES,
       "free_headroom_bytes":max(0,SAFETY_STOP_BYTES-meta["bytes"]),
       "raw_source_date_count_is_not_per_stock_5y_completeness":True,
       "current_stock_master_is_not_historical_listed_universe":True,
       "ipo_delisting_and_no_trade_history_independently_audited":False,
       "corporate_action_original_disclosure_vintage_verified":False,
       "historical_independent_model_holdout_approved":False,
       "model_live_trading_approved":False,
       "database_read_only":True,
       "LINE_messages_sent":False,"paid_service_used":False
    }

def inspect(url,*,report_path=None):
    if not url:
        raise ValueError("Protected existing DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='45000ms'")
        meta=dict(conn.execute(META_SQL).fetchone())
        stock=dict(conn.execute(STOCK_DAYS_SQL).fetchone())
        years=[dict(x) for x in conn.execute(YEARLY_SQL).fetchall()]
    result=assess(stock,years,meta)
    result["checked_utc"]=datetime.now(ZoneInfo("UTC")).isoformat()
    if report_path:
        target=Path(report_path)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    import argparse
    p=argparse.ArgumentParser(description="Read-only TPEx five-year annual source and per-stock maturity audit")
    p.add_argument("--report",type=Path,default=Path("tpex-five-year-per-stock-maturity.json"))
    args=p.parse_args()
    out=inspect(os.getenv("DATABASE_URL",""),report_path=args.report)
    print(json.dumps({
       k:out[k] for k in (
       "scope","latest_trading_session","market_years",
       "market_wide_anchored_day_coverage_pct",
       "stock_valid_session_distribution",
       "current_stock_master_with_at_least_240_valid_days",
       "current_stock_master_with_at_least_480_valid_days",
       "database_bytes","historical_independent_model_holdout_approved")
    },ensure_ascii=False))

if __name__=="__main__":
    main()
