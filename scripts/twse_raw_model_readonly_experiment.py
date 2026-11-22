"""Bounded TWSE raw-price research model: no Neon derived writes or LINE.

This is an exploratory, unadjusted-price-only twenty-stock cohort. Neither the
saved original Ridge model nor any production score or trading flag changes.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE
from src.raw_factor_feature_bridge import MAX_BARS
from src.raw_factor_walkforward import (
    MAX_SIGNAL_DAYS, frozen_unadjusted_dataset, purged_ridge_prototype,
)

# Frozen, current-official-listed small *research* roster, NOT all-market
# model validation or an as-of historical survivor-free universe.
PROTOTYPE_STOCKS = (
    "1103", "1201", "1216", "1301", "1303",
    "2002", "2207", "2303", "2308", "2317",
    "2327", "2330", "2357", "2379", "2382",
    "2412", "2454", "2603", "2881", "6505",
)
MAX_STOCK_BARS = 400
assert MAX_STOCK_BARS <= MAX_BARS

ROSTER_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT COUNT(*)::int AS eligible
FROM official_current_listed o
WHERE o.market='twse' AND o.stock_id=ANY(%s)
  AND NOT EXISTS (
    SELECT 1 FROM public.model_stock_exclusions x
    WHERE x.market=o.market AND x.stock_id=o.stock_id
  )
"""

PRICE_SQL = """SELECT market,stock_id,trade_date,open,high,low,close,volume,
turnover,price_change,transactions,source
FROM (
 SELECT market,stock_id,trade_date,open,high,low,close,volume,
        turnover,price_change,transactions,source
 FROM public.daily_prices
 WHERE market='twse' AND stock_id=%s AND trade_date<=%s
 ORDER BY trade_date DESC LIMIT %s
) bars ORDER BY trade_date"""

SIGNALS_SQL = """SELECT trade_date FROM public.daily_prices
WHERE market='twse' AND stock_id=%s AND trade_date<=%s
  AND close>0 AND volume>=0
ORDER BY trade_date DESC LIMIT %s"""


def execute(url, *, label_cutoff, test_start, max_signals=90, output_dir=None):
    if (not url or type(label_cutoff) is not date or type(test_start) is not date
            or test_start >= label_cutoff
            or type(max_signals) is not int
            or not 25 <= max_signals <= MAX_SIGNAL_DAYS):
        raise ValueError("Read-only source, ordered dates and bounded signals required")
    if "1589" in PROTOTYPE_STOCKS or len(set(PROTOTYPE_STOCKS)) != len(PROTOTYPE_STOCKS):
        raise ValueError("Research roster violates owner exclusions")
    with psycopg.connect(
        url, connect_timeout=20, row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '50000ms'")
        receipt = conn.execute(ROSTER_SQL, (list(PROTOTYPE_STOCKS),)).fetchone()
        if not receipt or receipt["eligible"] != len(PROTOTYPE_STOCKS):
            raise RuntimeError("Missing, stale or excluded current TWSE official research roster")
        series = {
            sid: [dict(r) for r in conn.execute(
                PRICE_SQL, (sid, label_cutoff, MAX_STOCK_BARS)).fetchall()]
            for sid in PROTOTYPE_STOCKS
        }
        signal_rows = conn.execute(
            SIGNALS_SQL, (PROTOTYPE_STOCKS[0], label_cutoff, max_signals)
        ).fetchall()
    if len(signal_rows) != max_signals:
        raise RuntimeError("Insufficient verified, real TWSE signal sessions")
    dataset = frozen_unadjusted_dataset(
        series,
        signal_dates=[r["trade_date"] for r in signal_rows],
        label_cutoff=label_cutoff,
        market="twse",
    )
    if dataset["accepted_whole_cohort_days"] < 5:
        raise RuntimeError("Insufficient full-roster forward label maturity")
    evaluation = purged_ridge_prototype(dataset, test_start=test_start)
    report = {
        "scope": "TWSE_TWENTY_STOCK_CAUSAL_RAW_RESEARCH_ONLY",
        "feature_version": dataset["feature_version"],
        "included_stocks": len(PROTOTYPE_STOCKS),
        "source_price_rows": dataset["source_row_count"],
        "accepted_whole_cohort_dates": dataset["accepted_whole_cohort_days"],
        "dataset_sha256": dataset["rows_sha256"],
        "development_dates": evaluation["development_dates"],
        "nonoverlapping_holdout_windows": len(evaluation["nonoverlap_test_windows"]),
        "mean_illustrative_net_excess_vs_equal_weight": evaluation.get(
            "mean_illustrative_net_excess_vs_equal_weight"),
        "research_window_count_sufficient": evaluation.get(
            "research_window_count_sufficient", False),
        "identical_illustrative_cost_assumptions_for_benchmark": evaluation.get(
            "benchmark_uses_identical_illustrative_cost_assumptions", False),
        "prototype_status": evaluation["status"],
        "historical_asof_capture_vintage_proven": False,
        "original_historical_exchange_universe_audited": False,
        "dividend_adjusted_total_return_proven": False,
        "independent_future_validation_passed": False,
        "production_tw_factor_ridge_1_unchanged": True,
        "no_derived_database_rows_written": True,
        "neon_read_only": True,
        "line_messages_sent": False,
        "live_trading_approved": False,
        "paid_upgrade_required": False,
    }
    if output_dir is not None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        for filename, value in (
            ("research-dataset.json", dataset),
            ("prototype-walkforward.json", evaluation),
            ("research-safety-evidence.json", report),
        ):
            (output / filename).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
    return report


def main():
    p = argparse.ArgumentParser(description="TWSE twenty-stock read-only raw research")
    p.add_argument("--label-cutoff", type=date.fromisoformat, required=True)
    p.add_argument("--test-start", type=date.fromisoformat, required=True)
    p.add_argument("--max-signal-days", type=int, default=90)
    p.add_argument("--output-dir", type=Path, default=Path("twse-raw-research-proof"))
    args = p.parse_args()
    print(json.dumps(execute(
        os.getenv("DATABASE_URL", ""),
        label_cutoff=args.label_cutoff,
        test_start=args.test_start,
        max_signals=args.max_signal_days,
        output_dir=args.output_dir,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
