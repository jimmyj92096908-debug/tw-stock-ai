"""Read-only TPEx five-year source capacity, historical-factor debt and batch plan.

The active official market importer writes source-only prices. No derived
recalculation must race it or assume 879/879 still holds. This analysis uses
real PostgreSQL per-table row counts and total index/heap sizes, projects
materialized all-history factor debt conservatively, and emits a finite
fixed-stock recomputation candidate plan only. Never mutates Neon.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SAFETY_STOP_BYTES = 800_000_000
MIN_RECOMPUTE_FREE_BYTES = 40_000_000
MAX_CANDIDATE_STOCKS = 5
MAX_RECOMPUTE_PRICE_ROWS = 5000

TABLE_SQL = """
SELECT 'daily_prices' AS tbl, count(*)::bigint AS rows,
 pg_total_relation_size('public.daily_prices')::bigint AS bytes
FROM public.daily_prices
UNION ALL SELECT 'daily_adjusted_prices',count(*)::bigint,
 pg_total_relation_size('public.daily_adjusted_prices')::bigint
FROM public.daily_adjusted_prices
UNION ALL SELECT 'daily_technicals',count(*)::bigint,
 pg_total_relation_size('public.daily_technicals')::bigint
FROM public.daily_technicals
UNION ALL SELECT 'daily_smc',count(*)::bigint,
 pg_total_relation_size('public.daily_smc')::bigint
FROM public.daily_smc
"""

SOURCE_DAYS_SQL = """
WITH known AS (
 SELECT trade_date,
 COUNT(*) FILTER (WHERE close>0 AND volume>=0)::int AS original_closes,
 COUNT(*) FILTER (WHERE source='TPEX_DATED_OTC_EW'
  AND close>0 AND volume>=0)::int AS official_dated_closes,
 COUNT(*) FILTER (WHERE source='TPEX_DAILY_CLOSE_OPENAPI'
  AND close>0 AND volume>=0)::int AS daily_openapi_closes
 FROM public.daily_prices
 WHERE market='tpex'
 AND trade_date >= (SELECT max(trade_date)-interval '5 years'
                    FROM public.daily_prices WHERE market='tpex' AND close>0)
 GROUP BY trade_date
)
SELECT COUNT(*) FILTER (WHERE original_closes>=10)::int AS known_anchor_days,
 COUNT(*) FILTER (WHERE original_closes>=10 AND
   GREATEST(official_dated_closes,daily_openapi_closes)>=500)::int AS full_market_source_days,
 COUNT(*) FILTER (WHERE original_closes>=10 AND
   GREATEST(official_dated_closes,daily_openapi_closes)<500)::int AS incomplete_anchor_days
FROM known
"""

# Counts only *genuinely missing* historical derived rows. Do not consider
# a latest-only score to be full historical factor completeness.
MISSING_SQL = """
WITH per_stock AS (
 SELECT p.stock_id,
 COUNT(*)::int AS price_rows,
 COUNT(*) FILTER (WHERE a.trade_date IS NULL)::int AS missing_adjusted,
 COUNT(*) FILTER (WHERE t.trade_date IS NULL)::int AS missing_technical,
 COUNT(*) FILTER (WHERE s.trade_date IS NULL)::int AS missing_smc,
 COUNT(*) FILTER (WHERE p.close>0 AND p.volume>=0)::int AS valid_days,
 MAX(p.trade_date) FILTER (WHERE p.close>0 AND p.volume>=0) AS latest_valid
 FROM public.daily_prices p
 LEFT JOIN public.daily_adjusted_prices a
  ON a.market=p.market AND a.stock_id=p.stock_id AND a.trade_date=p.trade_date
 LEFT JOIN public.daily_technicals t
  ON t.market=p.market AND t.stock_id=p.stock_id AND t.trade_date=p.trade_date
 LEFT JOIN public.daily_smc s
  ON s.market=p.market AND s.stock_id=p.stock_id AND s.trade_date=p.trade_date
 WHERE p.market='tpex' AND p.stock_id<>'1808'
 GROUP BY p.stock_id
)
SELECT * FROM per_stock ORDER BY
 (missing_adjusted+missing_technical+missing_smc) DESC,
 price_rows ASC,stock_id
