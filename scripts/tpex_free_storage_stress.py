"""Strict read-only Neon Free capacity stress planning, never DB writes.

Projects the observed price-table footprint and index-inclusive derivative
cost under stated 700/850/900 new daily-quote scenarios. This is a stress
scenario, NOT proof of security/IPO status or future table compression.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

STOP_BYTES=800_000_000
RESERVE_BYTES=50_000_000
ROW_SAFETY_MULTIPLIER=1.50
ASSUMED_NEW_QUOTES_PER_DAY=(700,850,900)
REQUIRED_TABLES=("daily_prices","daily_adjusted_prices","daily_technicals","daily_smc")

TABLE_SQL="""SELECT 'daily_prices' AS tbl,COUNT(*)::bigint AS n,
pg_total_relation_size('public.daily_prices')::bigint AS bytes
FROM public.daily_prices
UNION ALL SELECT 'daily_adjusted_prices',COUNT(*)::bigint,
pg_total_relation_size('public.daily_adjusted_prices')::bigint
FROM public.daily_adjusted_prices
UNION ALL SELECT 'daily_technicals',COUNT(*)::bigint,
pg_total_relation_size('public.daily_technicals')::bigint
FROM public.daily_technicals
UNION ALL SELECT 'daily_smc',COUNT(*)::bigint,
pg_total_relation_size('public.daily_smc')::bigint
FROM public.daily_smc"""
SOURCE_SQL="""WITH latest AS (
 SELECT MAX(trade_date) AS latest_session FROM public.daily_prices
 WHERE market='tpex' AND close>0
), day_count AS (
 SELECT p.trade_date,
 COUNT(*) FILTER(WHERE p.close>0 AND p.volume>=0)::int AS anchored,
 COUNT(*) FILTER(WHERE p.close>0 AND p.volume>=0
  AND p.source='TPEX_DATED_OTC_EW')::int AS dated,
 COUNT(*) FILTER(WHERE p.close>0 AND p.volume>=0
  AND p.source='TPEX_DAILY_CLOSE_OPENAPI')::int AS openapi
 FROM public.daily_prices p CROSS JOIN latest l
 WHERE p.market='tpex' AND
 p.trade_date>=l.latest_session-interval '5 years' AND
 p.trade_date<=l.latest_session GROUP BY p.trade_date
)
SELECT COUNT(*) FILTER(WHERE anchored>=10)::int AS observed_anchored_days,
 COUNT(*) FILTER(WHERE anchored>=10 AND GREATEST(dated,openapi)>=500)::int AS covered_days,
 COUNT(*) FILTER(WHERE anchored>=10 AND GREATEST(dated,openapi)<500)::int AS incomplete_days
 FROM day_count"""
DEBT_SQL="""SELECT
 (SELECT COUNT(*)::bigint FROM public.daily_prices
  WHERE market='tpex') AS raw_prices,
 (SELECT COUNT(*)::bigint FROM public.daily_adjusted_prices
  WHERE market='tpex') AS adjusted,
 (SELECT COUNT(*)::bigint FROM public.daily_technicals
  WHERE market='tpex') AS technical,
 (SELECT COUNT(*)::bigint FROM public.daily_smc
  WHERE market='tpex') AS smc"""
CAPACITY_SQL="SELECT pg_database_size(current_database())::bigint AS bytes"

def _assert_int(value,field,minimum=0):
    if type(value) is not int or value<minimum:
        raise ValueError("Invalid audited count: "+field)
    return value

def forecast(*,db_bytes,tables,source,debts):
    _assert_int(db_bytes,"database_bytes",1)
    if set(tables)!=set(REQUIRED_TABLES):
        raise ValueError("Missing per-table index-inclusive physical size evidence")
    cost={}
    physical={}
    for table in REQUIRED_TABLES:
        item=tables[table]
        n=_assert_int(item.get("n"),table+".rows",1)
        bytes_=_assert_int(item.get("bytes"),table+".bytes",n)
        physical[table]={"n":n,"bytes":bytes_}
        cost[table]=math.ceil(bytes_/n*ROW_SAFETY_MULTIPLIER)
    known=_assert_int(source.get("observed_anchored_days"),"anchored")
    complete=_assert_int(source.get("covered_days"),"covered")
    missing=_assert_int(source.get("incomplete_days"),"missing")
    if not known or complete+missing!=known:
        raise ValueError("Actual known date source counts do not reconcile")
    all_prices=_assert_int(debts.get("raw_prices"),"raw_prices",1)
    missing_derived={}
    for column in ("adjusted","technical","smc"):
        n=_assert_int(debts.get(column),column)
        if n>all_prices:
            raise ValueError("Unreconciled derived price count")
        missing_derived[column]=all_prices-n
    # These are a LOWER BOUND on truly missing derived row keys: a surplus
    # on one stock cannot certify another missing stock/date is complete.
    derived_tables={"adjusted":"daily_adjusted_prices",
                    "technical":"daily_technicals","smc":"daily_smc"}
    current_derived_debt_floor=sum(
        missing_derived[k]*cost[table] for k,table in derived_tables.items())
    scenarios=[]
    derived_per_future_row=sum(cost[x] for x in derived_tables.values())
    for ticker_assumption in ASSUMED_NEW_QUOTES_PER_DAY:
        new_rows=ticker_assumption*missing
        raw_growth=new_rows*cost["daily_prices"]
        factors_growth=new_rows*derived_per_future_row
        source_after=db_bytes+raw_growth
        all_after=source_after+factors_growth+current_derived_debt_floor
        scenarios.append({
            "new_quotes_per_unfilled_market_day_ASSUMPTION":ticker_assumption,
            "remaining_anchored_source_days":missing,
            "new_source_price_rows_STRESS":new_rows,
            "projected_source_only_bytes":source_after,
            "projected_all_daily_factor_bytes":all_after,
            "source_only_fits_with_reserve_ESTIMATE":
                source_after+RESERVE_BYTES<STOP_BYTES,
            "all_daily_factors_fit_with_reserve_ESTIMATE":
                all_after+RESERVE_BYTES<STOP_BYTES,
            "source_only_headroom_after_reserve_bytes":
                STOP_BYTES-RESERVE_BYTES-source_after,
            "all_factors_headroom_after_reserve_bytes":
                STOP_BYTES-RESERVE_BYTES-all_after
        })
    if db_bytes>=STOP_BYTES:
        alert="STOP"
    elif db_bytes>=STOP_BYTES-RESERVE_BYTES:
        alert="CRITICAL"
    elif db_bytes>=int(STOP_BYTES*.8):
        alert="WARNING"
    else:
        alert="BELOW_INTERNAL_ALERT"
    return {
        "scope":"TPEX_FIVE_YEAR_FREE_STRESS_NO_DATABASE_WRITES",
        "schema_version":1,
        "database_bytes":db_bytes,
        "free_safety_stop_bytes":STOP_BYTES,
        "reserved_maintenance_margin_bytes":RESERVE_BYTES,
        "actual_headroom_to_stop_bytes":STOP_BYTES-db_bytes,
        "capacity_alert_level":alert,
        "tpex_market_date_source":dict(source),
        "index_inclusive_physical_size":physical,
        "conservative_new_row_bytes":cost,
        "missing_derived_row_count_LOWER_BOUND":missing_derived,
        "existing_factor_debt_bytes_LOWER_BOUND_STRESS":current_derived_debt_floor,
        "scenario_assumptions_not_historical_ipo_truth":True,
        "scenarios":scenarios,
        "source_only_overflow_under_max_stress":
            not scenarios[-1]["source_only_fits_with_reserve_ESTIMATE"],
        "materialize_all_daily_factors_safe_under_max_stress":
            scenarios[-1]["all_daily_factors_fit_with_reserve_ESTIMATE"],
        "recommend_materialize_all_historical_factors_now":False,
        "projection_is_not_capacity_guarantee":True,
        "hard_source_write_guard_is_separate":True,
        "database_read_only":True,"LINE_or_trading_enabled":False,
        "paid_plan_upgrade_requested":False,
    }

def inspect(url,*,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='60000ms'")
        db=int(conn.execute(CAPACITY_SQL).fetchone()["bytes"])
        tables={r["tbl"]:{"n":int(r["n"]),"bytes":int(r["bytes"])}
                for r in conn.execute(TABLE_SQL).fetchall()}
        source=dict(conn.execute(SOURCE_SQL).fetchone())
        debts=dict(conn.execute(DEBT_SQL).fetchone())
    report=forecast(db_bytes=db,tables=tables,source=source,debts=debts)
    report["checked_at_utc"]=datetime.now(timezone.utc).isoformat()
    if report_path is not None:
        file=Path(report_path)
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    return report

def main():
    import argparse
    p=argparse.ArgumentParser(description="Strict read-only TPEx five-year physical storage stress")
    p.add_argument("--report",type=Path,default=Path("tpex-free-stress.json"))
    a=p.parse_args()
    r=inspect(os.getenv("DATABASE_URL",""),report_path=a.report)
    print(json.dumps({k:r[k] for k in (
        "database_bytes","capacity_alert_level",
        "tpex_market_date_source","scenarios",
        "materialize_all_daily_factors_safe_under_max_stress",
        "database_read_only")},ensure_ascii=False))
    if r["capacity_alert_level"] in ("STOP","CRITICAL"):
        raise SystemExit("Neon Free headroom < 50 MB: reject further derived batches")

if __name__=="__main__":
    main()
