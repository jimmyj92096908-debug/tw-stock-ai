"""One shared official TWSE date panel -> five independent 240-session factors.

Reads ONLY 2024 official TWSE MI_INDEX source rows already verified in Neon:
one bounded SQL query and a single immutable READ ONLY snapshot, never
materializes historical prices, adjusted bars, factor rows or scores.
Strictly current-listed, user-allowed fixed cohort (no 1589/delisted).
The five-stock *2024 read-only* fanout is a proof of shared daily-source
architecture, NOT new 2022 source coverage or all-market readiness.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path

from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE
from src.raw_factor_feature_bridge import FEATURE_NAMES, build_research_features
from scripts.twse_stateless_240_monthly_factor import exact_sma240

COHORT = ("1301", "1303", "1402", "2317", "2454")
YEAR_START = date(2024, 1, 1)
YEAR_END = date(2024, 12, 31)
EXPECTED_SESSIONS = 242
MIN_WARMUP = 240
MAX_TOTAL_ROWS = 5 * 250
OFFICIAL_SOURCE = "TWSE_MI_INDEX_ALLBUT0999"

OFFICIAL_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
, allowed AS (
 SELECT o.stock_id FROM official_current_listed o
 JOIN public.stock_master m ON m.market=o.market AND m.stock_id=o.stock_id
 WHERE o.market='twse' AND o.stock_id=ANY(%s)
   AND o.stock_id<>'1589'
   AND NOT EXISTS (
    SELECT 1 FROM public.model_stock_exclusions x
    WHERE x.market=o.market AND x.stock_id=o.stock_id
   )
)
SELECT p.market,p.stock_id,p.trade_date,p.open,p.high,p.low,p.close,
       p.volume,p.turnover,p.price_change,p.transactions,p.source
FROM public.daily_prices p JOIN allowed a ON a.stock_id=p.stock_id
WHERE p.market='twse' AND p.source='TWSE_MI_INDEX_ALLBUT0999'
  AND p.trade_date BETWEEN %s AND %s
ORDER BY p.trade_date,p.stock_id
LIMIT %s
"""


def validate_shared_panel(rows):
    """Reject missing, duplicate, cross-date, excluded or inconsistent bars."""
    if (not isinstance(rows, list)
        or len(rows) != EXPECTED_SESSIONS * len(COHORT)
        or len(rows) > MAX_TOTAL_ROWS):
        raise ValueError("Incomplete fixed five-stock 242-day official panel")
    by_stock = {s: [] for s in COHORT}
    dates = set()
    previous = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Official source row must have actual field names")
        sid, day = row.get("stock_id"), row.get("trade_date")
        if (sid not in by_stock or sid == "1589" or type(day) is not date
            or not YEAR_START <= day <= YEAR_END
            or row.get("market") != "twse"
            or row.get("source") != OFFICIAL_SOURCE):
            raise ValueError("Mixed or unapproved stock, date or official source")
        key = (day, sid)
        if previous is not None and key <= previous:
            raise ValueError("Duplicate or unsorted date and stock in shared panel")
        previous = key
        values = (row.get("open"),row.get("high"),
                  row.get("low"),row.get("close"))
        if (any(type(v) is not Decimal or not v.is_finite() or v <= 0
                for v in values)
            or not values[2] <= min(values[0], values[3])
                 <= max(values[0], values[3]) <= values[1]
            or type(row.get("volume")) is not int or row["volume"] < 0):
            raise ValueError("Invalid exact Decimal OHLC or volume in official panel")
        dates.add(day)
        by_stock[sid].append(row)
    if len(dates) != EXPECTED_SESSIONS:
        raise ValueError("Missing official market session date")
    common = sorted(dates)
    for sid in COHORT:
        if [x["trade_date"] for x in by_stock[sid]] != common:
            raise ValueError("Stocks have different official trading session dates")
    return by_stock, common


