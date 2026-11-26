"""Five-model, past-only adaptive probability mixture for offline V3 research.

Fixed simplex grid with 20 percentage point increments. Date-equal Brier
objective; no tuning on current/future labels. No source authentication or
release approval. The five component archives must cover identical cohorts.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import product
from math import fsum
import numpy as np

from src.v3_purged_logistic_baseline import _hash, _symbol
from src.v3_probability_calibration import _day
from src.v3_capital_risk_research import _num
from src.v3_walkforward_probability_archive import walkforward_logistic_archive

MODELS=("logistic","forest","lightgbm","xgboost","catboost")
GRID=tuple(w for w in product(range(6),repeat=5) if sum(w)==5)
MIN_DATES=20
MIN_ROWS=200


def adaptive_five_blend(archives, *, regimes=None):
    """Return forecasts, matched mature outcomes and auditable weight history.

    Archives must contain distinct protocols and matched forecasts/outcomes.
    Date-cohort residual Gram matrices make the 126-candidate grid cheap.
    Uniform weights until sufficient mature historical forecasts exist;
    ties favor weights nearest uniform, then lexicographic order.
    """
    if not isinstance(archives,dict) or set(archives)!=set(MODELS):
        raise ValueError("Exactly five named component archives required")
    cutoff=_day(archives[MODELS[0]]["archive_cutoff"])
    protocols=[archives[k]["protocol_sha256"] for k in MODELS]
    if (any(not isinstance(p,str) or len(p)!=64 or any(c not in "0123456789abcdef" for c in p) for p in protocols)
            or len(set(protocols))!=5
            or any(_day(archives[k]["archive_cutoff"])!=cutoff for k in MODELS)):
        raise ValueError("Invalid component protocols or cutoff")
    protocol=_hash(dict(recipe="five_model_simplex_brier_v1",models=list(MODELS),
                        components=protocols,grid_units=5,min_dates=MIN_DATES,
                        min_rows=MIN_ROWS,tie="rounded12_nearest_uniform_lexicographic",
                        objective="date_equal_brier"))
    def index(archive,field):
        result={}
        rows=archive[field]
        if not isinstance(rows,list) or len(rows)>200000:
            raise ValueError("Invalid bounded archive rows")
        for r in rows:
            stock=_symbol(r)
            signal,trained=map(_day,(r["signal_date"],r["training_labels_through"]))
            if not trained<signal<cutoff or r["protocol_sha256"]!=archive["protocol_sha256"]:
                raise ValueError("Invalid component chronology or protocol")
            _num(r["probability"],"probability",0,1)
            key=(signal,r["market"],stock)
            if key in result:
                raise ValueError("Duplicate component observation")
            result[key]=r
        return result
    preds=[index(archives[k],"predictions") for k in MODELS]
    outs=[index(archives[k],"mature_outcomes") for k in MODELS]
    if any(set(p)!=set(preds[0]) for p in preds) or any(set(o)!=set(outs[0]) for o in outs) or not set(outs[0])<=set(preds[0]):
        raise ValueError("Unmatched component cohorts")
    days,cohorts=defaultdict(list),defaultdict(list)
    fields=("net_return","exit_date","label_available_date","cohort_available_date","training_labels_through")
    for key in sorted(preds[0]):
        first=preds[0][key]
        if any(p[key]["training_labels_through"]!=first["training_labels_through"] for p in preds):
            raise ValueError("Component training cutoff mismatch")
        days[key[0]].append(key)
        if key not in outs[0]:
            continue
        row=outs[0][key]
        if any(any(o[key][f]!=row[f] for f in fields) for o in outs):
            raise ValueError("Component outcomes mismatch")
        for p,o in zip(preds,outs):
            if any(p[key][f]!=o[key][f] for f in ("probability","training_labels_through")):
                raise ValueError("Outcome does not match forecast")
        ex,available,cohort=map(_day,(row["exit_date"],row["label_available_date"],row["cohort_available_date"]))
        if not key[0]<ex<=available<=cohort<cutoff:
            raise ValueError("Immature archive outcome")
        y=int(_num(row["net_return"],"net return",-1,1000)>0)
        cohorts[key[0]].append((cohort,key,[p[key]["probability"]-y for p in preds]))
    states={}
    if regimes is not None:
        if (regimes["index_id"]!="TWSE_TAIEX" or
                _hash(regimes["states"])!=regimes["states_sha256"]):
            raise ValueError("Invalid regime archive")
        for state in regimes["states"]:
            d=_day(state["signal_date"])
            trend=state["regime"]
            volatile=state["volatile_heuristic"]
            if (d in states or trend not in ("UPTREND","DOWNTREND","RANGE_OR_TRANSITION","UNKNOWN_HISTORY")
                    or type(volatile) is not bool
                    or (trend!="UNKNOWN_HISTORY" and state["last_available_close"]!=d.isoformat())):
                raise ValueError("Invalid regime state")
            states[d]=(trend,volatile)
        if not set(days)<=set(states):
            raise ValueError("Missing forecast-date regime")
        protocol=_hash(dict(recipe="five_model_regime_simplex_v1",base_protocol=protocol,
                            min_dates=MIN_DATES,min_rows=MIN_ROWS,
                            fallback="global_then_uniform",unknown="uniform_no_new_exposure"))
    mature=[]
    for day,records in sorted(cohorts.items()):
        if (len(records)!=len(days[day]) or len({r[0] for r in records})!=1
                or records[0][0]!=max(_day(outs[0][r[1]]["label_available_date"]) for r in records)):
            raise ValueError("Partial or inconsistent maturity cohort")
        residual=np.asarray([r[2] for r in records],dtype=np.float64)
        mature.append((records[0][0],day,len(records),residual.T@residual/len(records)))
    mature.sort(key=lambda r:(r[0],r[1]))
    gram=np.zeros((5,5))
    grid=np.asarray(GRID,dtype=np.float64)/5
    pointer=count=0
    by_state={}
    latest_global=None
    forecasts,outcomes,weight_log=[],[],[]
    for day,keys in sorted(days.items()):
        while pointer<len(mature) and mature[pointer][0]<day:
            available,signal,n,matrix=mature[pointer]
            gram+=matrix
            count+=n
            latest_global=available
            if regimes is not None:
                state=states[signal]
                if state[0]!="UNKNOWN_HISTORY":
                    g,nd,nr,_=by_state.get(state,(np.zeros((5,5)),0,0,None))
                    by_state[state]=(g+matrix,nd+1,nr+n,available)
            pointer+=1
        state=states.get(day)
        chosen_gram,nd,nr,latest=gram,pointer,count,latest_global
        status="PAST_ONLY_SIMPLEX_SELECTION"
        if state is not None:
            g,dn,rn,la=by_state.get(state,(None,0,0,None))
            if state[0]=="UNKNOWN_HISTORY":
                nd=nr=0
                latest=None
            elif dn>=MIN_DATES and rn>=MIN_ROWS:
                chosen_gram,nd,nr,latest=g,dn,rn,la
                status="REGIME_MATCHED_SELECTION"
            else:
                status="GLOBAL_FALLBACK_SELECTION"
        if nd>=MIN_DATES and nr>=MIN_ROWS:
            scores=np.einsum("ij,jk,ik->i",grid,chosen_gram/nd,grid)
            best=min(range(len(GRID)),key=lambda i:(round(float(scores[i]),12),
                       sum((x-1)**2 for x in GRID[i]),GRID[i]))
            units=GRID[best]
        else:
            units=(1,1,1,1,1)
            status="UNIFORM_FALLBACK"
        weights=[x/5 for x in units]
        weight_log.append(dict(signal_date=day.isoformat(),weights=dict(zip(MODELS,weights)),
                               status=status,mature_training_dates=nd,mature_training_rows=nr,
                               latest_cohort_available=latest.isoformat() if latest else None))
        if state is not None:
            weight_log[-1].update(regime=state[0],volatile_heuristic=state[1],
                                  new_exposure_blocked_by_regime=state[0]=="UNKNOWN_HISTORY")
        for key in keys:
            probability=min(1.,max(0.,fsum(w*p[key]["probability"] for w,p in zip(weights,preds))))
            row=dict(preds[0][key],probability=probability,protocol_sha256=protocol)
            if state is not None:
                # Meta-estimator also learns from mature forecast cohorts.
                if latest is not None and status!="UNIFORM_FALLBACK":
                    row["training_labels_through"]=max(row["training_labels_through"],latest.isoformat())
                row.update(regime=state[0],volatile_heuristic=state[1])
            forecasts.append(row)
            if key in outs[0]:
                outcomes.append(dict(row,**{f:outs[0][key][f] for f in fields if f!="training_labels_through"}))
    return {"protocol_sha256":protocol,"archive_cutoff":cutoff.isoformat(),
            "predictions":forecasts,"mature_outcomes":outcomes,"weight_log":weight_log,
            "forecast_sha256":_hash(forecasts),"weight_log_sha256":_hash(weight_log),
            "grid_candidates":len(GRID),"source_provenance_verified":False,
            "pristine_holdout_verified":False,"calibrated_probability":False,
            "model_release":"BLOCKED","trading_approved":False}


def walkforward_five_ensemble(**kwargs):
    """Generate all five archives on identical data; missing backend fails closed."""
    return adaptive_five_blend({k:walkforward_logistic_archive(**kwargs,model_kind=k) for k in MODELS})