"""
DB_SIZE_SQL = "SELECT pg_database_size(current_database())::bigint AS size_bytes"

def row_byte_estimate(tables,table):
    info=tables[table]
    if type(info["rows"]) is not int or type(info["bytes"]) is not int:
        raise ValueError("Expected exact audited PostgreSQL numeric storage counts")
    if info["rows"]<1 or info["bytes"]<info["rows"]:
        raise ValueError("No sound table-size estimate for "+table)
    # 1.5x historical physical-per-row index/heap estimate. Not a DB promise.
    return math.ceil(info["bytes"]/info["rows"]*1.5)

def formulate_plan(db_bytes,tables,source_stats,cohort):
    if type(db_bytes) is not int or db_bytes<1:
        raise ValueError("Invalid Neon storage size")
    if set(tables)!={
        "daily_prices","daily_adjusted_prices","daily_technicals","daily_smc"
    }:
        raise ValueError("Missing required existing source/derived storage tables")
    if not isinstance(source_stats,dict) or not isinstance(cohort,list):
        raise ValueError("Unverified market sessions or stock rows")
    for key in ("known_anchor_days","full_market_source_days","incomplete_anchor_days"):
        if type(source_stats.get(key)) is not int or source_stats[key]<0:
            raise ValueError("Invalid independent source day count")
    if source_stats["known_anchor_days"]!= (
        source_stats["full_market_source_days"]+source_stats["incomplete_anchor_days"]
    ):
        raise ValueError("Market session counts do not reconcile")
    if not cohort or len({r["stock_id"] for r in cohort})!=len(cohort):
        raise ValueError("Invalid or duplicate TPEx stock coverage cohort")
    for r in cohort:
        if not isinstance(r.get("stock_id"),str) or not r["stock_id"]:
            raise ValueError("Unverifiable stock identifier")
        if any(type(r.get(k)) is not int or r[k]<0 for k in
          ("price_rows","missing_adjusted","missing_technical","missing_smc","valid_days")):
            raise ValueError("Missing per-stock raw/derived row accounting")
        if any(r[k]>r["price_rows"] for k in
               ("missing_adjusted","missing_technical","missing_smc")):
            raise ValueError("Impossible >100% missing factor accounting")
    price_b=row_byte_estimate(tables,"daily_prices")
    derived_b={
        "missing_adjusted":row_byte_estimate(tables,"daily_adjusted_prices"),
        "missing_technical":row_byte_estimate(tables,"daily_technicals"),
        "missing_smc":row_byte_estimate(tables,"daily_smc")
    }
    missing={key:sum(r[key] for r in cohort) for key in derived_b}
    estimated_factor_bytes=sum(missing[k]*v for k,v in derived_b.items())
    headroom=max(0,SAFETY_STOP_BYTES-db_bytes)
    projected_full_derived=db_bytes+estimated_factor_bytes
    # 898 stock_master entries may include never-listed/renamed delistings.
    # This is a capacity scenario, not proof that all known dates traded.
    remaining_source_dates=source_stats["incomplete_anchor_days"]
    scenario_raw_add_bytes=remaining_source_dates*850*price_b
    selected=[]
    selected_price_rows=0
    for r in cohort:
        if not any(r[k] for k in derived_b) or r["valid_days"]<60:
            continue
        if len(selected)>=MAX_CANDIDATE_STOCKS:
            break
        if selected_price_rows+r["price_rows"]>MAX_RECOMPUTE_PRICE_ROWS:
            continue
        selected.append({
            "stock_id":r["stock_id"],"raw_price_days":r["price_rows"],
            "missing_adjusted":r["missing_adjusted"],
            "missing_technical":r["missing_technical"],
            "missing_smc":r["missing_smc"]
        })
        selected_price_rows+=r["price_rows"]
    # Recomputing all existing stock rows involves UPSERT on conflict and can
    # temporarily create dead tuples. Reserve 2x factor bytes for selected rows.
    selected_estimated_write_bytes=2*selected_price_rows*sum(derived_b.values())
    approved_preview_only=bool(
        selected and headroom>=MIN_RECOMPUTE_FREE_BYTES+
        selected_estimated_write_bytes
    )
    return {
       "source":source_stats,
       "database_bytes":db_bytes,
       "free_safety_stop_bytes":SAFETY_STOP_BYTES,
       "headroom_to_internal_safety_stop_bytes":headroom,
       "measured_row_storage_bytes":tables,
       "conservative_bytes_per_new_row":{"daily_prices":price_b,**derived_b},
       "estimated_unfilled_derived_row_counts":missing,
       "estimated_full_derived_catchup_extra_bytes":estimated_factor_bytes,
       "estimated_database_after_full_derived":projected_full_derived,
       "full_history_derivatives_fit_free_safety_budget_estimate":
         projected_full_derived+MIN_RECOMPUTE_FREE_BYTES<SAFETY_STOP_BYTES,
       "scenario_missing_market_days":remaining_source_dates,
       "scenario_assumed_new_market_quotes_per_day":850,
       "estimated_unfilled_raw_source_extra_bytes":scenario_raw_add_bytes,
       "source_plus_full_derived_projection_bytes":
           projected_full_derived+scenario_raw_add_bytes,
       "selected_preview_stocks":selected,
       "selected_preview_raw_price_rows":selected_price_rows,
       "selected_estimated_rewrite_buffer_bytes":selected_estimated_write_bytes,
       "bounded_preview_passes_free_storage_check":approved_preview_only,
       "manual_derived_recompute_permitted_now":False,
       "must_wait_until_source_campaign_stopped":True,
       "forecast_is_not_guaranteed":True,
       "full_five_year_per_stock_history_verified":False,
       "latest_day_scores_are_not_historical_factor_completeness":True,
       "raw_prices_modified":False,"derived_rows_modified":False,
       "LINE_or_trading_enabled":False,"paid_upgrade_requested":False,
    }

def inspect(url,*,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    # One consistent database snapshot, independent of concurrent writer.
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='45000ms'")
        db_bytes=conn.execute(DB_SIZE_SQL).fetchone()["size_bytes"]
        tables={r["tbl"]:{"rows":r["rows"],"bytes":r["bytes"]}
                for r in conn.execute(TABLE_SQL).fetchall()}
        days=dict(conn.execute(SOURCE_DAYS_SQL).fetchone())
        cohort=[dict(r) for r in conn.execute(MISSING_SQL).fetchall()]
    report=formulate_plan(db_bytes,tables,days,cohort)
    report["schema_version"]=1
    report["checked_at_utc"]=datetime.now(timezone.utc).isoformat()
    report["scope"]="TPEX_FIVE_YEAR_CAPACITY_AND_DERIVED_RECALC_READ_ONLY_PLAN"
    if report_path is not None:
        file=Path(report_path)
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser(description="Read-only five-year TPEx free-capacity and derived debt planning")
    p.add_argument("--report",type=Path,default=Path("tpex-five-year-capacity-plan.json"))
    args=p.parse_args()
    report=inspect(os.getenv("DATABASE_URL",""),report_path=args.report)
    print(json.dumps({key:report[key] for key in (
       "source","database_bytes","headroom_to_internal_safety_stop_bytes",
       "estimated_unfilled_derived_row_counts",
       "estimated_full_derived_catchup_extra_bytes",
       "full_history_derivatives_fit_free_safety_budget_estimate",
       "selected_preview_stocks","manual_derived_recompute_permitted_now"
    )},ensure_ascii=False))

if __name__=="__main__":
    main()
