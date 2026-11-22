"""Full current-survivor TWSE 2024 shared 242-session MA240, streaming READ ONLY.

Unlike the five-stock 2024 canary, this validates the actual 800+ stock
cross-section already safely stored in Neon with ONE ordered server cursor
and a 242-row per-stock memory buffer. Exact Decimal MA240 and five existing
12-feature technical/SMC prefix checks; no derived/price writes or public
stock-level output. Historical non-survivor/delisted issuers remain excluded
and the retrospective model release gate stays BLOCKED.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path

from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE
from scripts.twse_2022_shared_source_stream import _safe_bar, SOURCE_TAG
from scripts.twse_stateless_240_monthly_factor import exact_sma240
from src.raw_factor_feature_bridge import build_research_features, FEATURE_NAMES

YEAR_START = date(2024, 1, 1)
YEAR_END = date(2024, 12, 31)
EXPECTED_MARKET_DAYS = 242
MIN_FULL_STOCKS = 800
MAX_FULL_STOCKS = 1000
MAX_TOTAL_ROWS = 250_000
FEATURE_SPOTCHECK_STOCKS = 5

STREAM_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible_codes AS (
 SELECT p.stock_id
 FROM public.daily_prices p
 JOIN official_current_listed o
   ON o.market=p.market AND o.stock_id=p.stock_id
 JOIN public.stock_master m
   ON m.market=p.market AND m.stock_id=p.stock_id
 WHERE p.market='twse'
   AND p.source='TWSE_MI_INDEX_ALLBUT0999'
   AND p.trade_date BETWEEN %s AND %s
   AND p.stock_id<>'1589'
   AND NOT EXISTS (
     SELECT 1 FROM public.model_stock_exclusions x
     WHERE x.market=p.market AND x.stock_id=p.stock_id
   )
 GROUP BY p.stock_id
 HAVING COUNT(*) = 242 AND
   BOOL_AND(COALESCE(
     p.open > 0 AND p.high >= GREATEST(p.open,p.close) AND
     p.low > 0 AND p.low <= LEAST(p.open,p.close) AND
     p.close > 0 AND p.volume >= 0, FALSE
   ))
)
SELECT p.market,p.stock_id,p.trade_date,p.open,p.high,p.low,p.close,
       p.volume,p.turnover,p.transactions,p.price_change,p.source
FROM public.daily_prices p
JOIN eligible_codes q ON q.stock_id=p.stock_id
WHERE p.market='twse' AND p.source='TWSE_MI_INDEX_ALLBUT0999'
  AND p.trade_date BETWEEN %s AND %s
ORDER BY p.stock_id,p.trade_date
"""


