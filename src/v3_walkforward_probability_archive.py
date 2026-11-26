"""Offline expanding walk-forward logistic prediction archive.

Produces chronological out-of-fold forecasts and a separate mature evidence
stream. No source authentication, complete roster proof, live trading,
or pristine holdout claim. Uses the existing NumPy baseline.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json

from src.v3_purged_logistic_baseline import purged_logistic_predictions
from src.v3_probability_calibration import _day
from src.v3_capital_risk_research import _num


def walkforward_logistic_archive(*, rows, feature_names, label_protocol_sha256,
                                 evaluation_dates, archive_cutoff, model_kind="logistic"):
    """Fit independently at each declared decision date using older cohorts.

    All supplied rows carry realized labels for offline research. Evaluation
    forecasts receive only explicitly allowlisted pre-decision fields.
    A whole signal cohort is withheld until all its labels are available
    strictly before the evidence cutoff. Later labels never enter forecasts
    or evidence for an earlier date. Dates must be chosen before evaluation;
    caller must independently prove this and source completeness.
    """
    cutoff = _day(archive_cutoff)
    if (not isinstance(rows,list) or not 1<=len(rows)<=200000
            or not isinstance(evaluation_dates,list) or not 1<=len(evaluation_dates)<=1260):
        raise ValueError("Invalid archive inputs")
    days=[_day(d) for d in evaluation_dates]
    if any(a>=b for a,b in zip(days,days[1:])) or days[-1]>=cutoff:
        raise ValueError("Invalid ordered evaluation dates")
    groups=defaultdict(list)
    seen=set()
    for r in rows:
        signal,ex,available=map(_day,(r["signal_date"],r["exit_date"],r["label_available_date"]))
        if not signal<ex<=available or signal>=cutoff:
            raise ValueError("Invalid archive label chronology")
        if r.get("label_protocol_sha256")!=label_protocol_sha256:
            raise ValueError("Mixed label protocols")
        key=(signal,r["stock_id"])
        if key in seen:
            raise ValueError("Duplicate archive signal")
        seen.add(key)
        _num(r["net_return"],"net outcome",-1,1000)
        groups[signal].append(r)
    if not set(days)<=set(groups):
        raise ValueError("Missing evaluation cohort")
    ordered=sorted(groups)
    past=[]
    pointer=0
    forecasts=[]
    folds=[]
    emitted_by_day={}
    protocol=None
    for day in days:
        while pointer<len(ordered) and ordered[pointer]<day:
            past.extend(groups[ordered[pointer]])
            pointer+=1
        current=groups[day]
        # Explicit allowlist; do not pass realized outcomes to predictor.
        candidates=[{k:r[k] for k in ("stock_id","market","currently_listed",
                         "signal_date","feature_available_date",
                         "feature_vintage_declared","features")} for r in current]
        fit=purged_logistic_predictions(feature_names=feature_names,
                     label_protocol_sha256=label_protocol_sha256,
                     training_rows=past,prediction_rows=candidates,
                     decision_date=day.isoformat(),model_kind=model_kind)
        if protocol is not None and protocol!=fit["protocol_sha256"]:
            raise AssertionError("Strategy protocol changed between folds")
        protocol=fit["protocol_sha256"]
        folds.append({"signal_date":day.isoformat(),"status":fit["status"],
                     "training_rows":fit["training_rows"],"training_dates":fit["training_dates"],
                     "purged_dates":fit["purged_dates"],
                     "fit_sha256":fit.get("fit_sha256"),
                     "training_labels_through":fit.get("training_labels_through"),
                     "prediction_count":len(fit["predictions"])})
        forecasts.extend(fit["predictions"])
        if fit["predictions"]:
            latest=max(_day(r["label_available_date"]) for r in current)
            lookup={r["stock_id"]:r for r in current}
            emitted_by_day[day]=(latest,[dict(p,exit_date=lookup[p["stock_id"]]["exit_date"],
                    label_available_date=lookup[p["stock_id"]]["label_available_date"],
                    cohort_available_date=latest.isoformat(),
                    net_return=lookup[p["stock_id"]]["net_return"]) for p in fit["predictions"]])
    mature=[r for d,(available,records) in sorted(emitted_by_day.items())
            if available<cutoff for r in records]
    fingerprint=sha256(json.dumps(forecasts,sort_keys=True,separators=(",",":"),
                                   allow_nan=False).encode()).hexdigest()
    return {"protocol_sha256":protocol,"archive_cutoff":archive_cutoff,
            "folds":folds,"predictions":forecasts,"mature_outcomes":mature,
            "forecast_sha256":fingerprint,
            "source_provenance_verified":False,"cohort_completeness_verified":False,
            "pristine_holdout_verified":False,"survivorship_bias_possible":True,
            "model_release":"BLOCKED","trading_approved":False}


def mature_evidence_before(archive, *, decision_date):
    """Filter archive outcomes by entire-cohort label availability.

    This is a temporal filter, not authentication of an externally supplied
    archive. No future evidence is returned or usable by the allocator.
    """
    day=_day(decision_date)
    if day>_day(archive["archive_cutoff"]):
        raise ValueError("Decision beyond archive cutoff")
    selected=[]
    for row in archive["mature_outcomes"]:
        trained,signal,exit_day,available,cohort=map(_day,(
            row["training_labels_through"],row["signal_date"],row["exit_date"],
            row["label_available_date"],row["cohort_available_date"]))
        if not trained<signal<exit_day<=available<=cohort:
            raise ValueError("Invalid archive outcome chronology")
        if cohort<day:
            selected.append(dict(row))
    return selected
