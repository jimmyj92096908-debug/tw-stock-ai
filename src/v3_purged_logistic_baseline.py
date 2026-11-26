"""Deterministic NumPy logistic baseline for purged V3 probability research.

This is a baseline, not the planned tree ensemble. No new dependencies,
database access, or live trading. Labels are supplied net outcomes of a
declared frozen strategy; source flags and hashes are not authentication.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import re
import numpy as np

from src.v3_probability_calibration import _day
from src.v3_capital_risk_research import _num
from src.v3_numpy_forest import FOREST_RECIPE, fit_forest, forest_probability

MIN_TRAIN_DATES = 20
MIN_TRAIN_ROWS = 200
MIN_CLASS_ROWS = 20
ITERATIONS = 300
L2 = 0.1
LEARNING_RATE = 0.1


def _hash(obj):
    return sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),
                             allow_nan=False).encode()).hexdigest()


def _symbol(row):
    s = row["stock_id"]
    if (row["market"] not in ("TWSE","TPEx") or not isinstance(s,str)
            or not s.isascii() or not s.isdigit() or s in ("1589","1808")
            or row.get("currently_listed") is not True):
        raise ValueError("Invalid or excluded instrument")
    return s


def purged_logistic_predictions(*, feature_names, label_protocol_sha256,
                                training_rows, prediction_rows, decision_date,
                                model_kind="logistic"):
    """Fit only complete supplied signal cohorts with mature labels.

    A date cohort with any label not available strictly before decision is
    skipped in its entirety. Missing cohort members cannot be detected;
    the caller must prove roster completeness and historical source vintage.
    Prediction rows must not contain outcome fields. Fixed recipe, no tuning.
    Feature availability is checked at date granularity, not intraday time.
    """
    if model_kind not in ("logistic","forest"):
        raise ValueError("Unsupported model kind")
    cutoff = _day(decision_date)
    if (not isinstance(feature_names,(tuple,list)) or not 1<=len(feature_names)<=64
            or any(not isinstance(n,str) or not re.fullmatch("[a-zA-Z][a-zA-Z0-9_]{0,63}",n)
                   or re.search("future|label|target|exit|forward|net_return",n,re.I)
                   for n in feature_names)
            or len(set(feature_names))!=len(feature_names)):
        raise ValueError("Invalid feature schema")
    if not isinstance(label_protocol_sha256,str) or re.fullmatch("[0-9a-f]{64}",label_protocol_sha256) is None:
        raise ValueError("Invalid label protocol")
    if (not isinstance(training_rows,list) or len(training_rows)>200000
            or not isinstance(prediction_rows,list) or len(prediction_rows)>2000):
        raise ValueError("Invalid research rows")
    protocol = _hash(dict(recipe="numpy_logistic_fixed_v1",features=list(feature_names),
                          label_protocol_sha256=label_protocol_sha256,
                          iterations=ITERATIONS,l2=L2,learning_rate=LEARNING_RATE,
                          min_dates=MIN_TRAIN_DATES,min_rows=MIN_TRAIN_ROWS,
                          min_class=MIN_CLASS_ROWS,clip=8))
    if model_kind == "forest":
        protocol = _hash(dict(recipe="numpy_forest_fixed_v1",features=list(feature_names),
                              label_protocol_sha256=label_protocol_sha256,
                              min_dates=MIN_TRAIN_DATES,min_rows=MIN_TRAIN_ROWS,
                              min_class=MIN_CLASS_ROWS,forest=FOREST_RECIPE))
    def features(row,signal):
        if (_day(row["feature_available_date"])>signal
                or row.get("feature_vintage_declared") is not True):
            raise ValueError("Feature chronology or vintage declaration missing")
        values = row["features"]
        if not isinstance(values,dict) or set(values)!=set(feature_names):
            raise ValueError("Feature schema mismatch")
        return [_num(values[n],"feature", -1e9,1e9) for n in feature_names]
    groups, seen = defaultdict(list), set()
    for row in training_rows:
        s = _symbol(row)
        signal, exit_day, available = map(_day,(row["signal_date"],row["exit_date"],
                                                row["label_available_date"]))
        if not signal < exit_day <= available or signal >= cutoff:
            raise ValueError("Invalid training chronology")
        if row.get("label_protocol_sha256")!=label_protocol_sha256:
            raise ValueError("Mixed label protocols")
        key=(signal,s)
        if key in seen:
            raise ValueError("Duplicate training signal")
        seen.add(key)
        x=features(row,signal)
        y=_num(row["net_return"],"net return",-1,1000)
        groups[signal].append((s,available,x,int(y>0)))
    mature=[(d,sorted(v)) for d,v in sorted(groups.items())
            if all(row[1]<cutoff for row in v)]
    samples=[row for _,cohort in mature for row in cohort]
    candidates, seen = [], set()
    for row in prediction_rows:
        s=_symbol(row)
        signal=_day(row["signal_date"])
        if (signal!=cutoff or s in seen
                or set(row)&{"net_return","exit_date","label_available_date","label","target","future_return"}):
            raise ValueError("Invalid or outcome-bearing prediction")
        seen.add(s)
        candidates.append((s,row["market"],features(row,signal)))
    report={"protocol_sha256":protocol,"training_rows":len(samples),
            "training_dates":len(mature),"purged_dates":len(groups)-len(mature),
            "predictions":[],"status":"INSUFFICIENT_MATURE_TRAINING",
            "source_provenance_verified":False,"cohort_completeness_verified":False,
            "survivorship_bias_possible":True,"calibrated_probability":False,
            "model_release":"BLOCKED","trading_approved":False}
    if len(mature)<MIN_TRAIN_DATES or len(samples)<MIN_TRAIN_ROWS:
        return report
    y=np.asarray([r[3] for r in samples],dtype=np.float64)
    if min(y.sum(),len(y)-y.sum())<MIN_CLASS_ROWS:
        return report
    X=np.asarray([r[2] for r in samples],dtype=np.float64)
    if model_kind == "forest":
        trees=fit_forest(X,y)
        fit_parameters={"trees":trees}
        status="RETROSPECTIVE_NUMPY_FOREST"
        def predict(x):
            return forest_probability(trees,x)
    else:
        means=X.mean(axis=0)
        scales=X.std(axis=0)
        scales=np.where(scales<1e-12,1.0,scales)
        X=np.clip((X-means)/scales,-8,8)
        w=np.zeros(X.shape[1],dtype=np.float64)
        bias=0.0
        for _ in range(ITERATIONS):
            p=1/(1+np.exp(-np.clip(X@w+bias,-35,35)))
            err=p-y
            w-=LEARNING_RATE*((X.T@err)/len(y)+L2*w)
            bias-=LEARNING_RATE*float(err.mean())
        if not np.isfinite(w).all() or not np.isfinite(bias):
            raise ValueError("Nonfinite fit")
        fit_parameters=dict(w=w.tolist(),bias=bias,means=means.tolist(),scales=scales.tolist())
        status="RETROSPECTIVE_LOGISTIC_BASELINE"
        def predict(x):
            z=np.clip((np.asarray(x)-means)/scales,-8,8)
            return float(1/(1+np.exp(-np.clip(z@w+bias,-35,35))))
    last=max(r[1] for r in samples).isoformat()
    report.update(status=status,
                  training_labels_through=last,
                  fit_sha256=_hash(fit_parameters),
                  training_fingerprint=_hash([(d.isoformat(),[(s,a.isoformat(),x,y) for s,a,x,y in v])
                                              for d,v in mature]))
    for s,market,x in sorted(candidates):
        p=predict(x)
        report["predictions"].append(dict(stock_id=s,market=market,currently_listed=True,
                  signal_date=decision_date,training_labels_through=last,
                  probability=p,protocol_sha256=protocol))
    return report
