"""Read-only preflight for five parallel research workstreams.

This is not a repair or model-release job. Every SQL statement is SELECT-only.
Missing evidence blocks release. It does not touch LINE, orders or paid services.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

STOP_BYTES = 800_000_000
RESERVE_BYTES = 50_000_000
WORKSTREAMS = ("incremental_factors", "price_quality",
               "corporate_actions", "free_capacity", "holdout_integrity")

CAPACITY_SQL = """
SELECT pg_database_size(current_database())::bigint AS database_bytes,
       pg_total_relation_size('public.daily_prices')::bigint AS raw_physical_bytes,
       (SELECT count(*)::bigint FROM public.daily_prices) AS raw_rows,
       pg_total_relation_size('public.daily_technicals')::bigint AS factor_physical_bytes,
       (SELECT count(*)::bigint FROM public.daily_technicals) AS factor_rows
"""
QUALITY_SQL = """
SELECT p.market, count(*)::bigint AS rows,
 count(*) FILTER (WHERE p.close IS NULL OR p.open IS NULL)::bigint AS missing_open_close,
 count(*) FILTER (WHERE p.close <= 0 OR p.open <= 0
 OR p.high < p.low OR p.close > p.high OR p.close < p.low
 OR p.volume < 0)::bigint AS invalid_ohlcv,
 count(*) FILTER (WHERE NOT EXISTS (
 SELECT 1 FROM public.model_stock_exclusions x
 WHERE x.market=p.market AND x.stock_id=p.stock_id))::bigint AS eligible_raw_rows,
 count(*) FILTER (WHERE EXISTS (
 SELECT 1 FROM public.model_stock_exclusions x
 WHERE x.market=p.market AND x.stock_id=p.stock_id))::bigint AS excluded_raw_rows
FROM public.daily_prices p GROUP BY p.market ORDER BY p.market
"""
FACTOR_SQL = """
SELECT p.market,
 count(*) FILTER (WHERE p.close>0 AND p.volume>=0)::bigint AS valid_raw_rows,
 count(*) FILTER (WHERE p.close>0 AND p.volume>=0 AND t.trade_date IS NULL)::bigint AS missing_technical_keys,
 count(*) FILTER (WHERE p.close>0 AND p.volume>=0 AND a.trade_date IS NULL)::bigint AS missing_adjusted_keys,
 count(*) FILTER (WHERE p.close>0 AND p.volume>=0 AND s.trade_date IS NULL)::bigint AS missing_smc_keys
FROM public.daily_prices p
LEFT JOIN public.daily_technicals t USING(market,stock_id,trade_date)
LEFT JOIN public.daily_adjusted_prices a USING(market,stock_id,trade_date)
LEFT JOIN public.daily_smc s USING(market,stock_id,trade_date)
WHERE NOT EXISTS (
 SELECT 1 FROM public.model_stock_exclusions x
 WHERE x.market=p.market AND x.stock_id=p.stock_id
)
GROUP BY p.market ORDER BY p.market
"""
ACTION_SQL = """
SELECT count(*)::bigint AS observed_actions,
 count(*) FILTER(WHERE verified=TRUE)::bigint AS verified_actions,
 count(*) FILTER(WHERE verified IS DISTINCT FROM TRUE)::bigint AS unverified_actions,
 count(*) FILTER(WHERE price_factor IS NULL OR price_factor<=0
 OR share_factor IS NULL OR share_factor<=0)::bigint AS invalid_factors
FROM public.corporate_actions
"""
HOLDOUT_SQL = """
SELECT (SELECT count(*)::bigint FROM public.research_forward_frozen_cohorts) AS frozen_cohorts,
 (SELECT max(signal_date) FROM public.research_forward_frozen_cohorts) AS latest_signal,
 (SELECT max(trade_date) FROM public.daily_prices WHERE close>0) AS latest_price,
 (SELECT count(*)::bigint FROM public.backtest_runs
   WHERE status='completed') AS completed_backtest_runs
