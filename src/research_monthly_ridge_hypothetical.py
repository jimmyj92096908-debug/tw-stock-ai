"""Research-only expanding Ridge on hypothetical economic labels.

Never authenticates corporate-action evidence or publication vintage. Features
and complete cohorts are supplied explicitly; no fitting on missing-label
survivors. No production weights, orders, LINE, database or network access.
"""
from collections import defaultdict
from hashlib import sha256
from math import ceil,isfinite
import json
import re
import numpy as np

from src.research_monthly_fold_plan import plan,day,MAX_DATES,MAX_COHORT
from src.research_entitlement_return import whole_cohort, num

FEATURE_NAMES=("raw_ret5","raw_ret20","raw_ma20_gap","raw_ma55_gap","raw_rsi14_fraction",
    "raw_atr14_fraction","raw_volume_vs_ma20","raw_smc_trend","raw_smc_bos_bullish",
    "raw_smc_bos_bearish","raw_smc_choch_bullish","raw_smc_choch_bearish")
RIDGE_LAMBDA=2.0
TOP_FRACTION=0.20
FEE_BPS=14.25
SELL_TAX_BPS=30
SLIPPAGE_BPS=(10,30,60)


def fingerprint(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def fit(X,y):
    X=np.asarray(X,dtype=np.float64);y=np.asarray(y,dtype=np.float64)
    mu=X.mean(axis=0);sd=X.std(axis=0)
    sd=np.where(sd<1e-12,1.0,sd)
    z=(X-mu)/sd
    w=np.linalg.solve(z.T@z+RIDGE_LAMBDA*np.eye(len(FEATURE_NAMES)),z.T@(y-y.mean()))
    if not np.all(np.isfinite(w)):
        raise ValueError("Nonfinite coefficients")
    return mu,sd,w,float(y.mean())


def net_return(raw_sale_value_ratio,cash_ratio,slippage):
    # Costs apply to purchased and liquidated share value, not dividend cash.
    # Illustrative fees/tax, no actual execution or tax treatment verification.
    entry=1+(FEE_BPS+slippage)/10000
    exit_mult=1-(FEE_BPS+SELL_TAX_BPS+slippage)/10000
    return (raw_sale_value_ratio*exit_mult+cash_ratio)/entry-1


def evaluate(feature_rows,observations,*,label_cutoff,test_start):
    """Build labels from supplied paths; fit only complete mature cohorts.

    Observations are the input dictionaries of research_entitlement_return.
    Empty observation cohorts are excluded explicitly; partial or foreign
    cohorts fail closed. The evaluation dates are selected without returns.
    """
    cutoff=day(label_cutoff)
    if type(feature_rows) is not list or not 1<=len(feature_rows)<=MAX_DATES*MAX_COHORT:
        raise ValueError("Bounded feature rows required")
    if type(observations) is not list or len(observations)>len(feature_rows):
        raise ValueError("Bounded label observations required")
    groups=defaultdict(dict);obs=defaultdict(list);months=set()
    for r in feature_rows:
        if type(r) is not dict:
            raise ValueError("Invalid feature row")
        d=r["signal_date"];dt=day(d);market=r["market"];sid=r["stock_id"];v=r["feature_vector"]
        if (dt>cutoff or market not in ("twse","tpex") or type(sid) is not str
            or not re.fullmatch(r"[0-9]{4}",sid) or sid=="1589"
            or type(v) is not list or len(v)!=len(FEATURE_NAMES)
            or any(type(x) not in (int,float) or not isfinite(x) for x in v)
            or (market,sid) in groups[d]):
            raise ValueError("Invalid or duplicate feature key")
        groups[d][market,sid]=v
    for d,g in groups.items():
        dt=day(d)
        if (dt.year,dt.month) in months or len(g)>MAX_COHORT:
            raise ValueError("One bounded signal per month required")
        months.add((dt.year,dt.month))
    if len(groups)>MAX_DATES:
        raise ValueError("Too many signal dates")
    for x in observations:
        if type(x) is not dict or x.get("signal_date") not in groups:
            raise ValueError("Foreign observation date")
        obs[x["signal_date"]].append(x)
    ready=[];data={}
    for d,g in sorted(groups.items()):
        items=obs[d];keys=sorted(g)
        record={"signal_date":d,"entry_date":None,"exit_date":None,
            "candidate_rows":len(keys),"complete_label_rows":0,"whole_cohort_aligned":False,
            "label_kind":"HYPOTHETICAL_ECONOMIC_RESEARCH_ONLY"}
        if items:
            if len(keys)<5 or len(items)!=len(keys):
                raise ValueError("Partial or insufficient observed cohort")
            # whole_cohort enforces complete identity, common session dates,
            # supported action terms and maturity before any fitting.
            summary,labels=whole_cohort(keys,items,label_cutoff=label_cutoff)
            original={(x["market"],x["stock_id"]):x for x in items}
            members=[]
            for r in labels:
                key=(r["market"],r["stock_id"])
                x=original[key]
                entry=num(x["prices"][0]["close"],positive=True)
                cash=float(num(r["cash_entitlement_per_initial_share"])/entry)
                sale=float(num(r["exit_share_entitlement"])*num(x["prices"][-1]["close"],positive=True)/entry)
                gross=float(r["hypothetical_gross_entitlement_return"])
                if not all(isfinite(v) for v in (cash,sale,gross)) or not -1<gross<=10:
                    raise ValueError("Invalid economic label")
                members.append((key,g[key],gross,sale,cash))
            data[d]=members
            record.update(entry_date=labels[0]["entry_date"],exit_date=labels[0]["exit_date"],
                          complete_label_rows=len(labels),whole_cohort_aligned=True)
        ready.append(record)
    schedule=plan(ready,label_cutoff=label_cutoff,test_start=test_start)
    result={"scope":"OFFLINE_HYPOTHETICAL_MONTHLY_RIDGE_EVALUATION","schema_version":1,
        "feature_names":list(FEATURE_NAMES),"fold_plan":schedule,"folds":[],
        "model_trained":False,"historical_total_return_verified":False,"source_labels_authenticated":False,
        "pristine_future_holdout_verified":False,"alpha_verified":False,"production_weights_updated":False,
        "liquidity_and_execution_verified":False,"transaction_tax_applicability_verified":False,
        "production_neon_reads":0,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED"}
    if not schedule["exploratory_date_count_gate"]:
        return result
    for f in schedule["folds"]:
        train=[r for d in f["training_signal_dates"] for r in data[d]]
        test=data[f["signal_date"]]
        mu,sd,w,ybar=fit([r[1] for r in train],[r[2] for r in train])
        pred=(np.asarray([r[1] for r in test])-mu)/sd@w+ybar
        if not np.all(np.isfinite(pred)):
            raise ValueError("Nonfinite prediction")
        picks=sorted(range(len(test)),key=lambda i:(-float(pred[i]),test[i][0]))[:ceil(len(test)*TOP_FRACTION)]
        chosen=[test[i] for i in picks]
        cases=[]
        for bps in SLIPPAGE_BPS:
            selected=sum(net_return(r[3],r[4],bps) for r in chosen)/len(chosen)
            baseline=sum(net_return(r[3],r[4],bps) for r in test)/len(test)
            cases.append({"slippage_each_way_bps":bps,"selected_net":selected,
                "equal_weight_net":baseline,"net_excess":selected-baseline})
        result["folds"].append({"signal_date":f["signal_date"],"entry_date":f["entry_date"],
            "exit_date":f["exit_date"],"last_mature_training_exit":f["last_mature_training_exit"],
            "training_rows":len(train),"test_rows":len(test),"selected_count":len(chosen),
            "fitted_state_sha256":fingerprint([mu.tolist(),sd.tolist(),w.tolist(),ybar]),
            "selection_sha256":fingerprint([r[0] for r in chosen]),
            "cost_scenarios":cases})
    result["model_trained"]=True
    result["mean_worst_cost_excess"]=sum(f["cost_scenarios"][-1]["net_excess"] for f in result["folds"])/len(result["folds"])
    return result
