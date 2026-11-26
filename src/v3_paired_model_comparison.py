"""Paired retrospective comparison of fixed V3 probability recipes.

Identical source rows, dates, labels and eligible cohorts for all models.
Descriptive metrics only: selected outcomes may overlap; not portfolio P&L,
not independent holdout performance or evidence of deployable probabilities.
"""
from __future__ import annotations

from collections import defaultdict
from math import fsum, log
from src.v3_walkforward_probability_archive import walkforward_logistic_archive
from src.v3_capital_risk_research import outcome_diagnostics, _num

MODEL_KINDS=("logistic","forest","ensemble")


def compare_probability_models(*, rows, feature_names, label_protocol_sha256,
                               evaluation_dates, archive_cutoff):
    """Compare fixed recipes on matched mature out-of-fold observations.

    Report probability scores and fixed >=0.8 screening outcomes separately.
    No ranking winner, threshold tuning or weight selection on these results.
    Each signal date receives equal weight in date-mean Brier loss.
    """
    archives={k:walkforward_logistic_archive(rows=rows,feature_names=feature_names,
                 label_protocol_sha256=label_protocol_sha256,evaluation_dates=evaluation_dates,
                 archive_cutoff=archive_cutoff,model_kind=k) for k in MODEL_KINDS}
    def index(records):
        out={}
        for r in records:
            key=(r["signal_date"],r["market"],r["stock_id"])
            if key in out:
                raise ValueError("Duplicate model observation")
            out[key]=r
        return out
    forecasts={k:index(v["predictions"]) for k,v in archives.items()}
    outcomes={k:index(v["mature_outcomes"]) for k,v in archives.items()}
    first=MODEL_KINDS[0]
    keys=sorted(outcomes[first])
    for k in MODEL_KINDS:
        if set(forecasts[k])!=set(forecasts[first]) or set(outcomes[k])!=set(keys):
            raise ValueError("Unmatched evaluation cohorts")
        for key in keys:
            a,b=outcomes[first][key],outcomes[k][key]
            if any(a[f]!=b[f] for f in ("net_return","exit_date","label_available_date",
                                       "cohort_available_date","training_labels_through")):
                raise ValueError("Unmatched outcome or training chronology")
    def metrics(pairs):
        if not pairs:
            return None
        by_day=defaultdict(list)
        brier,loss,correct=[],[],[]
        chosen=[]
        for key,p,r in pairs:
            y=int(r>0)
            error=(p-y)**2
            brier.append(error)
            by_day[key[0]].append(error)
            q=min(1-1e-12,max(1e-12,p))
            loss.append(-log(q if y else 1-q))
            correct.append(int((p>=.5)==bool(y)))
            if p>=.8:
                chosen.append((key,r))
        diag=outcome_diagnostics([r for _,r in chosen]) if chosen else None
        return {"observations":len(pairs),"signal_dates":len(by_day),
                "brier":fsum(brier)/len(pairs),
                "date_equal_brier":fsum(fsum(v)/len(v) for v in by_day.values())/len(by_day),
                "log_loss":fsum(loss)/len(pairs),"accuracy_at_0_5":fsum(correct)/len(pairs),
                "screened_count":len(chosen),"screened_signal_dates":len({k[0] for k,_ in chosen}),
                "screened_fraction":len(chosen)/len(pairs),"screened_outcomes":diag}
    reports={}
    for k in MODEL_KINDS:
        pairs=[(key,_num(outcomes[k][key]["probability"],"probability",0,1),
                outcomes[k][key]["net_return"]) for key in keys]
        reports[k]={"protocol_sha256":archives[k]["protocol_sha256"],
                    "forecast_sha256":archives[k]["forecast_sha256"],
                    "forecast_count":len(forecasts[k]),"metrics":metrics(pairs)}
    # Fixed 0.5 reference is not a trained or dynamically tuned baseline.
    reference=metrics([(key,.5,outcomes[first][key]["net_return"]) for key in keys])
    return {"status":"PAIRED_RETROSPECTIVE_COMPARISON" if keys else "NO_MATURE_MATCHED_OUTCOMES",
            "matched_observations":len(keys),"matched_signal_dates":len({k[0] for k in keys}),
            "models":reports,"constant_0_5_reference":reference,
            "selected_model":None,"optimized_weights":None,
            "pristine_holdout_verified":False,"source_provenance_verified":False,
            "portfolio_returns_verified":False,"dependence_verified":False,
            "model_release":"BLOCKED","trading_approved":False}
