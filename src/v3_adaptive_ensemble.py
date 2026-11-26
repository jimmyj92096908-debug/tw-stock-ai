"""Past-only adaptive blend of the existing logistic and forest archives.

Fixed candidate weights and date-equal Brier objective. The recipe is frozen
before evaluation; this is retrospective research, not pristine validation.
No external dependencies, database access or live orders.
"""
from __future__ import annotations

from collections import defaultdict
from math import fsum
from src.v3_purged_logistic_baseline import _hash, _symbol
from src.v3_probability_calibration import _day
from src.v3_capital_risk_research import _num
from src.v3_walkforward_probability_archive import walkforward_logistic_archive

GRID=(0.0,0.25,0.5,0.75,1.0)
MIN_DATES=20
MIN_ROWS=200


def adaptive_blend_archives(logistic, forest):
    """Select logistic weight on matched, fully mature previous forecast cohorts.

    Date-equal Brier loss avoids overweighting large cross sections. Tie
    preference is nearest 0.5, then smaller logistic weight. Until 20 dates
    and 200 observations are available, use the fixed 0.5 fallback. Each
    forecast and its later outcome inherit the adaptive recipe protocol,
    not either component's protocol. No calibrated probability claim.
    """
    cutoff=_day(logistic["archive_cutoff"])
    if _day(forest["archive_cutoff"])!=cutoff:
        raise ValueError("Archive cutoff mismatch")
    protocols=[a["protocol_sha256"] for a in (logistic,forest)]
    if (len(set(protocols))!=2 or any(not isinstance(p,str) or len(p)!=64
                                     or any(c not in "0123456789abcdef" for c in p)
                                     for p in protocols)):
        raise ValueError("Distinct component protocols required")
    protocol=_hash(dict(recipe="adaptive_brier_grid_v2",components=protocols,
                        logistic_weights=list(GRID),min_dates=MIN_DATES,
                        min_rows=MIN_ROWS,fallback=0.5,objective="date_equal_brier",
                        tie="nearest_half_then_lower"))
    def index(archive, field):
        result={}
        for r in archive[field]:
            s=_symbol(r)
            signal,trained=map(_day,(r["signal_date"],r["training_labels_through"]))
            if not trained<signal<cutoff or r["protocol_sha256"]!=archive["protocol_sha256"]:
                raise ValueError("Invalid component prediction chronology or protocol")
            _num(r["probability"],"probability",0,1)
            key=(signal,r["market"],s)
            if key in result:
                raise ValueError("Duplicate component observation")
            result[key]=r
        return result
    pa,pb=[index(a,"predictions") for a in (logistic,forest)]
    oa,ob=[index(a,"mature_outcomes") for a in (logistic,forest)]
    if set(pa)!=set(pb) or set(oa)!=set(ob) or not set(oa)<=set(pa):
        raise ValueError("Unmatched component cohorts")
    cohorts, forecasts=defaultdict(list),defaultdict(list)
    for key in sorted(pa):
        a,b=pa[key],pb[key]
        if a["training_labels_through"]!=b["training_labels_through"]:
            raise ValueError("Component training cutoff mismatch")
        forecasts[key[0]].append(key)
        if key not in oa:
            continue
        x,y=oa[key],ob[key]
        fields=("net_return","exit_date","label_available_date","cohort_available_date",
                "training_labels_through")
        if any(x[f]!=y[f] for f in fields):
            raise ValueError("Component outcome mismatch")
        for pred,out in ((a,x),(b,y)):
            if pred["probability"]!=out["probability"] or pred["training_labels_through"]!=out["training_labels_through"]:
                raise ValueError("Outcome does not match forecast")
        ex,avail,cohort=map(_day,(x["exit_date"],x["label_available_date"],x["cohort_available_date"]))
        if not key[0]<ex<=avail<=cohort<cutoff:
            raise ValueError("Immature archive outcome")
        net=_num(x["net_return"],"net return",-1,1000)
        cohorts[key[0]].append((cohort,a["probability"],b["probability"],int(net>0),key))
    mature=[]
    for day,records in sorted(cohorts.items()):
        if (len(records)!=len(forecasts[day])
                or len({r[0] for r in records})!=1
                or records[0][0]!=max(_day(oa[r[4]]["label_available_date"]) for r in records)):
            raise ValueError("Partial or inconsistent maturity cohort")
        scores=[fsum((w*a+(1-w)*b-y)**2 for _,a,b,y,_ in records)/len(records)
                for w in GRID]
        mature.append((records[0][0],day,len(records),scores))
    mature.sort()
    sums=[0.0]*len(GRID)
    count=0
    pointer=0
    prediction_rows,outcomes,weight_log=[],[],[]
    for day,keys in sorted(forecasts.items()):
        while pointer<len(mature) and mature[pointer][0]<day:
            _,_,n,scores=mature[pointer]
            count+=n
            for i,v in enumerate(scores):
                sums[i]+=v
            pointer+=1
        if pointer>=MIN_DATES and count>=MIN_ROWS:
            best=min(range(len(GRID)),key=lambda i:(round(sums[i]/pointer,12),abs(GRID[i]-.5),GRID[i]))
            w=GRID[best]
            status="PAST_ONLY_GRID_SELECTION"
        else:
            w=.5
            status="FIXED_FALLBACK"
        weight_log.append(dict(signal_date=day.isoformat(),logistic_weight=w,forest_weight=1-w,
                               mature_training_dates=pointer,mature_training_rows=count,status=status,
                               latest_cohort_available=mature[pointer-1][0].isoformat() if pointer else None))
        for key in keys:
            p=dict(pa[key],probability=w*pa[key]["probability"]+(1-w)*pb[key]["probability"],
                   protocol_sha256=protocol)
            if status=="PAST_ONLY_GRID_SELECTION":
                p["training_labels_through"]=max(p["training_labels_through"],mature[pointer-1][0].isoformat())
            prediction_rows.append(p)
            if key in oa:
                outcomes.append(dict(p,**{f:oa[key][f] for f in ("net_return","exit_date",
                                   "label_available_date","cohort_available_date")}))
    return {"protocol_sha256":protocol,"archive_cutoff":cutoff.isoformat(),
            "predictions":prediction_rows,"mature_outcomes":outcomes,"weight_log":weight_log,
            "forecast_sha256":_hash(prediction_rows),"weight_log_sha256":_hash(weight_log),
            "source_provenance_verified":False,"pristine_holdout_verified":False,
            "calibrated_probability":False,"model_release":"BLOCKED","trading_approved":False}


def walkforward_adaptive_ensemble(**kwargs):
    """Generate both component archives with the same supplied source inputs."""
    return adaptive_blend_archives(
        walkforward_logistic_archive(**kwargs,model_kind="logistic"),
        walkforward_logistic_archive(**kwargs,model_kind="forest"))
