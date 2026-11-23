"""Frozen, trainable Taiwan equity factor model (research only).

This learns a small ridge-regression ranking from *development-period* adjusted
forward returns. Holdout labels cannot influence fitted parameters. The model
always refuses to issue trade signals, even if its research gate passes:
execution, corporate-action and delisting audits remain separate requirements.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from hashlib import sha256
import json
import math

import numpy as np
from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

VERSION = "tw-factor-ridge-1"
FEATURES = (
    "total_score", "technical_score", "smc_score", "short_term_score",
    "swing_score", "long_term_score", "coverage_weight",
)
OPTIONAL = FEATURES[1:6]
FEATURE_NAMES = FEATURES + tuple("missing_" + key for key in OPTIONAL)
REGULARIZATION = 2.0
COST_BPS = 30
TOP_FRACTION = 0.20
MIN_UNIVERSE = 5
MIN_TRAIN_DATES = 20
MIN_HOLDOUT_DATES = 10
MIN_TRAIN_ROWS = 200

# Window over raw-price trading sessions, never over sparse adjusted-price rows.
# All labels are fetched only for evaluation/training, never for a live ranking.
TRAINING_SQL = f"""{CURRENT_OFFICIAL_LISTED_CTE}, sessions AS (
 SELECT p.market,p.stock_id,p.trade_date,p.close AS raw_close,
        a.close AS adjusted_close,
        LEAD(p.trade_date,6) OVER w AS exit_date,
        LEAD(p.trade_date,1) OVER w AS entry_date,
        LEAD(a.close,1) OVER w AS entry_close,
        LEAD(a.close,6) OVER w AS exit_close
 FROM public.daily_prices p
 LEFT JOIN public.daily_adjusted_prices a
   ON a.market=p.market AND a.stock_id=p.stock_id
  AND a.trade_date=p.trade_date
 WHERE p.close IS NOT NULL AND p.close>0
 WINDOW w AS (PARTITION BY p.market,p.stock_id ORDER BY p.trade_date)
)
SELECT s.market,s.stock_id,s.as_of_date,s.total_score,
       s.technical_score,s.smc_score,s.short_term_score,s.swing_score,
       s.long_term_score,s.coverage_weight,
       p.adjusted_close,p.entry_date,p.entry_close,p.exit_close,p.exit_date
FROM public.daily_composite_scores s
JOIN official_current_listed active
 ON active.market=s.market AND active.stock_id=s.stock_id
JOIN public.stock_master sm
 ON sm.market=s.market AND sm.stock_id=s.stock_id
JOIN sessions p
 ON p.market=s.market AND p.stock_id=s.stock_id
 AND p.trade_date=s.as_of_date
WHERE s.as_of_date BETWEEN %s AND %s
  AND s.total_score IS NOT NULL
  AND s.stock_id <> '1808'
  AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x
                  WHERE x.market=s.market AND x.stock_id=s.stock_id)
ORDER BY s.as_of_date,s.market,s.stock_id
"""

LATEST_MODEL_SQL = f"""{CURRENT_OFFICIAL_LISTED_CTE}, latest AS (
 SELECT MAX(as_of_date) AS score_date
 FROM public.daily_composite_scores WHERE total_score IS NOT NULL
)
SELECT s.market,s.stock_id,sm.stock_name,s.as_of_date,
 s.total_score,s.technical_score,s.smc_score,s.short_term_score,
 s.swing_score,s.long_term_score,s.coverage_weight,
 p.close AS signal_close
FROM latest l
JOIN public.daily_composite_scores s ON s.as_of_date=l.score_date
JOIN public.daily_prices p
 ON p.market=s.market AND p.stock_id=s.stock_id
 AND p.trade_date=s.as_of_date
JOIN public.stock_master sm
 ON sm.market=s.market AND sm.stock_id=s.stock_id
JOIN official_current_listed active
 ON active.market=s.market AND active.stock_id=s.stock_id
WHERE p.close>0 AND s.stock_id<>'1808' AND s.total_score IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x
                  WHERE x.market=s.market AND x.stock_id=s.stock_id)
