"""Optional pinned XGBoost CPU adapter for offline V3 research."""
from __future__ import annotations

from importlib import import_module
from importlib.metadata import version, PackageNotFoundError
from hashlib import sha256
import numpy as np

XGBOOST_VERSION="2.1.4"
XGBOOST_ROUNDS=64
XGBOOST_RECIPE={
    "objective":"binary:logistic","eval_metric":"logloss",
    "tree_method":"hist","device":"cpu","max_depth":4,
    "eta":0.05,"min_child_weight":5,"lambda":1.0,"alpha":0.0,
    "subsample":1.0,"colsample_bytree":1.0,"max_bin":128,
    "seed":20261126,"nthread":1,"verbosity":0,
}


def fit_xgboost(X,y,*,depth=4):
    """Train the native binary booster only on chronologically purged rows.

    The optional CPU-only distribution is required exactly; neither a
    missing package nor a different package may silently select a fallback.
    Fixed rounds and no prediction-label evaluation or early stopping.
    """
    if type(depth) is not int or depth not in (2,4,6):
        raise ValueError("Unsupported booster depth")
    try:
        installed=version("xgboost-cpu")
    except PackageNotFoundError as exc:
        raise RuntimeError("Optional XGBoost CPU 2.1.4 is not installed") from exc
    if installed!=XGBOOST_VERSION:
        raise RuntimeError("Unexpected XGBoost CPU version")
    try:
        version("xgboost")
    except PackageNotFoundError:
        pass
    else:
        raise RuntimeError("Conflicting full XGBoost distribution")
    lib=import_module("xgboost")
    if lib.__version__!=XGBOOST_VERSION:
        raise RuntimeError("Imported XGBoost version mismatch")
    matrix=lib.DMatrix(X,label=y,nthread=1)
    booster=lib.train(dict(XGBOOST_RECIPE,max_depth=depth),matrix,num_boost_round=XGBOOST_ROUNDS)
    fingerprint=sha256(bytes(booster.save_raw(raw_format="ubj"))).hexdigest()
    def predict(x):
        p=float(booster.predict(lib.DMatrix(np.asarray([x]),nthread=1))[0])
        if not np.isfinite(p) or not 0<=p<=1:
            raise ValueError("Invalid XGBoost probability")
        return p
    return {"version":installed,"booster_sha256":fingerprint},predict