def audit_ordered_stock_rows(rows, *, minimum=MIN_FULL_STOCKS):
    """Memory O(242): retain one stock at a time; no persisted price rows."""
    if type(minimum) is not int or not 2 <= minimum <= MAX_FULL_STOCKS:
        raise ValueError("Invalid source stock-count safety bound")
    previous_stock = None
    current_prices = []
    first_market_dates = None
    stock_count = 0
    row_count = 0
    full_feature_checks = 0
    digest = sha256()

    def flush_one(stock_id, prices):
        nonlocal stock_count, first_market_dates, full_feature_checks
        if len(prices) != EXPECTED_MARKET_DAYS:
            raise ValueError("2024 stock missing an official exchange session")
        days = tuple(x["trade_date"] for x in prices)
        if len(set(days)) != EXPECTED_MARKET_DAYS or (
            first_market_dates is not None and days != first_market_dates
        ):
            raise ValueError("Full-market stock/date calendar does not align")
        if first_market_dates is None:
            first_market_dates = days
        last = days[-1]
        prior = days[-2]
        sma = exact_sma240(prices, asof=last)
        earlier = exact_sma240(prices, asof=prior)
        if earlier != exact_sma240(prices[:-1],asof=prior):
            raise RuntimeError("Full-cohort 240-session SMA read future bars")
        digest.update((stock_id+"|"+str(sma)+"|"+str(earlier)+"\n").encode())

        if full_feature_checks < FEATURE_SPOTCHECK_STOCKS:
            latest = build_research_features(
                prices,stock_id=stock_id,market="twse",cutoff=last,
                signal_dates=[last],
            )
            with_future = build_research_features(
                prices,stock_id=stock_id,market="twse",cutoff=last,
                signal_dates=[prior],
            )
            without_future = build_research_features(
                prices[:-1],stock_id=stock_id,market="twse",cutoff=prior,
                signal_dates=[prior],
            )
            if (latest["included_signals"] != 1
                or with_future["included_signals"] != 1
                or without_future["included_signals"] != 1
                or with_future["signals"][0]["feature_vector"]
                   != without_future["signals"][0]["feature_vector"]
                or len(latest["feature_names"]) != len(FEATURE_NAMES)):
                raise RuntimeError("Full-cohort technical/SMC feature leaked future")
            digest.update(latest["raw_source_fingerprint_sha256"].encode())
            full_feature_checks += 1
        stock_count += 1

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("PostgreSQL source row lacks column names")
        stock = row.get("stock_id")
        day = row.get("trade_date")
        if (not isinstance(stock,str) or len(stock)!=4 or not stock.isascii()
            or not stock.isdigit() or stock=="1589"
            or type(day) is not date or not YEAR_START <= day <= YEAR_END):
            raise ValueError("Foreign, delisted, excluded or wrong-year source stock")
        _safe_bar(row,day=day)
        if previous_stock is not None and stock < previous_stock:
            raise ValueError("Source stream must be sorted by stock/date")
        if stock != previous_stock:
            if previous_stock is not None:
                flush_one(previous_stock,current_prices)
            current_prices=[]
            previous_stock=stock
            if stock_count>=MAX_FULL_STOCKS:
                raise ValueError("Unexpectedly many current official listed stocks")
        elif current_prices and day <= current_prices[-1]["trade_date"]:
            raise ValueError("Duplicate, reversed or invalid exchange trading day")
        current_prices.append(row)
        row_count += 1
        if (len(current_prices) > EXPECTED_MARKET_DAYS
            or row_count > MAX_TOTAL_ROWS):
            raise ValueError("Unbounded market source response")
    if previous_stock is not None:
        flush_one(previous_stock,current_prices)
    if not minimum <= stock_count <= MAX_FULL_STOCKS or (
        row_count != stock_count*EXPECTED_MARKET_DAYS or
        full_feature_checks != FEATURE_SPOTCHECK_STOCKS
    ):
        raise ValueError("Not enough fully verified 2024 official-stock sessions")

    return {
        "schema_version":1,
        "scope":"TWSE_2024_CURRENT_SURVIVORS_800PLUS_FULL_MA240_READONLY",
        "official_source":"TWSE_MI_INDEX_ALLBUT0999",
        "actual_2024_common_market_days":len(first_market_dates),
        "actual_current_listed_stocks_with_all_242_sessions":stock_count,
        "total_official_price_rows_read":row_count,
        "exact_ma240_prefix_parity_stock_count":stock_count,
        "technical_smc_12_feature_prefix_checks":full_feature_checks,
        "first_source_session":first_market_dates[0].isoformat(),
        "last_source_session":first_market_dates[-1].isoformat(),
        "aggregate_stock_ma_and_source_sha256":digest.hexdigest(),
        "single_streaming_readonly_query":True,
        "owner_excluded_1589_and_current_delisted":True,
        "source_bars_present_in_neon_before_test":True,
        "new_2022_missing_source_days_obtained":0,
        "survivorship_free_asof_market_universe":False,
        "dividend_adjusted_total_return_verified":False,
        "independent_model_alpha_validated":False,
        "complete_five_year_model_released":False,
        "neon_price_or_derived_rows_written":0,
        "github_price_or_factor_artifacts_written":0,
        "line_messages_sent":0,
        "live_trading_approved":False,
        "paid_upgrade_requested":False,
    }


def execute(database_url, *, output=None):
    if not database_url:
        raise ValueError("Explicit read-only Neon URL required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(
        database_url,connect_timeout=20,row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '150000ms'")
        with conn.cursor(name="twse_full_market_2024_240_readonly") as cursor:
            cursor.execute(STREAM_SQL,(YEAR_START,YEAR_END,YEAR_START,YEAR_END))
            def source_stream():
                while True:
                    batch=cursor.fetchmany(4000)
                    if not batch:
                        break
                    for r in batch:
                        yield dict(r)
            proof=audit_ordered_stock_rows(source_stream())
    data=json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if len(data.encode())>7000:
        raise RuntimeError("Unbounded public 2024 aggregate receipt")
    if output is None:
        print(data)
    else:
        path=Path(output)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(data,encoding="utf-8")
    return proof


def main():
    parser=argparse.ArgumentParser(
        description="2024 800+ current-listed TWSE 242-day MA240 read-only evidence"
    )
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    execute(os.environ.get("DATABASE_URL",""),output=args.output)


if __name__=="__main__":
    main()