ORDER BY s.market,s.stock_id
"""

# For a time-frozen, same-snapshot research cohort ONLY. The caller must
# independently establish the actual newest nonzero market-close date AND
# latest non-null score date in the *same REPEATABLE READ snapshot*, prove
# the two dates are equal and pass that exact date as a typed parameter.
# This avoids a global "MAX(score date)" aggregate inside the whole-roster
# join, which had timed out in the owner scheduled workflow. It does NOT
# relax original MOPS vintage, future label, eligibility, release or trade
# gates. It uses existing (stock_id, as_of_date) / (stock_id, trade_date)
# indexes; no DB schema, DDL or paid compute needed.
FROZEN_SAME_DAY_MODEL_SQL = f"""{CURRENT_OFFICIAL_LISTED_CTE}
SELECT s.market,s.stock_id,sm.stock_name,s.as_of_date,
 s.total_score,s.technical_score,s.smc_score,s.short_term_score,
 s.swing_score,s.long_term_score,s.coverage_weight,
 p.close AS signal_close
FROM official_current_listed active
JOIN public.daily_composite_scores s
 ON s.market=active.market AND s.stock_id=active.stock_id
 AND s.as_of_date=%s::date
JOIN public.daily_prices p
 ON p.market=s.market AND p.stock_id=s.stock_id
 AND p.trade_date=s.as_of_date
JOIN public.stock_master sm
 ON sm.market=s.market AND sm.stock_id=s.stock_id
WHERE p.close>0 AND s.stock_id NOT IN ('1808','1589')
 AND s.total_score IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x
                 WHERE x.market=s.market AND x.stock_id=s.stock_id)
