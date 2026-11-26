"""Chronologically frozen forest hyperparameter selection for V3 research.

Three predeclared depth candidates, selected on a separate
development window only. Holdout outcomes never participate in selection.
This is retrospective research; the caller must independently prove
the dates and protocol were committed before observing holdout outcomes.
"""
from __future__ import annotations

from collections import defaultdict
from math import fsum
from src.v3_purged_logistic_baseline import _hash
from src.v3_numpy_forest import FOREST_DEPTH_GRID
from src.v3_probability_calibration import _day
from src.v3_walkforward_probability_archive import walkforward_logistic_archive

MIN_DATES=20
MIN_ROWS=200


def frozen_forest_tuning(*,rows,feature_names,label_protocol_sha256,
                           development_dates,holdout_dates,selection_cutoff,archive_cutoff):
    """Choose depth from mature development forecasts, then freeze for holdout.

    Development archives are generated from rows strictly before the
    selection cutoff. Holdout uses expanding refits with the frozen depth;
    previous holdout outcomes may enter later refits after maturation,
    but never change the selected hyperparameter.
    """
    selection=_day(selection_cutoff)
    end=_day(archive_cutoff)
    if not isinstance(rows,list) or not 1<=len(rows)<=200000:
        raise ValueError("Invalid research rows")
    if not isinstance(development_dates,list) or not isinstance(holdout_dates,list):
        raise ValueError("Expected ordered date lists")
    dev=[_day(d) for d in development_dates]
    hold=[_day(d) for d in holdout_dates]
    if (not dev or not hold or any(a>=b for a,b in zip(dev,dev[1:]))
            or any(a>=b for a,b in zip(hold,hold[1:]))
            or not dev[-1]<selection<=hold[0]<=hold[-1]<end):
        raise ValueError("Invalid separated development and holdout windows")
    early=[r for r in rows if _day(r["signal_date"])<selection]
    scores=[]
    reference=None
    for depth in FOREST_DEPTH_GRID:
        archive=walkforward_logistic_archive(rows=early,feature_names=feature_names,
                    label_protocol_sha256=label_protocol_sha256,evaluation_dates=development_dates,
                    archive_cutoff=selection_cutoff,model_kind="forest",forest_depth=depth)
        daily=defaultdict(list)
        keys=[]
        for r in archive["mature_outcomes"]:
            keys.append((r["signal_date"],r["market"],r["stock_id"],r["net_return"],
                         r["label_available_date"],r["cohort_available_date"]))
            daily[r["signal_date"]].append((r["probability"]-int(r["net_return"]>0))**2)
        if reference is None:
            reference=keys
        elif reference!=keys:
            raise ValueError("Candidate development samples differ")
        adequate=len(daily)>=MIN_DATES and len(keys)>=MIN_ROWS
        score=fsum(fsum(v)/len(v) for v in daily.values())/len(daily) if adequate else None
        scores.append(dict(depth=depth,brier=score,rows=len(keys),dates=len(daily),
                           protocol_sha256=archive["protocol_sha256"]))
    adequate=all(x["brier"] is not None for x in scores)
    report={"development_scores":scores,"selection_cutoff":selection_cutoff,
            "selected_depth":None,"selection_sha256":None,"holdout_archive":None,
            "status":"INSUFFICIENT_DEVELOPMENT_EVIDENCE",
            "pristine_holdout_verified":False,"source_provenance_verified":False,
            "model_release":"BLOCKED","trading_approved":False}
    if not adequate:
        return report
    winner=min(scores,key=lambda x:(round(x["brier"],12),x["depth"]!=4,x["depth"]))
    digest=_hash(dict(recipe="frozen_forest_depth_development_v1",
                      selection_cutoff=selection_cutoff,development_dates=development_dates,
                      holdout_dates=holdout_dates,scores=scores,selected_depth=winner["depth"],
                      evidence_sha256=_hash(reference)))
    holdout=walkforward_logistic_archive(rows=rows,feature_names=feature_names,
               label_protocol_sha256=label_protocol_sha256,evaluation_dates=holdout_dates,
               archive_cutoff=archive_cutoff,model_kind="forest",forest_depth=winner["depth"])
    if holdout["protocol_sha256"]!=winner["protocol_sha256"]:
        raise AssertionError("Selected model recipe changed")
    # The strategy protocol must distinguish a selected recipe from one
    # preassigned without any development selection.
    selected_protocol=_hash(dict(recipe="frozen_selected_forest_v1",
                                 component=winner["protocol_sha256"],selection=digest))
    holdout["component_protocol_sha256"]=holdout["protocol_sha256"]
    holdout["protocol_sha256"]=selected_protocol
    for field in ("predictions","mature_outcomes"):
        for row in holdout[field]:
            row["protocol_sha256"]=selected_protocol
    holdout["forecast_sha256"]=_hash(holdout["predictions"])
    report.update(status="FROZEN_DEVELOPMENT_SELECTION",selected_depth=winner["depth"],
                  selection_sha256=digest,holdout_archive=holdout)
    return report