"""


def evaluate(*, capacity, quality, factors, actions, holdout):
    """Conservative evidence summary, not a claim of independent model alpha."""
    size = int(capacity["database_bytes"])
    raw_rows, factor_rows = int(capacity["raw_rows"]), int(capacity["factor_rows"])
    if size <= 0 or raw_rows <= 0 or factor_rows <= 0:
        raise ValueError("Missing physical storage evidence")
    if set(x["market"] for x in quality) != {"twse", "tpex"} or set(
        x["market"] for x in factors) != {"twse", "tpex"
    }:
        raise ValueError("Incomplete market evidence")
    if len(quality) != 2 or len(factors) != 2:
        raise ValueError("Duplicate market evidence")
    physical_raw = int(capacity["raw_physical_bytes"])
    physical_factor = int(capacity["factor_physical_bytes"])
    if min(physical_raw,physical_factor) <= 0:
        raise ValueError("Invalid measured table size")
    # Index-inclusive historical unit cost; a stress estimate, not a quota promise.
    factor_unit = (physical_factor / factor_rows) * 1.5
    missing_factor_rows = sum(int(x["missing_technical_keys"]) for x in factors)
    projected_existing_factor_cost = round(missing_factor_rows * factor_unit)
    raw_valid = sum(int(x["valid_raw_rows"]) for x in factors)
    invalid = sum(int(x["invalid_ohlcv"]) for x in quality)
    missing_open_close = sum(int(x["missing_open_close"]) for x in quality)
    actions_count = int(actions["observed_actions"])
    verified = int(actions["verified_actions"])
    if any(x < 0 for x in (
        missing_factor_rows,raw_valid,invalid,missing_open_close,
        actions_count,verified,projected_existing_factor_cost
    )) or verified > actions_count:
        raise ValueError("Inconsistent source evidence")
    if missing_factor_rows > raw_valid:
        raise ValueError("Missing factor keys exceed eligible raw observations")
    headroom = STOP_BYTES - size
    return {
        "schema_version": 1,
        "read_only": True,
        "production_repair_performed": False,
        "five_workstreams": {
            "incremental_factors": {
                "missing_technical_keys": missing_factor_rows,
                "valid_price_rows":raw_valid,
                "historical_factor_rebuild_complete":missing_factor_rows==0,
                "note":"Missing keys include warm-up dates; not all require non-null MA240"},
            "price_quality": {
                "invalid_ohlcv":invalid,
                "missing_open_close":missing_open_close,
                "all_raw_rows_quality_verified":invalid==0 and missing_open_close==0},
            "corporate_actions": {
                "observed_actions":actions_count,
                "verified_actions":verified,
                "unverified_actions":int(actions["unverified_actions"]),
                "invalid_factors":int(actions["invalid_factors"]),
                "five_year_vintage_verified":False},
            "free_capacity": {
                "database_bytes":size,
                "headroom_to_internal_stop_bytes":headroom,
                "derived_factor_debt_stress_bytes":projected_existing_factor_cost,
                "existing_factor_debt_fits_with_reserve_ESTIMATE":
                    size+projected_existing_factor_cost+RESERVE_BYTES < STOP_BYTES,
                "warning":size >= STOP_BYTES-RESERVE_BYTES},
            "holdout_integrity": {
                "frozen_cohorts":int(holdout["frozen_cohorts"]),
                "completed_backtest_runs":int(holdout["completed_backtest_runs"]),
                "independent_forward_performance_verified":False,
                "latest_frozen_signal":str(holdout["latest_signal"]),
                "latest_valid_price":str(holdout["latest_price"])}
        },
        "fully_accepted":False,
        "research_only":True,
        "line_changed":False,
        "orders_enabled":False,
        "paid_upgrade_requested":False,
    }


def inspect(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(
        url,connect_timeout=20,row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.execute("SET LOCAL statement_timeout = '45000ms'")
            capacity=dict(conn.execute(CAPACITY_SQL).fetchone())
            quality=[dict(x) for x in conn.execute(QUALITY_SQL).fetchall()]
            factors=[dict(x) for x in conn.execute(FACTOR_SQL).fetchall()]
            actions=dict(conn.execute(ACTION_SQL).fetchone())
            holdout=dict(conn.execute(HOLDOUT_SQL).fetchone())
    report=evaluate(capacity=capacity,quality=quality,factors=factors,
                    actions=actions,holdout=holdout)
    report["checked_at_utc"]=datetime.now(timezone.utc).isoformat()
    return report


if __name__=="__main__":
    print(json.dumps(inspect(os.getenv("DATABASE_URL","")),
                     ensure_ascii=False,indent=2,allow_nan=False))