ORDER BY s.market,s.stock_id
"""


def iso_day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)[:10]).isoformat()


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def feature_vector(row):
    values = []
    missing = []
    for key in FEATURES:
        value = number(row.get(key))
        if key == "coverage_weight":
            if value is None or not .5 <= value <= 1:
                return None
            values.append(value - .5)
        elif key == "total_score":
            if value is None or not 0 <= value <= 100:
                return None
            values.append(value / 100 - .5)
        else:
            valid = value is not None and 0 <= value <= 100
            values.append(value / 100 - .5 if valid else 0.0)
            missing.append(0.0 if valid else 1.0)
    return np.asarray(values + missing, dtype=np.float64)


def groups_from_rows(rows, *, holdout_start):
    """Freeze eligible t-day universes BEFORE evaluating future label coverage.

    Dates lacking any adjusted forward label are not evaluated, rather than
    removing only the missing ticker and shifting the test universe.
    """
    split = iso_day(holdout_start)
    candidates = defaultdict(list)
    rejected = {"bad_signal": 0, "missing_adjusted_signal": 0, "duplicate": 0}
    seen = set()
    for raw in rows:
        try:
            day = iso_day(raw["as_of_date"])
            market = str(raw["market"])
            stock_id = str(raw["stock_id"])
        except (KeyError, ValueError, TypeError):
            rejected["bad_signal"] += 1
            continue
        key = (day, market, stock_id)
        if key in seen:
            rejected["duplicate"] += 1
            continue
        seen.add(key)
        features = feature_vector(raw)
        if features is None or market not in ("twse", "tpex") or stock_id in ("1808", "1589"):
            rejected["bad_signal"] += 1
            continue
        adj_close = number(raw.get("adjusted_close"))
        if adj_close is None or adj_close <= 0:
            rejected["missing_adjusted_signal"] += 1
            continue
        entry = number(raw.get("entry_close"))
        exit_ = number(raw.get("exit_close"))
        try:
            exit_date = iso_day(raw.get("exit_date")) if raw.get("exit_date") is not None else None
            entry_date = iso_day(raw.get("entry_date")) if raw.get("entry_date") is not None else None
        except (ValueError, TypeError):
            exit_date = None
            entry_date = None
        candidates[day].append({
            "market": market, "stock_id": stock_id,
            "features": features, "raw_score": float(raw["total_score"]),
            "entry": entry, "exit": exit_, "exit_date": exit_date,
            "entry_date": entry_date,
        })
    sets = {"development": [], "holdout": []}
    skipped = {"small_universe": 0, "incomplete_forward": 0, "split_embargo": 0}
    for day, members in sorted(candidates.items()):
        if len(members) < MIN_UNIVERSE:
            skipped["small_universe"] += 1
            continue
        # Never rank away unavailable future labels. Discard the whole cohort.
        if any(m["entry"] is None or m["exit"] is None or
               m["entry"] <= 0 or m["exit"] <= 0 or
               m["exit_date"] is None for m in members):
            skipped["incomplete_forward"] += 1
            continue
        if day < split and any(m["exit_date"] >= split for m in members):
            skipped["split_embargo"] += 1
            continue
        for m in members:
            m["return"] = m["exit"] / m["entry"] - 1
        group = "development" if day < split else "holdout"
        sets[group].append((day, members))
    return sets, {"excluded": rejected, "skipped_dates": skipped}


def _date_matrix(cohort):
    # Date-wise centering trains cross-sectional rather than market-direction
    # exposure; its centering parameters use t-day features only.
    X = np.stack([m["features"] for m in cohort])
    return X - X.mean(axis=0)


def fit_development(development):
    total_rows = sum(len(items) for _, items in development)
    if len(development) < MIN_TRAIN_DATES or total_rows < MIN_TRAIN_ROWS:
        raise ValueError("Not enough development history for model fitting")
    gram = np.eye(len(FEATURE_NAMES), dtype=np.float64) * REGULARIZATION
    rhs = np.zeros(len(FEATURE_NAMES), dtype=np.float64)
    # Every date receives equal weight regardless of the number of stocks.
    # Targets clipped only for fitting; real adjusted returns used in audit.
    fingerprint = sha256()
    for day, members in development:
        x = _date_matrix(members)
        y = np.asarray([min(.5, max(-.5, m["return"])) for m in members])
        y -= y.mean()
        gram += (x.T @ x) / len(members)
        rhs += (x.T @ y) / len(members)
        for m in sorted(members, key=lambda v: (v["market"], v["stock_id"])):
            fingerprint.update(
                json.dumps([day, m["market"], m["stock_id"],
                            round(m["return"], 12),
                            [round(float(a), 12) for a in m["features"]]],
                           separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            )
    coefficients = np.linalg.solve(gram, rhs)
    if not np.all(np.isfinite(coefficients)):
        raise ValueError("Model coefficients not finite")
    return {
        "version": VERSION,
        "feature_names": list(FEATURE_NAMES),
        "weights": [round(float(w), 12) for w in coefficients],
        "regularization": REGULARIZATION,
        "development_dates": len(development),
        "development_rows": total_rows,
        "development_sha256": fingerprint.hexdigest(),
        "model_type": "regularized_cross_sectional_linear_ranker",
        "may_send_trade_signals": False,
    }


def _model_order(members, weights):
    x = _date_matrix(members)
    values = x @ np.asarray(weights, dtype=np.float64)
    return sorted(range(len(members)), key=lambda i: (
        -float(values[i]), -members[i]["raw_score"],
        members[i]["market"], members[i]["stock_id"]
    ))


def _baseline_order(members):
    return sorted(range(len(members)), key=lambda i: (
        -members[i]["raw_score"], members[i]["market"], members[i]["stock_id"]
    ))


def audit_period(groups, model):
    weights = model["weights"]
    daily = []
    for day, members in groups:
        k = max(1, math.ceil(len(members) * TOP_FRACTION))
        all_return = sum(m["return"] for m in members) / len(members)
        predicted = _model_order(members, weights)
        baseline = _baseline_order(members)
        model_gross = sum(members[i]["return"] for i in predicted[:k]) / k
        base_gross = sum(members[i]["return"] for i in baseline[:k]) / k
        cost = COST_BPS / 10000
        daily.append({
            "date": day, "universe": len(members), "selected": k,
            "model_net_excess": model_gross - cost - all_return,
            "baseline_net_excess": base_gross - cost - all_return,
            "model_net_return": model_gross - cost,
        })
    def avg(key):
        return round(sum(x[key] for x in daily) / len(daily), 8) if daily else None
    return {
        "dates": len(daily),
        "stocks_evaluated": sum(x["universe"] for x in daily),
        "model_mean_net_return": avg("model_net_return"),
        "model_mean_net_excess": avg("model_net_excess"),
        "original_score_mean_net_excess": avg("baseline_net_excess"),
        "positive_net_excess_fraction": (
            round(sum(x["model_net_excess"] > 0 for x in daily) / len(daily), 6)
            if daily else None
        ),
    }


def train_and_verify(rows, *, holdout_start):
    groups, exclusions = groups_from_rows(rows, holdout_start=holdout_start)
    model = fit_development(groups["development"])
    model["trained_through"] = groups["development"][-1][0]
    model["holdout_from"] = iso_day(holdout_start)
    dev = audit_period(groups["development"], model)
    holdout = audit_period(groups["holdout"], model)
    sufficient = holdout["dates"] >= MIN_HOLDOUT_DATES
    favorable = (sufficient and holdout["model_mean_net_excess"] > 0
                 and holdout["positive_net_excess_fraction"] >= .55)
    report = {
        "model_version": VERSION, "development": dev, "holdout": holdout,
        "exclusions": exclusions, "assumed_round_trip_cost_bps": COST_BPS,
        "holdout_research_gate_passed": bool(favorable),
        "holdout_research_gate_reason": (
            "passed_research_screen_only" if favorable else
            "insufficient_holdout_dates" if not sufficient else
            "negative_or_unstable_out_of_sample_excess"
        ),
        "live_trading_approved": False,
        "line_signal_delivery_approved": False,
        "notes": [
            "Not causal or a fitted price-forecast probability",
            "Adjusted prices can be retrospectively revised by corporate actions",
            "Cross-sectional universe selection and delisting bias remain",
            "Five-session overlapping labels are dependent observations",
            "Neither research holdout nor assumed costs justify live orders",
        ],
    }
    return model, report


def research_rank(rows, artifact, *, limit=10):
    if artifact.get("version") != VERSION or artifact.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("Unknown model artifact or mismatched feature schema")
    weights = artifact.get("weights")
    if not isinstance(weights, list) or len(weights) != len(FEATURE_NAMES) or any(number(w) is None for w in weights):
        raise ValueError("Invalid coefficients")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("Invalid ranking limit")
    approved = []
    signal_dates = set()
    for raw in rows:
        feature = feature_vector(raw)
        if feature is None or str(raw.get("stock_id")) in ("1808", "1589") or str(raw.get("market")) not in ("twse", "tpex"):
            continue
        close = number(raw.get("signal_close"))
        if close is None or close <= 0:
            continue
        day = iso_day(raw["as_of_date"])
        signal_dates.add(day)
        approved.append({
            "market": str(raw["market"]), "stock_id": str(raw["stock_id"]),
            "name": str(raw.get("stock_name") or ""), "day": day,
            "features": feature, "raw_score": float(raw["total_score"]), "close": close,
        })
    if len(signal_dates) > 1:
        raise ValueError("Cannot mix score dates in current ranking")
    if not approved:
        return {"model_version": VERSION, "date": None, "stocks": [],
                "abstain": True, "reason": "no_valid_same_day_stocks"}
    order = _model_order(approved, weights)
    return {
        "model_version": VERSION, "date": next(iter(signal_dates)),
        "eligible_universe": len(approved),
        "stocks": [
            {"rank": j, "market": approved[i]["market"], "stock_id": approved[i]["stock_id"],
             "name": approved[i]["name"], "raw_composite_score": approved[i]["raw_score"],
             "relative_model_score": round(float(
                 (np.stack([r["features"] for r in approved]) -
                  np.stack([r["features"] for r in approved]).mean(axis=0))[i] @ np.asarray(weights)
             ), 8), "signal_close": approved[i]["close"]}
            for j, i in enumerate(order[:limit], 1)
        ],
        "abstain": True,
        "reason": "research_only_unapproved_for_trade_signals",
        "live_trading_approved": False,
    }
