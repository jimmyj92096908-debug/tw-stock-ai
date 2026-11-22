"""Expanding purged *retrospective* raw-price research for actual TWSE/TPEx bars.

For each nonoverlapping evaluation window, refit on *only* real forward
labels whose exit preceded the signal. Never use a current signal's future
return to fit its own model. This does not solve survivorship, point-in-time
corporate actions, true source vintage, or pristine forward validation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from hashlib import sha256
import json
import math

import numpy as np

from src.raw_factor_feature_bridge import FEATURE_NAMES, _day
from src.raw_factor_walkforward import (
    MIN_TRAIN_DAYS, MIN_TRAIN_ROWS, RIDGE_LAMBDA, TOP_FRACTION,
    purged_ridge_prototype,
)
from src.research_execution_costs import stress_test


MIN_INDEPENDENT_WINDOWS_FOR_RESEARCH = 10
COST_ASSUMPTIONS = dict(
    fee_bps=14.25,
    sell_tax_bps=30,
    slippage_bps_scenarios=(10, 30, 60),
)


def expanding_purged_research(dataset: dict, *, test_start: date) -> dict:
    """Recompute regression fit per window using only prior matured outcomes."""
    # Reuse the existing strict frozen-cohort, checksum, as-of and label
    # validation. This will fail closed before doing any fitting.
    certified = purged_ridge_prototype(dataset, test_start=test_start)
    evidence = {
        "schema_version": 1,
        "status": "INSUFFICIENT_MATURE_RAW_RESEARCH",
        "dataset_rows_sha256": dataset["rows_sha256"],
        "market": dataset.get("market", "tpex"),
        "research_only": True,
        "training_is_purged_by_actual_exit": True,
        "expanding_refit_uses_only_mature_past_labels": True,
        "nonoverlap_windows": [],
        "count": 0,
        "min_nonoverlap_research_windows": MIN_INDEPENDENT_WINDOWS_FOR_RESEARCH,
        "research_window_count_sufficient": False,
        "mean_illustrative_net_excess_vs_equal_weight": None,
        "price_labels_adjusted_for_dividends": False,
        "historical_issuer_survivorship_audited": False,
        "source_capture_vintage_independently_audited": False,
        "independent_future_validation_passed": False,
        "production_weights_modified": False,
        "neon_database_writes": 0,
        "line_messages_sent": False,
        "trading_approved": False,
    }
    if certified["status"] != "RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY":
        return evidence

    groups: dict[date, list[dict]] = defaultdict(list)
    for item in dataset["rows"]:
        groups[_day(item["as_of_date"])].append(item)
    start = _day(test_start)
    previous_exit = None
    for signal, members in sorted(groups.items()):
        if signal < start or previous_exit is not None and signal <= previous_exit:
            continue
        # Note: older *signals* are not enough. Every earlier label must
        # have already exited strictly before the next evaluation signal.
        train_groups = [
            (day, values) for day, values in sorted(groups.items())
            if day < signal and all(_day(v["exit_date"]) < signal for v in values)
        ]
        if len(train_groups) < MIN_TRAIN_DAYS:
            continue
        samples = [v for _, values in train_groups for v in values]
        if len(samples) < MIN_TRAIN_ROWS:
            continue
        X = np.asarray([v["feature_vector"] for v in samples], dtype=np.float64)
        y = np.asarray([v["raw_unadjusted_gross_return"] for v in samples],
                       dtype=np.float64)
        means = X.mean(axis=0)
        stds = np.where(X.std(axis=0) < 1e-12, 1.0, X.std(axis=0))
        centered = (X - means) / stds
        coefficients = np.linalg.solve(
            centered.T @ centered + RIDGE_LAMBDA * np.eye(len(FEATURE_NAMES)),
            centered.T @ (y - y.mean()),
        )
        if not np.all(np.isfinite(coefficients)):
            raise RuntimeError("Non-finite expanding research model coefficients")
        scaled = (np.asarray([v["feature_vector"] for v in members]) - means) / stds
        ranks = scaled @ coefficients
        count = max(1, math.ceil(len(members) * TOP_FRACTION))
        selected = np.argsort(-ranks, kind="stable")[:count]
        returns = [v["raw_unadjusted_gross_return"] for v in members]
        selected_gross = float(np.mean([returns[i] for i in selected]))
        baseline_gross = float(np.mean(returns))
        net = stress_test(selected_gross, **COST_ASSUMPTIONS)[
            "worst_assumed_net_return"]
        baseline_net = stress_test(baseline_gross, **COST_ASSUMPTIONS)[
            "worst_assumed_net_return"]
        exit_date = _day(members[0]["exit_date"])
        max_train_exit = max(_day(v["exit_date"]) for v in samples)
        if max_train_exit >= signal:
            raise AssertionError("Purged fold contains future or simultaneous label")
        frozen_weights_hash = sha256(
            json.dumps([round(float(x), 12) for x in coefficients],
                       separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        evidence["nonoverlap_windows"].append({
            "signal_date": signal.isoformat(),
            "entry_date": members[0]["entry_date"],
            "exit_date": exit_date.isoformat(),
            "last_mature_training_exit": max_train_exit.isoformat(),
            "training_date_count": len(train_groups),
            "training_row_count": len(samples),
            "training_weights_sha256": frozen_weights_hash,
            "selected_stock_count": count,
            "assumed_cost_net_return": net,
            "equal_weight_assumed_cost_net_return": baseline_net,
            "assumed_net_excess_vs_equal_weight": round(net - baseline_net, 10),
            "verified_executable_orders": False,
        })
        previous_exit = exit_date
    out = evidence["nonoverlap_windows"]
    evidence["count"] = len(out)
    evidence["research_window_count_sufficient"] = (
        len(out) >= MIN_INDEPENDENT_WINDOWS_FOR_RESEARCH
    )
    if out:
        evidence["mean_illustrative_net_excess_vs_equal_weight"] = round(
            float(np.mean([x["assumed_net_excess_vs_equal_weight"] for x in out])),
            10,
        )
        evidence["status"] = "RETROSPECTIVE_EXPANDING_PURGED_RAW_ONLY"
    return evidence
