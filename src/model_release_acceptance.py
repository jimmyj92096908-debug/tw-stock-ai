"""Conservative, evidence-based model research release gate (no trading).

This is not a model trainer and cannot convert incomplete historical returns
or revised adjusted prices into a pristine out-of-sample evaluation.
"""
from __future__ import annotations
import math
from datetime import date
from hashlib import sha256
import json

REQUIRED_HOLDOUT_DAYS=20
REQUIRED_UNSEEN_NONOVERLAP_WINDOWS=10


def _finite(v,label):
    if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v):
        raise ValueError(label+" must be finite")
    return v


def evaluate_release(model_evaluation,*,historical_label_report=None,
                     independently_frozen_future_holdout=None):
    if not isinstance(model_evaluation,dict):
        raise ValueError("Expected complete persisted model evaluation")
    version=model_evaluation.get("model_version")
    if not isinstance(version,str) or not version or len(version)>90:
        raise ValueError("Provenance model version required")
    holdout=model_evaluation.get("holdout")
    if not isinstance(holdout,dict):
        raise ValueError("Absent saved holdout evidence")
    days=holdout.get("dates")
    stocks=holdout.get("stocks_evaluated")
    if type(days) is not int or days<=0 or type(stocks) is not int or stocks<=0:
        raise ValueError("Missing real scored holdout sample counts")
    mean_net_excess=_finite(holdout.get("model_mean_net_excess"),"net excess")
    mean_net_return=_finite(holdout.get("model_mean_net_return"),"net return")
    baseline=_finite(holdout.get("original_score_mean_net_excess"),"baseline excess")
    reasons=[]
    if not bool(model_evaluation.get("holdout_research_gate_passed")):
        reasons.append("SAVED_HOLDOUT_GATE_FAILED")
    if mean_net_excess<=0:
        reasons.append("NEGATIVE_OR_ZERO_SAVED_NET_EXCESS")
    if mean_net_excess<=baseline:
        reasons.append("NOT_BETTER_THAN_ORIGINAL_SCORE_BASELINE")
    if days<REQUIRED_HOLDOUT_DAYS:
        reasons.append("SAVED_HOLDOUT_TOO_FEW_DATES")
    if not model_evaluation.get("holdout_is_pristine_independent_validation",False):
        reasons.append("EXAMINED_HOLDOUT_NOT_INDEPENDENT")
    if model_evaluation.get("requires_new_unseen_future_holdout",True):
        reasons.append("NEW_UNSEEN_FUTURE_HOLDOUT_REQUIRED")

    if historical_label_report is None:
        reasons.append("NO_VERIFIED_HISTORICAL_MATURITY_REPORT")
        mature_windows=None
    else:
        if not isinstance(historical_label_report,dict):
            raise ValueError("Historical maturity evidence must be a JSON object")
        mature_windows=historical_label_report.get("nonoverlapping_actual_holding_windows")
        if type(mature_windows) is not int or mature_windows<0:
            raise ValueError("Verified nonoverlap window count required")
        if (mature_windows<REQUIRED_UNSEEN_NONOVERLAP_WINDOWS or
            not historical_label_report.get("eligible_for_exploratory_outcome_research",False)):
            reasons.append("INSUFFICIENT_NONOVERLAPPING_MATURE_WINDOW_COHORT")
        if not historical_label_report.get("corporate_action_adjustment_vintage_verified",False):
            reasons.append("ADJUSTED_PRICE_ASOF_VINTAGE_UNVERIFIED")
        if not historical_label_report.get("market_wide_survivorship_bias_audited",False):
            reasons.append("SURVIVORSHIP_BIAS_NOT_AUDITED")

    if independently_frozen_future_holdout is None:
        reasons.append("NO_FROZEN_FORWARD_INDEPENDENT_EVALUATION")
    else:
        # Do not auto-approve a user-supplied or retroactively manufactured
        # JSON object. The validating review must be separately recorded.
        if not isinstance(independently_frozen_future_holdout,dict):
            raise ValueError("Future independent evaluation must be an object")
        if independently_frozen_future_holdout.get("model_version")!=version:
            raise ValueError("Future evidence cannot refer to a different model")
        if not independently_frozen_future_holdout.get("precommitted_before_labels",False):
            reasons.append("FUTURE_EVALUATION_NOT_PRECOMMITTED")
        if not independently_frozen_future_holdout.get("independent_provenance_reviewed",False):
            reasons.append("FUTURE_EVALUATION_NOT_INDEPENDENTLY_REVIEWED")
        if not independently_frozen_future_holdout.get("net_costs_liquidity_stress_passed",False):
            reasons.append("REAL_COST_LIQUIDITY_STRESS_UNVERIFIED")
        if not independently_frozen_future_holdout.get("nonoverlapping_holdout_periods_verified",False):
            reasons.append("NEW_HOLDOUT_INDEPENDENCE_UNVERIFIED")
    evidence_hash=sha256(json.dumps(model_evaluation,sort_keys=True,separators=(",",":"),
                                    ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    return {
        "schema_version":1,
        "model_version":version,
        "saved_evaluation_sha256":evidence_hash,
        "saved_holdout_dates":days,
        "saved_holdout_observations":stocks,
        "saved_holdout_mean_net_return":mean_net_return,
        "saved_holdout_mean_net_excess":mean_net_excess,
        "saved_baseline_mean_net_excess":baseline,
        "historical_independent_windows":mature_windows,
        "research_evaluation_quality_passed":len(reasons)==0,
        "blocking_reasons":sorted(set(reasons)),
        "decision":"BLOCKED" if reasons else "ELIGIBLE_FOR_INDEPENDENT_HUMAN_REVIEW_ONLY",
        "live_trading_approved":False,
        "line_signal_delivery_approved":False,
        "model_weights_modified":False,
        "database_writes":False,
        "no_false_alpha_claim":True,
    }
