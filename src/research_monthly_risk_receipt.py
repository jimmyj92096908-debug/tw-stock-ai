"""Strict offline risk receipt for hypothetical, nonoverlapping monthly windows.

This measures only successive sampled holding windows. It is not a continuous
portfolio NAV, annualized return, daily drawdown, executable strategy or
independent prospective performance evidence.
"""
from datetime import date
from math import ceil,isclose,isfinite
from statistics import mean,median
import re
from src.research_monthly_fold_plan import MIN_TRAIN_DATES,MIN_TRAIN_ROWS,MIN_TEST_WINDOWS

BPS=(10,30,60)
DIGEST=re.compile(r"[0-9a-f]{64}",re.ASCII)


def _day(s):
    if type(s) is not str:
        raise ValueError("Canonical date required")
    d=date.fromisoformat(s)
    if d.isoformat()!=s:
        raise ValueError("Canonical date required")
    return d


def _metrics(values):
    nav=peak=1.0;drawdown=0.0
    for r in values:
        nav*=1+r
        peak=max(peak,nav)
        drawdown=max(drawdown,1-nav/peak)
    return {"mean_net_return":mean(values),"median_net_return":median(values),
        "positive_window_fraction":sum(v>0 for v in values)/len(values),
        "worst_window_return":min(values),"sampled_window_compounded_return":nav-1,
        "sampled_window_end_drawdown_fraction":drawdown}


def audit(result):
    if (type(result) is not dict or result.get("scope")!="OFFLINE_HYPOTHETICAL_MONTHLY_RIDGE_EVALUATION"
        or result.get("model_release")!="BLOCKED"
        or any(result.get(k) is not False for k in ("historical_total_return_verified",
             "source_labels_authenticated","pristine_future_holdout_verified","alpha_verified",
             "production_weights_updated","liquidity_and_execution_verified"))
        or type(result.get("model_trained")) is not bool):
        raise ValueError("Invalid hypothetical-only evaluation")
    schedule=result["fold_plan"];folds=result["folds"]
    if (type(folds) is not list or len(folds)>48 or type(schedule) is not dict
        or schedule.get("scope")!="OFFLINE_HYPOTHETICAL_MONTHLY_FOLD_PLAN"
        or schedule.get("model_release")!="BLOCKED"
        or schedule.get("minimum_train_dates")!=MIN_TRAIN_DATES
        or schedule.get("minimum_train_rows")!=MIN_TRAIN_ROWS
        or schedule.get("minimum_test_windows")!=MIN_TEST_WINDOWS):
        raise ValueError("Invalid fold plan")
    base={"scope":"OFFLINE_HYPOTHETICAL_MONTHLY_RISK_RECEIPT","schema_version":1,
        "window_count":len(folds),"continuous_daily_nav_verified":False,
        "annualized_metrics_computed":False,"intrawindow_drawdown_measured":False,
        "statistical_significance_proven":False,"independent_future_holdout_verified":False,
        "liquidity_and_executability_verified":False,"alpha_verified":False,
        "production_neon_reads":0,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED","scenarios":[]}
    if not result["model_trained"]:
        if folds or schedule.get("exploratory_date_count_gate") is not False:
            raise ValueError("Inconsistent insufficient-data receipt")
        return dict(base,status="INSUFFICIENT_HYPOTHETICAL_WINDOWS")
    planned=schedule.get("folds")
    if (type(planned) is not list or len(planned)!=len(folds) or
        len(folds)<MIN_TEST_WINDOWS or schedule.get("test_windows")!=len(folds)
        or schedule.get("exploratory_date_count_gate") is not True):
        raise ValueError("Fitted folds do not reconcile with plan")
    buckets={b:([],[],[]) for b in BPS};last_exit=None
    cutoff=_day(schedule["label_cutoff"])
    for f,p in zip(folds,planned):
        keys=("signal_date","entry_date","exit_date","last_mature_training_exit","training_rows","test_rows")
        if any(f.get(k)!=p.get(k) for k in keys):
            raise ValueError("Fold receipt differs from predeclared plan")
        signal,entry,exit_,train_exit=map(_day,(f["signal_date"],f["entry_date"],f["exit_date"],f["last_mature_training_exit"]))
        if (not train_exit<signal<entry<exit_<=cutoff or last_exit is not None and signal<=last_exit
            or type(p.get("training_dates")) is not int or p["training_dates"]<MIN_TRAIN_DATES
            or type(f["training_rows"]) is not int or f["training_rows"]<MIN_TRAIN_ROWS
            or type(f["test_rows"]) is not int or not 5<=f["test_rows"]<=1990
            or type(f.get("selected_count")) is not int or f["selected_count"]!=ceil(.2*f["test_rows"])):
            raise ValueError("Noncausal or invalid fold")
        for k in ("fitted_state_sha256","selection_sha256"):
            if type(f.get(k)) is not str or not DIGEST.fullmatch(f[k]):
                raise ValueError("Missing fit or selection checksum")
        cases=f.get("cost_scenarios")
        if type(cases) is not list or len(cases)!=len(BPS):
            raise ValueError("All fixed cost cases required")
        prev=None
        for b,c in zip(BPS,cases):
            if type(c) is not dict or c.get("slippage_each_way_bps")!=b:
                raise ValueError("Cost scenario order changed")
            a,e,x=(c[k] for k in ("selected_net","equal_weight_net","net_excess"))
            if (any(type(v) not in (int,float) or not isfinite(v) for v in (a,e,x))
                or not -1<a<=10 or not -1<e<=10 or not isclose(a-e,x,rel_tol=0,abs_tol=1e-12)
                or prev is not None and (a>prev[0]+1e-12 or e>prev[1]+1e-12)):
                raise ValueError("Invalid or nonmonotone scenario returns")
            for seq,v in zip(buckets[b],(a,e,x)):seq.append(v)
            prev=(a,e)
        last_exit=exit_
    for b,(a,e,x) in buckets.items():
        base["scenarios"].append({"slippage_each_way_bps":b,
            "selected":_metrics(a),"equal_weight":_metrics(e),
            "mean_net_excess":mean(x),"median_net_excess":median(x),
            "positive_excess_window_fraction":sum(v>0 for v in x)/len(x),
            "worst_window_excess":min(x)})
    worst=base["scenarios"][-1]
    if not isclose(worst["mean_net_excess"],result["mean_worst_cost_excess"],rel_tol=0,abs_tol=1e-12):
        raise ValueError("Mean excess receipt mismatch")
    base["status"]="HYPOTHETICAL_DESCRIPTIVE_RISK_ONLY"
    # Descriptive flag, not an alpha or release gate.
    base["positive_mean_excess_all_cost_cases"]=all(s["mean_net_excess"]>0 for s in base["scenarios"])
    return base