def audit_shared_240(rows):
    """Reuse audited causal feature bridge per stock, never persist vectors."""
    by_stock, days = validate_shared_panel(rows)
    reports = []
    for sid in COHORT:
        prices = by_stock[sid]
        latest_day, prior_day = days[-1], days[-2]
        now = exact_sma240(prices, asof=latest_day)
        previous = exact_sma240(prices, asof=prior_day)
        if previous != exact_sma240(prices[:-1], asof=prior_day):
            raise RuntimeError("Shared SMA240 uses future source information")
        actual = build_research_features(prices,stock_id=sid,market="twse",
                                         cutoff=latest_day,signal_dates=[latest_day])
        previous_inclusive = build_research_features(
            prices,stock_id=sid,market="twse",
            cutoff=latest_day,signal_dates=[prior_day])
        previous_prefix = build_research_features(
            prices[:-1],stock_id=sid,market="twse",
            cutoff=prior_day,signal_dates=[prior_day])
        if (actual["included_signals"] != 1
            or previous_inclusive["included_signals"] != 1
            or previous_prefix["included_signals"] != 1
            or previous_inclusive["signals"][0]["feature_vector"]
               != previous_prefix["signals"][0]["feature_vector"]
            or actual["feature_names"] != list(FEATURE_NAMES)):
            raise RuntimeError("Multi-stock 240-session feature vector has future leakage")
        reports.append((
            sid, str(now),str(previous),
            actual["raw_source_fingerprint_sha256"],
            actual["signals"][0]["feature_vector"],
        ))
    proof = sha256(json.dumps(reports,ensure_ascii=False,sort_keys=True,
                             separators=(",",":"),allow_nan=False).encode()).hexdigest()
    return {
        "schema_version":1,
        "scope":"TWSE_FIVE_STOCK_SHARED_2024_OFFICIAL_240_SESSION_READONLY_RESEARCH",
        "shared_official_market_dates":len(days),
        "first_official_date":days[0].isoformat(),
        "latest_official_date":days[-1].isoformat(),
        "current_listed_eligible_stocks_verified":len(COHORT),
        "source_stock_rows_consumed":len(rows),
        "source_gets_or_sql_queries_for_all_stocks":1,
        "causal_240_session_sma_checks":len(reports),
        "causal_technical_smc_vector_checks":len(reports),
        "existing_raw_feature_count":len(FEATURE_NAMES),
        "aggregate_private_source_feature_sha256":proof,
        "shared_panel_exact_stock_date_alignment_verified":True,
        "excluded_1589_and_delisted_stocks":True,
        "neon_source_is_already_saved_not_new_2022_replay":True,
        "missing_2022_bulk_market_sessions_fetched":0,
        "historical_original_issuer_universe_audited":False,
        "dividend_adjusted_total_return_proven":False,
        "independent_future_alpha_validated":False,
        "all_market_five_year_factor_coverage_proven":False,
        "neon_price_and_derived_rows_written":0,
        "public_raw_price_or_factor_rows_written":0,
        "line_messages_sent":0,
        "model_live_trading_approved":False,
        "paid_upgrade_requested":False,
    }


def execute(database_url, *, output=None):
    if not database_url:
        raise ValueError("Explicit Neon read-only connection required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(
        database_url,connect_timeout=20,row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '60000ms'")
        rows = [dict(x) for x in conn.execute(
            OFFICIAL_SQL,(list(COHORT),YEAR_START,YEAR_END,MAX_TOTAL_ROWS+1)
        ).fetchall()]
    result = audit_shared_240(rows)
    data = json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False) + "\n"
    if len(data.encode("utf-8")) > 5000:
        raise ValueError("Unbounded research output")
    if output:
        path=Path(output)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(data,encoding="utf-8")
    else:
        print(data)
    return result


def main():
    parser=argparse.ArgumentParser(description="Read-only five-stock shared TWSE factor")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    execute(os.environ.get("DATABASE_URL",""),output=args.output)


if __name__=="__main__":
    main()
