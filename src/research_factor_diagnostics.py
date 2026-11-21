"""Ex-post factor information coefficients; NOT proof of future alpha.

Use point-in-time daily composite features and adjusted future labels from a
validated retrospective dataset. Score factor subsets on *the same subset*
as their original-score baseline. Every tested signal window is disjoint.
"""
from __future__ import annotations

from collections import defaultdict
import math
from statistics import mean, median, pstdev

from src.research_dataset import FACTOR_FIELDS, verify_dataset

COST_BPS = 30
DEFAULT_TOP_FRACTION = .20


def _ranks(values):
    n = len(values)
    order = sorted(range(n), key=lambda i: (values[i], i))
    out = [0.0] * n
    i = 0
    while i < n:
        j = i + 1
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            out[order[k]] = rank
        i = j
    return out


def spearman_ic(factors, returns):
    if len(factors) != len(returns) or len(factors) < 2:
        return None
    x, y = _ranks(factors), _ranks(returns)
    a, b = mean(x), mean(y)
    numerator = sum((u-a)*(v-b) for u,v in zip(x,y))
    den1 = sum((u-a)**2 for u in x)
    den2 = sum((v-b)**2 for v in y)
    if den1 <= 0 or den2 <= 0:
        return None
    return max(-1.0, min(1.0, numerator/math.sqrt(den1*den2)))


def _basket_return(members, key, *, fraction):
    k = max(1, math.ceil(len(members)*fraction))
    order = sorted(members, key=lambda r: (-r[key],r["market"],r["stock_id"]))
    return mean(r["exit_close"]/r["entry_close"]-1 for r in order[:k]), k


def factor_diagnostics(dataset, *, exploration_end,
                       min_pairs=10, top_fraction=DEFAULT_TOP_FRACTION):
    """Return stable exploratory factor diagnostics without fitting weights.

    The held-out period is *not* examined; users must not tune factor selection
    using newly seen validation dates. This does not establish independence of
    any past holdout that was examined in previous research iterations.
    """
    if type(min_pairs) is not int or not 5 <= min_pairs <= 100:
        raise ValueError("min_pairs must be an integer from 5 to 100")
    if isinstance(top_fraction, bool) or not isinstance(top_fraction, (float,int)) or not 0 < top_fraction <= .5:
        raise ValueError("top_fraction must be >0 and <=0.5")
    from src.research_dataset import _date
    end = _date(exploration_end)
    m = dataset.get("manifest", {})
    if not m or not m.get("window_start") <= end <= m.get("window_end"):
        raise ValueError("Exploration end must be within the historical signal window")
    rows = verify_dataset(dataset)
    groups = defaultdict(list)
    for row in rows:
        if row["as_of_date"] <= end:
            groups[row["as_of_date"]].append(row)
    # Evaluate only non-overlapping date cohorts: adjacent 5-day labels are
    # strongly autocorrelated, and pretending N adjacent dates are N
    # independent observations overstates effective sample.
    evaluated = []
    omitted_overlapping = 0
    last_exit = None
    for day, cohort in sorted(groups.items()):
        cohort_exit = cohort[0]["exit_date"]
        if last_exit is not None and day <= last_exit:
            omitted_overlapping += 1
            continue
        last_exit = cohort_exit
        evaluated.append((day, cohort))
    output = {}
    for feature in FACTOR_FIELDS:
        records = []
        subset_universe = 0
        missing = 0
        skipped_min_pairs = 0
        skipped_constant = 0
        for day, cohort in evaluated:
            available = [r for r in cohort if r[feature] is not None]
            missing += len(cohort) - len(available)
            subset_universe += len(cohort)
            if len(available) < min_pairs:
                skipped_min_pairs += 1
                continue
            outcome = [r["exit_close"]/r["entry_close"]-1 for r in available]
            ic = spearman_ic([r[feature] for r in available], outcome)
            if ic is None:
                skipped_constant += 1
                continue
            top_gross,k = _basket_return(available,feature,fraction=top_fraction)
            baseline_gross,_ = _basket_return(available,"total_score",fraction=top_fraction)
            pool_gross = mean(outcome)
            records.append({
                "signal_date": day, "exit_date": available[0]["exit_date"],
                "cohort_count": len(cohort), "factor_observations": len(available),
                "top_count": k, "information_coefficient": round(ic,8),
                "factor_top_net_excess_vs_same_subset": round(
                    top_gross-COST_BPS/10000-pool_gross,8),
                "original_score_top_net_excess_vs_same_subset": round(
                    baseline_gross-COST_BPS/10000-pool_gross,8),
                "factor_minus_original_score": round(top_gross-baseline_gross,8),
            })
        ic = [r["information_coefficient"] for r in records]
        excess = [r["factor_top_net_excess_vs_same_subset"] for r in records]
        vs_base = [r["factor_minus_original_score"] for r in records]
        output[feature] = {
            "usable_nonoverlapping_dates": len(records),
            "sampled_date_count": len(evaluated),
            "sampled_scored_tickers": subset_universe,
            "missing_factor_tickers": missing,
            "factor_availability_rate": (
                round((subset_universe-missing)/subset_universe,6)
                if subset_universe else None),
            "dates_insufficient_factor_pairs": skipped_min_pairs,
            "dates_constant_factor_or_target": skipped_constant,
            "average_rank_ic": round(mean(ic),8) if ic else None,
            "median_rank_ic": round(median(ic),8) if ic else None,
            "rank_ic_volatility_per_window": round(pstdev(ic),8) if ic else None,
            "positive_ic_fraction": round(sum(x>0 for x in ic)/len(ic),6) if ic else None,
            "mean_top20_net_excess_vs_factor_subset": round(mean(excess),8) if excess else None,
            "mean_top20_advantage_vs_original_score": round(mean(vs_base),8) if vs_base else None,
            "per_window_evidence": records,
            "statistical_significance_tested": False,
            "comparable_to_other_factors_without_same_cohort_restriction": False,
        }
    return {
        "schema_version": 1,
        "diagnostic_type": "RETROSPECTIVE_EXPLORATORY_FACTOR_DIAGNOSTICS",
        "exploration_end": end,
        "dataset_sha256": m["rows_sha256"],
        "nonoverlapping_evaluated_dates": len(evaluated),
        "omitted_overlapping_dates": omitted_overlapping,
        "min_pairs_per_date": min_pairs,
        "assumed_round_trip_bps_per_long_only_top_basket": COST_BPS,
        "factor_diagnostics": output,
        "holdout_or_forward_performance_approved": False,
        "prior_holdout_not_restored_to_pristine": True,
        "orders_enabled": False,
        "caveats": [
            "Factors are descriptive and correlated; these are not independent causal effects",
            "All candidate stocks already had stored composite scores, causing selection bias",
            "Missing factors have different comparison subsets; raw factor IC cannot rank robustness",
            "Underlying corporate-action-adjusted history can be retrospectively revised",
            "Only historical development dates were explored; do not tune on validation outcomes",
            "Non-overlapping date windows still do not correct delisting and liquidity bias",
            "Exploratory diagnostic does not report p-values or proof of outperformance",
        ],
    }
