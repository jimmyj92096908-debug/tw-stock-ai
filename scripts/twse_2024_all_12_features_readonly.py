"""All eligible 2024 current-listed TWSE raw 12-feature/SMA240 audit.

Reuses the previously validated one-cursor official source query but computes
the EXISTING causal technical/SMC 12-vector and exact SMA240 for EVERY
admitted 242-session stock. Validates each stock's previous-day vector
both with and without the next day's bar; verifies per-stock common official
trade dates. No factor rows, OHLCV, labels, weights, trades or LINE outputs.
This is raw *unadjusted* research, NEVER total return or alpha evidence.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path

from scripts.twse_2024_full_market_ma240_readonly import (
    STREAM_SQL, YEAR_START, YEAR_END, EXPECTED_MARKET_DAYS,
    MIN_FULL_STOCKS, MAX_FULL_STOCKS, MAX_TOTAL_ROWS,
)
from scripts.twse_2022_shared_source_stream import _safe_bar
from scripts.twse_stateless_240_monthly_factor import exact_sma240
from src.raw_factor_feature_bridge import (
    FEATURE_NAMES, build_research_features, VERSION,
)


def audit_complete_12_feature_cohort(rows, *, minimum=MIN_FULL_STOCKS):
    if type(minimum) is not int or not 2 <= minimum <= MAX_FULL_STOCKS:
        raise ValueError("Require bounded official cohort count")
    sid = None
    bars = []
    first_stock_days = None
    counts = {"stocks": 0, "bars": 0, "ma240": 0, "vectors": 0,
              "prefix": 0}
    digest = sha256()

    def flush():
        nonlocal first_stock_days
        if len(bars) != EXPECTED_MARKET_DAYS:
            raise ValueError("Issuer lacks full 242 official-stock source sessions")
        dates = tuple(item["trade_date"] for item in bars)
        if len(set(dates)) != EXPECTED_MARKET_DAYS or (
            first_stock_days is not None and dates != first_stock_days
        ):
            raise ValueError("Stock histories do not share same official market dates")
        if first_stock_days is None:
            first_stock_days = dates
        latest_day, prior_day = dates[-1], dates[-2]
        current_sma = exact_sma240(bars, asof=latest_day)
        prev_sma = exact_sma240(bars, asof=prior_day)
        if prev_sma != exact_sma240(bars[:-1], asof=prior_day):
            raise ValueError("Future price contaminated previous-day 240-SMA")
        current = build_research_features(
            bars, market="twse", stock_id=sid,
            cutoff=latest_day, signal_dates=[latest_day])
        future = build_research_features(
            bars, market="twse", stock_id=sid,
            cutoff=latest_day, signal_dates=[prior_day])
        prefix = build_research_features(
            bars[:-1], market="twse", stock_id=sid,
            cutoff=prior_day, signal_dates=[prior_day])
        if (current["included_signals"] != 1
            or future["included_signals"] != 1
            or prefix["included_signals"] != 1
            or tuple(current["feature_names"]) != FEATURE_NAMES
            or future["signals"][0]["feature_vector"] !=
               prefix["signals"][0]["feature_vector"]
            or len(current["signals"][0]["feature_vector"]) != len(FEATURE_NAMES)
            or any(x["live_trading_approved"] for x in
                   (current, future, prefix))):
            raise ValueError("Technical and SMC vector causal or release gate failed")
        # SHA only; never publish issuer, prices or factor vectors.
        digest.update(json.dumps(
            [sid, str(current_sma), str(prev_sma),
             current["signals"][0]["feature_vector"],
             future["signals"][0]["feature_vector"]],
            allow_nan=False, separators=(",", ":"),
        ).encode("utf-8"))
        counts["stocks"] += 1
        counts["ma240"] += 1
        counts["vectors"] += 1
        counts["prefix"] += 1

    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("Original official price row column names required")
        stock = r.get("stock_id")
        day = r.get("trade_date")
        if (not isinstance(stock, str) or len(stock) != 4
            or not stock.isascii() or not stock.isdigit() or stock == "1589"
            or type(day) is not date or not YEAR_START <= day <= YEAR_END):
            raise ValueError("Foreign or excluded historical issuer")
        _safe_bar(r, day=day)
        if sid is not None and stock < sid:
            raise ValueError("Source cursor stock order is not chronological")
        if stock != sid:
            if sid is not None:
                flush()
            sid = stock
            bars = []
            if counts["stocks"] >= MAX_FULL_STOCKS:
                raise ValueError("Unbounded issuer set")
        elif bars and day <= bars[-1]["trade_date"]:
            raise ValueError("Duplicate or unsorted official issuer session")
        bars.append(r)
        counts["bars"] += 1
        if len(bars) > EXPECTED_MARKET_DAYS or counts["bars"] > MAX_TOTAL_ROWS:
            raise ValueError("Unbounded official source stock history")
    if sid is not None:
        flush()
    n = counts["stocks"]
    if (not minimum <= n <= MAX_FULL_STOCKS or
        counts["bars"] != n * EXPECTED_MARKET_DAYS or
        counts["ma240"] != n or counts["vectors"] != n or counts["prefix"] != n):
        raise ValueError("Incomplete true 2024 cohort 12-feature count")
    return {
        "scope": "TWSE_2024_FULL_CURRENT_LISTED_12_FACTOR_PREFIX_ALL_STOCKS",
        "genuine_2024_market_days": len(first_stock_days),
        "eligible_current_listed_stocks": n,
        "official_source_rows_evaluated": counts["bars"],
        "exact_ma240_no_future_checks": counts["ma240"],
        "complete_12_technical_smc_feature_vectors": counts["vectors"],
        "full_12_feature_prior_day_no_future_parity_checks": counts["prefix"],
        "raw_feature_version": VERSION,
        "raw_factor_count": len(FEATURE_NAMES),
        "only_aggregate_source_factor_sha256": digest.hexdigest(),
        "single_existing_official_source_query": True,
        "all_day_date_alignment_verified": True,
        "historical_issuer_survivorship_free": False,
        "corporate_actions_adjusted": False,
        "historical_total_returns_proven": False,
        "independent_forward_cost_stressed_alpha_positive": False,
        "five_year_history_complete": False,
        "neon_price_factor_model_rows_written": 0,
        "public_per_stock_source_or_vector_artifacts": 0,
        "line_messages_sent": 0,
        "live_trading_approved": False,
        "paid_upgrade_requested": False,
    }


def run(database_url, *, output=None):
    if not database_url:
        raise ValueError("Explicit protected read-only Neon URL required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(
        database_url, connect_timeout=20, row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '150000ms'")
        with conn.cursor(name="twse_full_12_feature_2024_readonly") as cur:
            cur.execute(STREAM_SQL, (YEAR_START, YEAR_END, YEAR_START, YEAR_END))
            def records():
                while True:
                    batch = cur.fetchmany(4000)
                    if not batch:
                        break
                    for item in batch:
                        yield dict(item)
            report = audit_complete_12_feature_cohort(records())
    data = json.dumps(report, indent=2, allow_nan=False,
                      ensure_ascii=False) + "\n"
    if len(data.encode()) > 7000:
        raise ValueError("Unbounded public aggregate proof")
    if output:
        file = Path(output)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(data, encoding="utf-8")
    else:
        print(data)
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Complete all 12 raw features for eligible 2024 TWSE issuers")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run(os.environ.get("DATABASE_URL", ""), output=args.output)


if __name__ == "__main__":
    main()
