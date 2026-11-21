"""Strictly retrospective walk-forward diagnostics for the frozen Ridge research design.

Each fold retrains only on dates whose *full forward label* matured before
that fold's first signal. Test holding windows are non-overlapping across
folds. Re-evaluating old dates is NOT a pristine future holdout and cannot
approve trades. Offline only: caller supplies verified historical research rows.
"""
from __future__ import annotations

from datetime import date
import math

from src.research_risk import nonoverlapping_path
from src.trained_factor_model import (
    COST_BPS, MIN_TRAIN_DATES, MIN_TRAIN_ROWS, TOP_FRACTION,
    _baseline_order, _model_order, fit_development, groups_from_rows, iso_day,
    number,
)


def _evaluate(date_str: str, members: list[dict], artifact: dict,
              *, verified_benchmark_returns: dict | None) -> dict:
    n = len(members)
    k = max(1, math.ceil(n * TOP_FRACTION))
    model_top = _model_order(members, artifact["weights"])[:k]
    original_top = _baseline_order(members)[:k]
    universe = sum(x["return"] for x in members)/n
    model_ret = sum(members[i]["return"] for i in model_top)/k - COST_BPS/10000
    original_ret = sum(members[i]["return"] for i in original_top)/k - COST_BPS/10000
    # All securities' exits must be known before another non-overlapping
    # research holding period can start.
    exit_date = max(x["exit_date"] for x in members)
    result = {"signal_date": date_str, "exit_date": exit_date,
              "universe_count": n, "selected_count": k,
              "net_return": round(model_ret, 10),
              "excess_vs_universe": round(model_ret-universe, 10),
              "baseline_net_return": round(original_ret, 10)}
    if verified_benchmark_returns is not None and date_str in verified_benchmark_returns:
        # A signal-date-only scalar is insufficient: the model enters at
        # next-session close, NOT at the signal-date close. Halt comparison
        # unless each constituent has the same actual entry and exit dates.
        benchmark = verified_benchmark_returns[date_str]
        if not isinstance(benchmark, dict):
            raise ValueError("Benchmark must have exact entry_date, exit_date and net_return")
        entry_dates = {m.get("entry_date") for m in members}
        exit_dates = {m["exit_date"] for m in members}
        if len(entry_dates) != 1 or None in entry_dates or len(exit_dates) != 1:
            raise ValueError("Cannot align a benchmark to differing security entry or exit dates")
        entry_date = next(iter(entry_dates))
        exit_date_exact = next(iter(exit_dates))
        if (benchmark.get("entry_date") != entry_date or
                benchmark.get("exit_date") != exit_date_exact):
            raise ValueError("Benchmark entry/exit dates do not match the research holding window")
        bench_value = benchmark.get("net_return")
        bench_return = number(bench_value)
        if isinstance(bench_value, bool) or bench_return is None or bench_return < -1:
            raise ValueError("Benchmark net_return must be a finite decimal >= -1")
        result["benchmark_net_return"] = bench_return
        result["benchmark_entry_date"] = entry_date
        result["benchmark_exit_date"] = exit_date_exact
    return result


def walk_forward_diagnostics(rows: list[dict], *, first_test_date: str,
                             fold_signals: int = 3, max_folds: int = 12,
                             verified_benchmark_returns: dict | None = None) -> dict:
    if not isinstance(rows, list) or not rows:
        raise ValueError("Verified historical research rows required")
    if type(fold_signals) is not int or not 1 <= fold_signals <= 10:
        raise ValueError("fold_signals must be between 1 and 10")
    if type(max_folds) is not int or not 1 <= max_folds <= 24:
        raise ValueError("max_folds must be between 1 and 24")
    if verified_benchmark_returns is not None and not isinstance(verified_benchmark_returns, dict):
        raise ValueError("Verified benchmark mapping required")
    try:
        first = iso_day(first_test_date)
        available = sorted({iso_day(x["as_of_date"]) for x in rows if x.get("as_of_date")})
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Invalid research date") from exc
    folds = []
    outcomes = []
    skipped = 0
    last_exit = None
    for fold_start in available:
        if fold_start < first or (last_exit is not None and fold_start <= last_exit):
            continue
        groups, exclusions = groups_from_rows(rows, holdout_start=fold_start)
        development = groups["development"]
        if len(development) < MIN_TRAIN_DATES or sum(len(x) for _, x in development) < MIN_TRAIN_ROWS:
            skipped += 1
            continue
        # Never admit a development label that exits on/after test start.
        for _, members in development:
            if any(m["exit_date"] >= fold_start for m in members):
                raise AssertionError("Training label not mature before fold start")
        artifact = fit_development(development)
        fold_outcomes = []
        window_exit = last_exit
        for day, members in groups["holdout"]:
            if day < fold_start or (window_exit is not None and day <= window_exit):
                continue
            event = _evaluate(day, members, artifact,
                              verified_benchmark_returns=verified_benchmark_returns)
            fold_outcomes.append(event)
            window_exit = event["exit_date"]
            if len(fold_outcomes) == fold_signals:
                break
        if not fold_outcomes:
            continue
        outcomes.extend(fold_outcomes)
        last_exit = window_exit
        folds.append({
            "train_through": development[-1][0],
            "first_test_date": fold_outcomes[0]["signal_date"],
            "last_test_date": fold_outcomes[-1]["signal_date"],
            "train_exit_before_first_test": True,
            "train_dates": len(development),
            "train_rows": sum(len(x) for _, x in development),
            "train_fingerprint": artifact["development_sha256"],
            "test_signals": len(fold_outcomes),
            "excluded": exclusions,
        })
        if len(folds) == max_folds:
            break
    risk = nonoverlapping_path(outcomes)
    return {
        "schema_version": 1,
        "research_status": ("RETROSPECTIVE_WALK_FORWARD_ONLY"
                            if folds else "INSUFFICIENT_MATURE_TRAINING_AND_TEST_HISTORY"),
        "folds": folds,
        "tested_windows": outcomes,
        "nonoverlapping_risk": risk,
        "skipped_insufficient_training_dates": skipped,
        "benchmark_status": (
            "PERIOD_ALIGNED_USER_SUPPLIED" if risk["external_benchmark_complete"]
            else "PARTIAL_PERIOD_ALIGNED_USER_SUPPLIED"
            if verified_benchmark_returns else "NOT_PROVIDED"
        ),
        "external_benchmark_provenance_independently_verified": False,
        "pristine_future_holdout_proven": False,
        "transaction_cost_bps_per_round_trip": COST_BPS,
        "caveats": [
            "Historic fold reuse does not establish an untouched future holdout",
            "Frozen design only; model changes require entirely new untouched test dates",
            "Equal-weight cohort is not the Taiwan Weighted Index",
            "External benchmark data are user supplied and not independently source-verified by this offline tool",
            "Benchmark windows must match actual next-session entry and each member's exit date",
            "Missing future adjusted labels exclude whole date cohorts",
            "Delisted stock, liquidity, slippage and corporate action biases remain",
        ],
        "orders_enabled": False,
        "line_trade_signals_enabled": False,
    }
