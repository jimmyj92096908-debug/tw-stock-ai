"""Read-only, owner-local attribution of ex-date candidates to saved TWSE Ridge baskets.

Replays FIXED and EXPANDING retrospective selection from the original 20-stock
UNADJUSTED dataset. It can identify whether a cash-dividend candidate was in
a selected basket, NOT calculate dividend proceeds or certify total returns.
No DB connection, LINE, trading, secret, or production model mutation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
import re

import numpy as np

from src.raw_factor_feature_bridge import FEATURE_NAMES
from src.raw_factor_walkforward import (
    MIN_TRAIN_DAYS, MIN_TRAIN_ROWS, RIDGE_LAMBDA, TOP_FRACTION,
)
from src.raw_expanding_walkforward import COST_ASSUMPTIONS
from src.research_execution_costs import stress_test
from scripts.twse_official_research_action_reconcile import validate_study

FILE_LIMIT = 12_000_000
MODEL_KEYS = ("dataset", "fixed", "expanding", "readiness")
CODE = re.compile(r"[0-9]{4}\Z")


def load_file(path: Path) -> tuple[dict, str]:
    if not path.is_file() or path.stat().st_size > FILE_LIMIT:
        raise ValueError("Missing or oversized offline research evidence")
    data = path.read_bytes()
    value = json.loads(data.decode("utf-8-sig"),
                       parse_constant=lambda _: (_ for _ in ()).throw(
                           ValueError("Non-finite JSON evidence")))
    if not isinstance(value, dict):
        raise ValueError("Offline evidence must be a JSON object")
    return value, sha256(data).hexdigest()


def _fit(training):
    if len(training) < MIN_TRAIN_ROWS:
        raise ValueError("Insufficient historical mature labels")
    features = []
    labels = []
    for row in training:
        vector = row.get("feature_vector")
        label = row.get("raw_unadjusted_gross_return")
        if (not isinstance(vector, list) or len(vector) != len(FEATURE_NAMES)
                or any(type(x) not in (float, int) or not math.isfinite(x)
                       for x in vector)
                or type(label) not in (float, int) or not math.isfinite(label)):
            raise ValueError("Missing/invalid unadjusted RAW feature or label")
        features.append(vector)
        labels.append(label)
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    means = x.mean(axis=0)
    stds = x.std(axis=0)
    stds = np.where(stds < 1e-12, 1.0, stds)
    centered = (x - means) / stds
    weights = np.linalg.solve(
        centered.T @ centered + RIDGE_LAMBDA * np.eye(len(FEATURE_NAMES)),
        centered.T @ (y - y.mean()),
    )
    if not np.all(np.isfinite(weights)):
        raise ValueError("Nonfinite replay weights")
    return means, stds, weights


def _rank(members, fitted):
    means, stds, weights = fitted
    x = np.asarray([r["feature_vector"] for r in members], dtype=np.float64)
    scores = (x - means) / stds @ weights
    count = max(1, math.ceil(len(members) * TOP_FRACTION))
    indices = np.argsort(-scores, kind="stable")[:count]
    picks = [members[i]["stock_id"] for i in indices]
    gross = float(np.mean([
        members[i]["raw_unadjusted_gross_return"] for i in indices]))
    baseline = float(np.mean([
        r["raw_unadjusted_gross_return"] for r in members]))
    return picks, gross, baseline


def _near(actual, recorded, name):
    if type(recorded) not in (float, int) or not math.isfinite(recorded):
        raise ValueError("Invalid saved original model receipt: " + name)
    if not math.isclose(actual, recorded, rel_tol=0, abs_tol=5e-9):
        raise ValueError("Model replay differs from saved receipt: " + name)


def _weights_digest(weights):
    encoded = json.dumps([round(float(v), 12) for v in weights],
                         separators=(",", ":"), allow_nan=False).encode()
    return sha256(encoded).hexdigest()


def replay(dataset, fixed, expanding, windows):
    if (dataset.get("research_status")
            != "RAW_ONLY_UNADJUSTED_SOURCE_COHORT_NOT_A_MODEL_RELEASE"
            or dataset.get("feature_names") != list(FEATURE_NAMES)
            or fixed.get("status") != "RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY"
            or expanding.get("status") != "RETROSPECTIVE_EXPANDING_PURGED_RAW_ONLY"
            or fixed.get("may_update_production_model_weights") is not False
            or fixed.get("may_release_positive_alpha_or_trade_signals") is not False):
        raise ValueError("Original exploratory model boundary is inconsistent")
    groups = defaultdict(list)
    for row in dataset["rows"]:
        groups[row["as_of_date"]].append(row)
    roster = set(dataset["frozen_current_stock_roster"])
    for signal, members in groups.items():
        if len(members) != len(roster) or {x["stock_id"] for x in members} != roster:
            raise ValueError("Training or test cohort incomplete")
        if len({x["exit_date"] for x in members}) != 1:
            raise ValueError("Training label exits differ within cohort")
    test_start = windows[0]["signal_date"]
    dev = [(day, group) for day, group in sorted(groups.items())
           if day < test_start and group[0]["exit_date"] < test_start]
    if len(dev) < MIN_TRAIN_DAYS or len(dev) != fixed.get("development_dates"):
        raise ValueError("First fixed-model development fold is inconsistent")
    train = [row for _, group in dev for row in group]
    if len(train) != fixed.get("development_rows"):
        raise ValueError("Training sample count differs from original")
    initial_fit = _fit(train)
    saved = fixed.get("prototype_weights_from_mature_development_only")
    if not isinstance(saved, list) or len(saved) != len(FEATURE_NAMES):
        raise ValueError("Fixed-model saved weights unavailable")
    for calc, expected in zip(initial_fit[2], saved):
        _near(round(float(calc), 12), expected, "fixed-ridge-coefficient")

    basket = {}
    for idx, window in enumerate(windows):
        signal = window["signal_date"]
        members = groups[signal]
        fixed_picks, fixed_gross, baseline = _rank(members, initial_fit)
        f = fixed["nonoverlap_test_windows"][idx]
        _near(fixed_gross, f["raw_price_only_gross_return"], "fixed-gross")
        _near(baseline, f["universe_raw_mean_return"], "fixed-equal-weight")
        _near(stress_test(fixed_gross, **COST_ASSUMPTIONS)[
            "worst_assumed_net_return"],
            f["illustrative_worst_cost_net_return"], "fixed-net")
        _near(stress_test(baseline, **COST_ASSUMPTIONS)[
            "worst_assumed_net_return"],
            f["equal_weight_illustrative_worst_cost_net_return"], "fixed-baseline-net")
        if len(fixed_picks) != f["selected_count"]:
            raise ValueError("Fixed selected count mismatch")

        expanded = [(day, group) for day, group in sorted(groups.items())
                    if day < signal and group[0]["exit_date"] < signal]
        if len(expanded) < MIN_TRAIN_DAYS:
            raise ValueError("Expanding model training was insufficient")
        examples = [row for _, group in expanded for row in group]
        means, stds, weights = _fit(examples)
        e = expanding["nonoverlap_windows"][idx]
        if (_weights_digest(weights) != e.get("training_weights_sha256")
                or len(expanded) != e.get("training_date_count")
                or len(examples) != e.get("training_row_count")
                or max(r["exit_date"] for r in examples)
                    != e.get("last_mature_training_exit")):
            raise ValueError("Expanding coefficients, fold maturity, or hash mismatch")
        expand_picks, expand_gross, expanded_baseline = _rank(
            members, (means, stds, weights))
        _near(expand_gross and expand_gross or 0.0, expand_gross, "finite expanded")
        _near(expanded_baseline, baseline, "equal-weight cohorts")
        _near(stress_test(expand_gross, **COST_ASSUMPTIONS)[
            "worst_assumed_net_return"],
            e["assumed_cost_net_return"], "expanding-net")
        _near(stress_test(expanded_baseline, **COST_ASSUMPTIONS)[
            "worst_assumed_net_return"],
            e["equal_weight_assumed_cost_net_return"], "expanding-baseline-net")
        if len(expand_picks) != e.get("selected_stock_count"):
            raise ValueError("Expanding selected count mismatch")
        basket[signal] = {
            "signal_date": signal, "entry_date": window["entry_date"],
            "exit_date": window["exit_date"],
            "fixed_selected_stocks": fixed_picks,
            "expanding_selected_stocks": expand_picks,
            "selection_replayed_against_saved_model_receipts": True,
        }
    return basket


def attribute(dataset, fixed, expanding, readiness, source_report):
    roster, windows, _ = validate_study(dataset, fixed, expanding, readiness)
    if (source_report.get("scope")
            != "TWSE_20_STOCK_OFFICIAL_EX_ACTION_CANDIDATE_RECONCILIATION"
            or source_report.get("release_decision") != "BLOCKED"
            or source_report.get("true_total_return_label_verified") is not False
            or source_report.get("database_connections") != 0
            or source_report.get("database_writes") != 0
            or source_report.get("line_messages_sent") != 0
            or source_report.get("monthly_source_files_not_independently_authenticated") is not True
            or source_report.get("historical_issuer_announcement_vintage_verified") is not False
            or source_report.get("historical_point_in_time_universe_verified") is not False):
        raise ValueError("Prior official preview is not valid raw-only research evidence")
    original = source_report.get("candidate_events")
    overlaps = source_report.get("window_candidate_overlap")
    if (not isinstance(original, list) or len(original) > 200
            or not isinstance(overlaps, list) or len(overlaps) != len(windows)
            or len(original) != source_report.get("twse_research_cohort_candidate_events")):
        raise ValueError("Official research candidate counts disagree")
    allowed = set(roster)
    for e in original:
        if (not isinstance(e, dict) or e.get("stock_id") not in allowed
                or not re.fullmatch(r"[0-9]{4}", e["stock_id"])
                or e.get("action_type_candidate") not in (
                    "CASH_DIVIDEND", "STOCK_DIVIDEND",
                    "COMBINED_OR_UNKNOWN", "CAPITAL_REDUCTION")
                or not isinstance(e.get("ex_date"), str)):
            raise ValueError("Unknown or excluded official research candidate")
        date.fromisoformat(e["ex_date"])
    expected = 0
    for w, recorded in zip(windows, overlaps):
        n = sum(w["entry_date"] <= e["ex_date"] <= w["exit_date"]
                for e in original)
        stocks = sorted({e["stock_id"] for e in original
                         if w["entry_date"] <= e["ex_date"] <= w["exit_date"]})
        if (any(recorded.get(key) != w[key] for key in (
                "signal_date", "entry_date", "exit_date"))
                or recorded.get("official_candidate_events_near_holding_period") != n
                or recorded.get("stocks_with_candidates") != stocks):
            raise ValueError("Saved official preview overlap is inconsistent")
        expected += bool(n)
    if expected != source_report.get("research_windows_with_event_candidate"):
        raise ValueError("Window event count differs from original preview")
    basket = replay(dataset, fixed, expanding, windows)
    events = []
    for e in original:
        related = []
        for w in windows:
            signal = w["signal_date"]
            in_holding = w["entry_date"] <= e["ex_date"] <= w["exit_date"]
            at_signal = e["ex_date"] == signal
            if in_holding or at_signal:
                trace = basket[signal]
                related.append({
                    "signal_date": signal, "entry_date": w["entry_date"],
                    "exit_date": w["exit_date"],
                    "ex_date_on_signal_day_before_entry": at_signal,
                    "ex_date_inside_holding_inclusive": in_holding,
                    "ex_date_on_exit_day": in_holding and e["ex_date"] == w["exit_date"],
                    "selected_by_fixed_raw_ridge": e["stock_id"] in trace["fixed_selected_stocks"],
                    "selected_by_expanding_raw_ridge": e["stock_id"] in trace["expanding_selected_stocks"],
                    "included_in_twenty_stock_equal_weight_benchmark": True,
                    "confirmed_dividend_cash_entitlement": False,
                    "label_return_adjustment_permitted": False,
                })
        events.append({
            "stock_id": e["stock_id"], "ex_date": e["ex_date"],
            "action_type_candidate": e["action_type_candidate"],
            "explicit_cash_dividend_per_share": e.get("explicit_cash_dividend_per_share"),
            "reference_price_factor_if_available": e.get("reference_price_factor_if_available"),
            "official_source": e.get("official_source"),
            "signal_or_holding_windows": related,
            "reference_factor_is_not_cash_dividend_per_share": True,
            "economic_adjustment_independently_proven": False,
        })
    return {
        "scope": "TWSE_OFFLINE_RAW_RIDGE_CORPORATE_ACTION_SELECTION_ATTRIBUTION",
        "frozen_twse_research_stocks": len(roster),
        "original_nonoverlap_windows_replayed": len(basket),
        "candidate_events_reviewed": len(events),
        "events": events,
        "model_weights_mutated": False,
        "dividend_proceeds_calculated": False,
        "total_return_labels_recomputed": False,
        "historical_point_in_time_source_proven": False,
        "independent_future_validation_passed": False,
        "release_decision": "BLOCKED",
        "database_connections": 0,
        "database_writes": 0,
        "line_messages_sent": 0,
        "paid_services_used": False,
    }


def main():
    ap = argparse.ArgumentParser(description="Owner-local read-only Ridge ex-action event attribution")
    for key in MODEL_KEYS:
        ap.add_argument("--" + key, type=Path, required=True)
    ap.add_argument("--actions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    loaded = {key: load_file(getattr(args, key)) for key in MODEL_KEYS}
    events, events_sha = load_file(args.actions)
    receipts = events.get("local_file_sha256_receipts_not_source_authentication")
    if not isinstance(receipts, dict) or any(
            receipts.get(key) != loaded[key][1] for key in MODEL_KEYS):
        raise ValueError("Underlying research receipts differ from official reconciliation")
    result = attribute(*(loaded[key][0] for key in MODEL_KEYS), events)
    result["input_research_sha256_receipts_not_original_source_authentication"] = {
        **{key: loaded[key][1] for key in MODEL_KEYS},
        "official_action_reconciliation": events_sha,
    }
    if args.out.exists():
        raise FileExistsError("Owner-local report exists; refusing to overwrite")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({
        "scope": result["scope"],
        "models_replayed": result["original_nonoverlap_windows_replayed"],
        "events": [{
            "stock": ev["stock_id"], "ex_date": ev["ex_date"],
            "windows": ev["signal_or_holding_windows"],
            "verified_cash_per_share": ev["explicit_cash_dividend_per_share"],
        } for ev in result["events"]],
        "release_decision": "BLOCKED",
        "database_writes": 0,
        "line_messages_sent": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
