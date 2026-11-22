"""Offline RAW-source AI research cohort adapter and purged walk-forward prototype.

The current Ridge model consumes historical COMPOSITE scores. These newly
computed unadjusted source-only raw features are a DIFFERENT schema, and
must not be silently cast into score fields or certify alpha.

Prospective validation and issuer-vintage/source captured-on-date proof are
not available here. Test returns are UNADJUSTED price-only, NOT dividends.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from datetime import date
from hashlib import sha256
import json
import math

import numpy as np

from src.raw_factor_feature_bridge import (
    FEATURE_NAMES,build_research_features,validate_source,_day
)
from src.research_execution_costs import stress_test

MIN_UNIVERSE=5
MAX_UNIVERSE=20
MAX_SIGNAL_DAYS=100
FORWARD_ENTRY_SESSION=1
FORWARD_EXIT_SESSION=6
MIN_TRAIN_DAYS=20
MIN_TRAIN_ROWS=100
RIDGE_LAMBDA=2.0
TOP_FRACTION=0.20

def frozen_unadjusted_dataset(series_by_stock, *, signal_dates, label_cutoff, market="tpex"):
    """Assemble whole cohorts; do not drop a loser whose exit bar is missing."""
    cutoff=_day(label_cutoff)
    if market not in ("twse", "tpex"):
        raise ValueError("Official exchange market required")
    if (not isinstance(series_by_stock,dict) or
        not MIN_UNIVERSE<=len(series_by_stock)<=MAX_UNIVERSE or
        not isinstance(signal_dates,(list,tuple)) or
        not 1<=len(signal_dates)<=MAX_SIGNAL_DAYS):
        raise ValueError("Bounded fixed roster of original price series required")
    days=[_day(v) for v in signal_dates]
    if len(set(days))!=len(days) or max(days)>cutoff:
        raise ValueError("Real historical dates must be unique and <= mature cutoff")
    sources={}
    stocks=sorted(series_by_stock)
    for sid in stocks:
        bars=series_by_stock[sid]
        validate_source(bars,stock_id=sid,cutoff=cutoff,market=market)
        sources[sid]=(bars,{_day(r["trade_date"]):i for i,r in enumerate(bars)})
    rows=[]
    excluded=Counter()
    for signal in sorted(days):
        members=[]
        skip=None
        for sid in stocks:
            bars,idx=sources[sid]
            i=idx.get(signal)
            if i is None:
                skip="missing_stock_session_in_frozen_roster"
                break
            if i+FORWARD_EXIT_SESSION>=len(bars):
                skip="unmatured_next_session_to_exit_label"
                break
            entry=bars[i+FORWARD_ENTRY_SESSION]
            exit_=bars[i+FORWARD_EXIT_SESSION]
            entry_day=_day(entry["trade_date"])
            exit_day=_day(exit_["trade_date"])
            if not signal<entry_day<exit_day<=cutoff:
                skip="future_or_unmatured_real_market_holding_window"
                break
            # Key anti-leakage invariant: the feature function NEVER receives
            # any data after the signal date, even though the label builder
            # separately needs the future entry/exit bars.
            feature=build_research_features(
                bars[:i+1],stock_id=sid,cutoff=signal,signal_dates=[signal],market=market)
            if not feature["signals"]:
                skip="insufficient_unadjusted_raw_warmup"
                break
            vec=feature["signals"][0]["feature_vector"]
            p0=float(entry["close"]);p1=float(exit_["close"])
            if p0<=0 or p1<=0 or not all(math.isfinite(v) for v in (p0,p1)):
                skip="invalid_actual_raw_forward_close"
                break
            members.append({
                "as_of_date":signal.isoformat(),
                "market":market,"stock_id":sid,
                "feature_vector":vec,
                "entry_date":entry_day.isoformat(),
                "exit_date":exit_day.isoformat(),
                "raw_unadjusted_gross_return":round(p1/p0-1,12),
                "forward_label_is_unadjusted_price_only":True
            })
        if skip is None and (
            len({x["entry_date"] for x in members})!=1 or
            len({x["exit_date"] for x in members})!=1
        ):
            skip="unaligned_real_stock_trading_windows"
        if skip:
            excluded[skip]+=1
            continue
        if len(members)!=len(stocks):
            raise AssertionError("Research cohort must preserve entire frozen roster")
        rows.extend(members)
    serial=json.dumps(rows,sort_keys=True,separators=(",",":"),allow_nan=False)
    return {
        "schema_version":1,
        "research_status":"RAW_ONLY_UNADJUSTED_SOURCE_COHORT_NOT_A_MODEL_RELEASE",
        "feature_version":"tw-raw-price-asof-bridge-1",
        "feature_names":list(FEATURE_NAMES),
        "frozen_current_stock_roster":stocks,
        "market":market,
        "requested_signal_days":len(days),
        "accepted_whole_cohort_days":len({r["as_of_date"] for r in rows}),
        "excluded_whole_cohort_days":dict(sorted(excluded.items())),
        "source_row_count":sum(len(bars) for bars,_ in sources.values()),
        "rows_sha256":sha256(serial.encode()).hexdigest(),
        "rows":rows,
        "label_cutoff":cutoff.isoformat(),
        "price_labels_adjusted_for_cash_dividends_or_splits":False,
        "issuer_population_survivorship_audited":False,
        "corporate_action_original_published_vintage_audited":False,
        "source_trading_day_capture_vintage_historically_proven":False,
        "fixed_roster_is_historical_exchange_wide_universe":False,
        "pristine_independent_future_holdout_verified":False,
        "existing_tw_factor_ridge_1_feature_schema_compatible":False,
        "live_trading_approved":False,"line_trade_signals_approved":False,
        "database_writes":0,
    }

def purged_ridge_prototype(dataset,*,test_start):
    """Train only labels exited before fold start, evaluate nonoverlap windows.

    ALWAYS RETROSPECTIVE AND UNAPPROVED, irrespective of observed returns.
    """
    if (not isinstance(dataset,dict) or
        dataset.get("research_status")!="RAW_ONLY_UNADJUSTED_SOURCE_COHORT_NOT_A_MODEL_RELEASE" or
        dataset.get("feature_names")!=list(FEATURE_NAMES) or
        dataset.get("existing_tw_factor_ridge_1_feature_schema_compatible") is not False):
        raise ValueError("Incompatible unverified factor input")
    rows=dataset.get("rows")
    if not isinstance(rows,list):
        raise ValueError("Original rows missing")
    serial=json.dumps(rows,sort_keys=True,separators=(",",":"),allow_nan=False)
    if sha256(serial.encode()).hexdigest()!=dataset.get("rows_sha256"):
        raise ValueError("Source research dataset fingerprint mismatch")
    cutoff=_day(dataset["label_cutoff"])
    test=_day(test_start)
    if test>cutoff:
        raise ValueError("Test start later than actual available labels")
    groups=defaultdict(list)
    for row in rows:
        day=_day(row["as_of_date"])
        exit_= _day(row["exit_date"])
        entry=_day(row["entry_date"])
        if not day<entry<exit_<=cutoff:
            raise ValueError("Unmatured raw label in research dataset")
        if (not isinstance(row.get("feature_vector"),list) or
            len(row["feature_vector"])!=len(FEATURE_NAMES) or
            any(type(v) not in (int,float) or not math.isfinite(v)
                for v in row["feature_vector"])):
            raise ValueError("Incomplete or non-finite as-of input feature")
        groups[day].append(row)
    complete=[]
    roster=set(dataset["frozen_current_stock_roster"])
    for day,members in sorted(groups.items()):
        if len(members)!=len(roster) or {x["stock_id"] for x in members}!=roster:
            raise ValueError("Selection bias: incomplete frozen stock cohort")
        if len({x["entry_date"] for x in members})!=1 or len({
            x["exit_date"] for x in members})!=1:
            raise ValueError("Unaligned true forward sessions")
        complete.append((day,members))
    development=[(d,m) for d,m in complete if d<test and all(
        _day(x["exit_date"])<test for x in m)]
    holdout=[(d,m) for d,m in complete if d>=test]
    result={
        "schema_version":1,"status":"INSUFFICIENT_MATURE_RAW_SOURCE_RESEARCH",
        "research_only":True,
        "purged_train_label_exits_before_first_holdout":True,
        "label_adjustment_vintage_proven":False,
        "source_capture_vintage_proven":False,
        "survivorship_population_verified":False,
        "true_pristine_future_holdout":False,
        "may_update_production_model_weights":False,
        "may_release_positive_alpha_or_trade_signals":False,
        "live_trading_approved":False,
        "development_dates":len(development),
        "development_rows":sum(len(x) for _,x in development),
        "holdout_available_dates":len(holdout),
        "nonoverlap_test_windows":[],
        "illustrative_broker_costs_not_executable_quotes":True,
    }
    if (len(development)<MIN_TRAIN_DAYS or
        result["development_rows"]<MIN_TRAIN_ROWS or not holdout):
        return result
    training=[r for _,m in development for r in m]
    X=np.asarray([r["feature_vector"] for r in training],dtype=np.float64)
    y=np.asarray([r["raw_unadjusted_gross_return"] for r in training],dtype=np.float64)
    means=X.mean(axis=0)
    stds=X.std(axis=0)
    stds=np.where(stds<1e-12,1.0,stds)
    centered=(X-means)/stds
    weights=np.linalg.solve(
        centered.T@centered+RIDGE_LAMBDA*np.eye(len(FEATURE_NAMES)),
        centered.T@(y-y.mean())
    )
    if not np.all(np.isfinite(weights)):
        raise RuntimeError("Non-finite ridge research coefficients")
    # No folds share future periods: one earlier training fit evaluated on
    # chronologically disjoint test windows, no post-test refit.
    last_exit=None
    outcomes=[]
    for signal,members in holdout:
        exit_=members[0]["exit_date"]
        if last_exit is not None and signal<=last_exit:
            continue
        m=np.asarray([r["feature_vector"] for r in members],dtype=float)
        rank=(m-means)/stds@weights
        count=max(1,math.ceil(len(members)*TOP_FRACTION))
        selected=np.argsort(-rank,kind="stable")[:count]
        gross=float(np.mean([members[i]["raw_unadjusted_gross_return"] for i in selected]))
        universe_gross=float(np.mean([
            member["raw_unadjusted_gross_return"] for member in members]))
        # Apply identical *illustrative* cost scenarios to the selected and
        # equal-weight benchmark. These are not verified execution costs.
        cost_assumptions=dict(fee_bps=14.25,sell_tax_bps=30,
                              slippage_bps_scenarios=(10,30,60))
        stress=stress_test(gross,**cost_assumptions)
        benchmark_stress=stress_test(universe_gross,**cost_assumptions)
        net=stress["worst_assumed_net_return"]
        baseline_net=benchmark_stress["worst_assumed_net_return"]
        outcomes.append({
            "signal_date":signal.isoformat(),
            "entry_date":members[0]["entry_date"],
            "exit_date":exit_,"selected_count":count,
            "raw_price_only_gross_return":round(gross,10),
            "illustrative_worst_cost_net_return":net,
            "universe_raw_mean_return":round(universe_gross,10),
            "equal_weight_illustrative_worst_cost_net_return":baseline_net,
            "illustrative_net_excess_vs_equal_weight":round(net-baseline_net,10),
        })
        last_exit=_day(exit_)
    result.update({
        "status":"RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY",
        "training_features_scaled_using_only_mature_development_rows":True,
        "prototype_weights_from_mature_development_only":[round(float(v),12) for v in weights],
        "nonoverlap_test_windows":outcomes,
        "nonoverlap_count":len(outcomes),
        "mean_illustrative_net_excess_vs_equal_weight":(
            round(float(np.mean([
                x["illustrative_net_excess_vs_equal_weight"] for x in outcomes])),10)
            if outcomes else None),
        "min_nonoverlapping_windows_for_research_comparison":10,
        "research_window_count_sufficient":len(outcomes)>=10,
        "benchmark_uses_identical_illustrative_cost_assumptions":True,
        "label_is_adjusted_total_return":False,
        "positive_alpha_conclusion_permitted":False
    })
    return result
