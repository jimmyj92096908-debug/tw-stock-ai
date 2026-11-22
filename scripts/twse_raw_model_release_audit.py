"""Independent *offline* model gate for current TWSE 20-stock research artifacts.

The research split was already examined and labels are unadjusted. This
audit can only BLOCK release. It does not create research weights, publish
trade picks, modify Neon, or send LINE messages.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path

from src.model_release_acceptance import evaluate_release

REPORT_SCOPE = "TWSE_TWENTY_STOCK_CAUSAL_RAW_RESEARCH_ONLY"
FIXED_STATUS = "RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY"
EXPANDING_STATUS = "RETROSPECTIVE_EXPANDING_PURGED_RAW_ONLY"
REQUIRED_WINDOWS = 10


def _numeric(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Missing finite " + name)
    return float(value)


def _windows(windows, metric):
    if not isinstance(windows, list) or not windows:
        raise ValueError("Missing actual purged research windows")
    prev_exit = None
    observed = []
    for w in windows:
        if not isinstance(w, dict):
            raise ValueError("Research window was not an object")
        try:
            signal = date.fromisoformat(w["signal_date"])
            entry = date.fromisoformat(w["entry_date"])
            exit_day = date.fromisoformat(w["exit_date"])
        except (ValueError, TypeError, KeyError) as e:
            raise ValueError("Invalid real holding window dates") from e
        if not signal < entry < exit_day or (
            prev_exit is not None and signal <= prev_exit
        ):
            raise ValueError("Overlapping, noncausal or reversed holding window")
        if "last_mature_training_exit" in w and (
            date.fromisoformat(w["last_mature_training_exit"]) >= signal
        ):
            raise ValueError("Unpurged expanding regression training labels")
        observed.append(_numeric(w.get(metric), "window excess return"))
        prev_exit = exit_day
    return observed


def review(probe, fixed, expanding, saved):
    if not all(isinstance(obj, dict) for obj in (probe, fixed, expanding, saved)):
        raise ValueError("Actual frozen model and raw research evidence required")
    if (probe.get("scope") != REPORT_SCOPE or
        probe.get("included_stocks") != 20 or
        probe.get("feature_version") != "tw-raw-price-asof-bridge-1" or
        type(probe.get("accepted_whole_cohort_dates")) is not int or
        probe["accepted_whole_cohort_dates"] < 1 or
        type(probe.get("source_price_rows")) is not int or
        probe["source_price_rows"] != 8000):
        raise ValueError("Actual bounded TWSE source research provenance mismatch")
    if (fixed.get("status") != FIXED_STATUS or
        expanding.get("status") != EXPANDING_STATUS or
        probe.get("prototype_status") != FIXED_STATUS or
        probe.get("expanding_purged_status") != EXPANDING_STATUS or
        probe.get("dataset_sha256") != expanding.get("dataset_rows_sha256")):
        raise ValueError("Inconsistent model/source artifact provenance")
    expected_false = (
        "independent_future_validation_passed",
        "expanding_independent_future_validation_passed",
        "dividend_adjusted_total_return_proven",
        "original_historical_exchange_universe_audited",
        "historical_asof_capture_vintage_proven",
        "live_trading_approved",
        "line_messages_sent",
    )
    if any(probe.get(name) is not False for name in expected_false):
        raise ValueError("Unverified retrospective result cannot be called released")
    if (probe.get("neon_read_only") is not True or
        probe.get("no_derived_database_rows_written") is not True or
        probe.get("production_tw_factor_ridge_1_unchanged") is not True or
        probe.get("retrospective_test_split_previously_reviewed") is not True or
        probe.get("expanding_training_uses_only_mature_labels") is not True or
        fixed.get("live_trading_approved") is not False or
        expanding.get("trading_approved") is not False):
        raise ValueError("Unverified model safety or split-reuse evidence")
    fixed_excess = _windows(
        fixed.get("nonoverlap_test_windows"),
        "illustrative_net_excess_vs_equal_weight",
    )
    expanding_excess = _windows(
        expanding.get("nonoverlap_windows"),
        "assumed_net_excess_vs_equal_weight",
    )
    n_fixed, n_expanding = len(fixed_excess), len(expanding_excess)
    if (n_fixed != probe.get("nonoverlapping_holdout_windows") or
        n_expanding != probe.get("expanding_purged_windows") or
        n_expanding != expanding.get("count")):
        raise ValueError("Model window count mismatch")
    fixed_mean = _numeric(
        probe.get("mean_illustrative_net_excess_vs_equal_weight"), "fixed mean")
    exp_mean = _numeric(
        probe.get("expanding_mean_net_excess_vs_equal_weight"), "expanding mean")
    if (abs(fixed_mean - sum(fixed_excess) / n_fixed) > 1e-8 or
        abs(exp_mean - sum(expanding_excess) / n_expanding) > 1e-8 or
        abs(exp_mean - _numeric(
            expanding.get("mean_illustrative_net_excess_vs_equal_weight"),
            "expanding output mean")) > 1e-8):
        raise ValueError("Inconsistent source-realized return arithmetic")
    old = evaluate_release(saved)
    if old["decision"] != "BLOCKED":
        raise ValueError("Existing Ridge unexpectedly received research approval")
    reasons = [
        "RETROSPECTIVE_SPLIT_NOT_PRISTINE",
        "CURRENT_SURVIVOR_ROSTER_NOT_HISTORICALLY_COMPLETE",
        "UNADJUSTED_CASH_DIVIDEND_AND_CORPORATE_ACTION_VINTAGE",
        "SOURCE_CAPTURE_VINTAGE_NOT_INDEPENDENTLY_VERIFIED",
        "NO_PRECOMMITTED_INDEPENDENT_FUTURE_MODEL_VALIDATION",
        "EXISTING_RIDGE_HOLDOUT_FAILED",
    ]
    if n_fixed < REQUIRED_WINDOWS or n_expanding < REQUIRED_WINDOWS:
        reasons.append("TOO_FEW_NONOVERLAPPING_RESEARCH_WINDOWS")
    if fixed_mean <= 0:
        reasons.append("NONPOSITIVE_FIXED_MODEL_NET_EXCESS")
    if exp_mean <= 0:
        reasons.append("NONPOSITIVE_EXPANDING_MODEL_NET_EXCESS")
    return {
        "schema_version": 1,
        "scope": "TWSE_RAW_RESEARCH_INDEPENDENT_RELEASE_BLOCKER",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_dataset_sha256": probe["dataset_sha256"],
        "saved_model_version": old["model_version"],
        "saved_model_net_holdout_excess": old["saved_holdout_mean_net_excess"],
        "fixed_model_windows": n_fixed,
        "expanding_model_windows": n_expanding,
        "fixed_illustrative_mean_net_excess": fixed_mean,
        "expanding_illustrative_mean_net_excess": exp_mean,
        "blocking_reasons": sorted(reasons),
        "decision": "BLOCKED",
        "research_only": True,
        "positive_alpha_approved": False,
        "new_research_weights_can_replace_production": False,
        "live_trading_approved": False,
        "line_signal_delivery_approved": False,
        "database_writes": 0,
        "paid_upgrade_requested": False,
    }


def main():
    p = argparse.ArgumentParser(description="Independent TWSE raw model release blocker")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--fixed", type=Path, required=True)
    p.add_argument("--expanding", type=Path, required=True)
    p.add_argument("--saved", type=Path,
                   default=Path("models/tw-factor-ridge-1-evaluation.json"))
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = review(*[
        json.loads(path.read_text(encoding="utf-8"))
        for path in (args.report, args.fixed, args.expanding, args.saved)
    ])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False,
                                   allow_nan=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "decision": result["decision"],
        "fixed_windows": result["fixed_model_windows"],
        "expanding_windows": result["expanding_model_windows"],
        "blocking_reasons": result["blocking_reasons"],
        "trading_approved": result["live_trading_approved"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
