"""Optional CPU LightGBM adapter; no automatic installs or network access."""
from __future__ import annotations

from importlib import import_module
from importlib.metadata import version, PackageNotFoundError
import numpy as np

LIGHTGBM_VERSION="4.6.0"
LIGHTGBM_ROUNDS=64
LIGHTGBM_RECIPE={
    "objective":"binary","learning_rate":0.05,
    "num_leaves":15,"max_depth":4,"min_data_in_leaf":20,
    "lambda_l2":1.0,"lambda_l1":0.0,"bagging_fraction":1.0,
    "feature_fraction":1.0,"seed":20261126,"num_threads":1,
    "device_type":"cpu","deterministic":True,"force_col_wise":True,
    "verbosity":-1,
}


def fit_lightgbm(X,y):
    """Train only on already validated and purged arrays.

    Require the exact optional package version; no substitute estimator.
    CPU-only single thread, fixed iterations, no evaluation/early stopping
    on prediction labels. Model text is used only for fingerprinting.
    """
    try:
        installed=version("lightgbm")
    except PackageNotFoundError as exc:
        raise RuntimeError("Optional LightGBM 4.6.0 is not installed") from exc
    if installed!=LIGHTGBM_VERSION:
        raise RuntimeError("Unexpected LightGBM version")
    lib=import_module("lightgbm")
    if lib.__version__!=LIGHTGBM_VERSION:
        raise RuntimeError("Imported LightGBM version mismatch")
    if set(np.unique(y))!={0,1}:
        raise ValueError("Unexpected binary labels")
    dataset=lib.Dataset(X,label=y)
    booster=lib.train(dict(LIGHTGBM_RECIPE),dataset,num_boost_round=LIGHTGBM_ROUNDS)
    model_text=booster.model_to_string()
    def predict(x):
        p=float(booster.predict(np.asarray([x]),num_threads=1)[0])
        if not np.isfinite(p) or not 0<=p<=1:
            raise ValueError("Invalid LightGBM probability")
        return p
    return {"version":installed,"model_text":model_text},predict
