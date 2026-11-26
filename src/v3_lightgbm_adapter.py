"""Optional CPU LightGBM adapter; no automatic installs or network access."""
from __future__ import annotations

from importlib import import_module
from importlib.metadata import version, PackageNotFoundError
import numpy as np

LIGHTGBM_VERSION="4.6.0"
LIGHTGBM_RECIPE={
    "objective":"binary","n_estimators":64,"learning_rate":0.05,
    "num_leaves":15,"max_depth":4,"min_child_samples":20,
    "reg_lambda":1.0,"reg_alpha":0.0,"subsample":1.0,
    "colsample_bytree":1.0,"random_state":20261126,"n_jobs":1,
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
    estimator=lib.LGBMClassifier(**LIGHTGBM_RECIPE)
    estimator.fit(X,y.astype(int))
    if list(estimator.classes_)!=[0,1]:
        raise ValueError("Unexpected classifier classes")
    model_text=estimator.booster_.model_to_string()
    def predict(x):
        # Use native booster to avoid feature-name warnings on ndarray input.
        p=float(estimator.booster_.predict(np.asarray([x]),num_threads=1)[0])
        if not np.isfinite(p) or not 0<=p<=1:
            raise ValueError("Invalid LightGBM probability")
        return p
    return {"version":installed,"model_text":model_text},predict
