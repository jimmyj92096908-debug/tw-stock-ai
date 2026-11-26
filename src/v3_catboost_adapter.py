"""Optional pinned CatBoost CPU adapter for offline V3 research."""
from __future__ import annotations

from importlib import import_module
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import numpy as np

CATBOOST_VERSION="1.2.8"
CATBOOST_RECIPE={
    "loss_function":"Logloss","iterations":64,"learning_rate":0.05,
    "depth":4,"l2_leaf_reg":3.0,"random_seed":20261126,
    "task_type":"CPU","thread_count":1,"verbose":False,
    "allow_writing_files":False,"bootstrap_type":"No",
    "random_strength":0.0,"boosting_type":"Plain",
    "nan_mode":"Forbidden",
}


def fit_catboost(X,y):
    """Fit only on arrays already validated by the chronological gate.

    This adapter currently accepts numeric features only. Model export is
    temporary; hashable predictive structure excludes volatile model_info
    metadata (e.g. training timestamps). No prediction-label eval set.
    """
    try:
        installed=version("catboost")
    except PackageNotFoundError as exc:
        raise RuntimeError("Optional CatBoost 1.2.8 is not installed") from exc
    if installed!=CATBOOST_VERSION:
        raise RuntimeError("Unexpected CatBoost version")
    lib=import_module("catboost")
    if lib.__version__!=CATBOOST_VERSION:
        raise RuntimeError("Imported CatBoost version mismatch")
    estimator=lib.CatBoostClassifier(**CATBOOST_RECIPE)
    estimator.fit(X,y.astype(int))
    if list(estimator.classes_)!=[0,1]:
        raise ValueError("Unexpected classifier classes")
    with TemporaryDirectory(prefix="v3-catboost-") as tmp:
        path=Path(tmp)/"model.json"
        estimator.save_model(str(path),format="json")
        structure=json.loads(path.read_text(encoding="utf-8"))
    if not {"features_info","oblivious_trees","scale_and_bias"}<=set(structure):
        raise ValueError("Unexpected CatBoost predictive structure")
    structure.pop("model_info",None)
    def predict(x):
        p=float(estimator.predict_proba(np.asarray([x]),thread_count=1)[0,1])
        if not np.isfinite(p) or not 0<=p<=1:
            raise ValueError("Invalid CatBoost probability")
        return p
    return {"version":installed,"predictive_structure":structure},predict
