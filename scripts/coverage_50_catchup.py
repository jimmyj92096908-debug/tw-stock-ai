"""Owner-authorized, one-time bounded path to >=50% *current* stock analysis coverage.

Uses verified existing indicator / SMC calculators, each capped at 20 stocks
per market per batch. Reads are exact last positive closing-price dates.
No raw price writes, fictitious bars, LINE sends, model trade approval or orders.
A failed invariant stops further batches, preserving evidence of prior batches.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from batch_indicator_catchup import run as batch_run  # noqa: E402
from composite_score import calculate_all  # noqa: E402

TARGET_PERCENT = 50
PER_MARKET = 20
MAX_ROUNDS = 55

COVERAGE_SQL = """
WITH priced AS (
 SELECT market,stock_id,MAX(trade_date) AS last_close
 FROM public.daily_prices WHERE close > 0
 GROUP BY market,stock_id
), complete AS (
 SELECT p.market,p.stock_id,
 EXISTS(SELECT 1 FROM public.daily_technicals t
        WHERE t.market=p.market AND t.stock_id=p.stock_id
          AND t.trade_date=p.last_close) AS technical,
 EXISTS(SELECT 1 FROM public.daily_smc s
        WHERE s.market=p.market AND s.stock_id=p.stock_id
          AND s.trade_date=p.last_close) AS smc,
 EXISTS(SELECT 1 FROM public.daily_composite_scores c
        WHERE c.market=p.market AND c.stock_id=p.stock_id
          AND c.as_of_date=p.last_close AND c.total_score IS NOT NULL) AS scored
 FROM priced p
)
SELECT
 (SELECT COUNT(*)::int FROM public.stock_master) AS universe,
 (SELECT COUNT(*)::int FROM priced) AS priced,
 (SELECT COUNT(*)::bigint FROM public.daily_prices) AS price_rows,
 (SELECT MAX(trade_date) FROM public.daily_prices WHERE close>0) AS latest_price_date,
 COUNT(*) FILTER (WHERE technical)::int AS technical_current,
 COUNT(*) FILTER (WHERE smc)::int AS smc_current,
 COUNT(*) FILTER (WHERE technical AND smc)::int AS both_current,
 COUNT(*) FILTER (WHERE scored)::int AS scored_current
FROM complete
"""


def read_snapshot(url: str) -> dict:
    """Separate repeatable read-only snapshot; never a writable cursor."""
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=20) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        row = dict(conn.execute(COVERAGE_SQL).fetchone())
    if not row["universe"] or not row["latest_price_date"]:
        raise ValueError("No verified price universe")
    row["latest_price_date"] = str(row["latest_price_date"])
    return row


def target_count(universe: int) -> int:
    if type(universe) is not int or universe <= 0:
        raise ValueError("Invalid stock universe")
    return math.ceil(universe * TARGET_PERCENT / 100)


def assert_stable_and_progress(previous: dict, current: dict, *, require_progress=True) -> None:
    """Never interpret market data movement, new symbols or lost coverage as success."""
    for field in ("universe", "price_rows", "latest_price_date"):
        if current[field] != previous[field]:
            raise RuntimeError("Market source or universe changed during catch-up: " + field)
    for field in ("technical_current", "smc_current", "both_current", "scored_current"):
        if current[field] < previous[field]:
            raise RuntimeError("Coverage regressed during catch-up: " + field)
    if require_progress and current["both_current"] <= previous["both_current"]:
        raise RuntimeError("No verifiable newest-session technical+SMC coverage gain")


def checkpoint(path: Path | None, report: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_coverage(url: str, *, apply: bool = False, max_rounds: int = 0,
                 report_path: Path | None = None) -> dict:
    if not url:
        raise ValueError("DATABASE_URL is required")
    if max_rounds < 0 or max_rounds > MAX_ROUNDS:
        raise ValueError("max_rounds exceeds bounded production limit")
    # Never let an accidental preview flag authorize writes.
    if apply and (
        max_rounds < 1
        or os.environ.get("STOCK_50_COVERAGE_WRITE_ENABLED") != "yes"
        or os.environ.get("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED") != "yes"
    ):
        raise ValueError("Explicit owner-authorized production write gates required")

    baseline = read_snapshot(url)
    target = target_count(baseline["universe"])
    report = {
        "schema_version": 1,
        "target_percent": TARGET_PERCENT,
        "target_stock_count": target,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline": baseline,
        "latest": baseline,
        "batch_rounds": [],
        "indicator_writes_attempted": False,
        "score_rebuild_attempted": False,
        "target_verified": False,
        "line_webhook_changed": False,
        "trade_signals_enabled": False,
    }
    checkpoint(report_path, report)
    if not apply:
        return report

    previous = baseline
    while previous["both_current"] < target and len(report["batch_rounds"]) < max_rounds:
        # The existing routine enforces per-stock savepoint rollback and
        # per-market <=20; a failed stock must stop the next round.
        results = batch_run(url, apply=True, per_market=PER_MARKET)
        report["indicator_writes_attempted"] = True
        verified = sum(item["status"] == "verified" for item in results)
        failed = sum(item["status"] == "failed" for item in results)
        current = read_snapshot(url)
        report["latest"] = current
        report["batch_rounds"].append({
            "round": len(report["batch_rounds"]) + 1,
            "selected": len(results),
            "verified": verified,
            "failed": failed,
            "both_before": previous["both_current"],
            "both_after": current["both_current"],
        })
        checkpoint(report_path, report)
        if failed or verified == 0:
            raise RuntimeError("Bounded verified indicator batch failed or made no progress")
        assert_stable_and_progress(previous, current)
        previous = current

    if previous["both_current"] < target:
        raise RuntimeError("Hard round cap reached before 50% indicator coverage")

    report["score_rebuild_attempted"] = True
    checkpoint(report_path, report)
    report["scored_candidates_processed"] = calculate_all(url)
    final = read_snapshot(url)
    assert_stable_and_progress(previous, final, require_progress=False)
    report["latest"] = final
    report["target_verified"] = final["scored_current"] >= target and final["both_current"] >= target
    checkpoint(report_path, report)
    if not report["target_verified"]:
        raise RuntimeError("Final latest-day valid composite score coverage is still below 50%")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Guarded 50 percent research coverage catch-up")
    parser.add_argument("--apply", action="store_true",
                        help="Require both production write environment gates")
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--report", type=Path, default=Path("coverage-50-evidence.json"))
    args = parser.parse_args()
    result = run_coverage(os.environ.get("DATABASE_URL", ""), apply=args.apply,
                          max_rounds=args.max_rounds, report_path=args.report)
    current = result["latest"]
    print("Current valid close-day coverage: "
          f"technicals {current['technical_current']}, SMC {current['smc_current']}, "
          f"both {current['both_current']}, valid scores {current['scored_current']}"
          f" / {current['universe']}; target {result['target_stock_count']}")
    print("Target independently verified:", result["target_verified"])
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### One-time 50% latest-session coverage validation\n")
            handle.write(f"- Valid composite scores: {current['scored_current']} / "
                         f"{current['universe']} (target {result['target_stock_count']})\n")
            handle.write(f"- Verified target: {result['target_verified']}\n")
            handle.write(f"- Bounded batch rounds: {len(result['batch_rounds'])}\n")
            handle.write("- No LINE changes, fabricated prices or trading activation.\n")


if __name__ == "__main__":
    main()
