"""Five tuned component models with a past-only adaptive ensemble.

Offline retrospective research only. Each model selects one predeclared
hyperparameter on the same separated development window. The resulting
component recipes are frozen before the first holdout signal. Adaptive
weights start uniformly and use only previously matured holdout forecasts.
"""
from __future__ import annotations

from src.v3_frozen_logistic_tuning import frozen_logistic_tuning
from src.v3_frozen_forest_tuning import frozen_forest_tuning
from src.v3_frozen_booster_tuning import frozen_booster_tuning
from src.v3_five_model_ensemble import MODELS, adaptive_five_blend
from src.v3_purged_logistic_baseline import _hash
from src.v3_market_regime_archive import market_regime_archive


def walkforward_tuned_five_ensemble(*, rows, feature_names, label_protocol_sha256,
                                    development_dates, holdout_dates,
                                    selection_cutoff, archive_cutoff, index_rows=None):
    args=dict(rows=rows,feature_names=feature_names,label_protocol_sha256=label_protocol_sha256,
              development_dates=development_dates,holdout_dates=holdout_dates,
              selection_cutoff=selection_cutoff,archive_cutoff=archive_cutoff)
    reports={}
    archives={}
    for kind in MODELS:
        if kind=="logistic":
            report=frozen_logistic_tuning(**args)
            parameter="selected_l2"
        elif kind=="forest":
            report=frozen_forest_tuning(**args)
            parameter="selected_depth"
        else:
            report=frozen_booster_tuning(model_kind=kind,**args)
            parameter="selected_depth"
        reports[kind]={k:v for k,v in report.items() if k!="holdout_archive"}
        if report["status"]=="INSUFFICIENT_DEVELOPMENT_EVIDENCE":
            return {"status":"INSUFFICIENT_COMPONENT_EVIDENCE","blocked_component":kind,
                    "component_reports":reports,"ensemble":None,"selection_sha256":None,
                    "model_release":"BLOCKED","trading_approved":False,
                    "pristine_holdout_verified":False,"source_provenance_verified":False}
        if (report["status"]!="FROZEN_DEVELOPMENT_SELECTION" or report[parameter] is None
                or not isinstance(report["selection_sha256"],str)
                or len(report["selection_sha256"])!=64 or report["holdout_archive"] is None):
            raise ValueError("Invalid component selection")
        archives[kind]=report["holdout_archive"]
    # Candidate development archives are not reused as unbiased evidence:
    # those outcomes helped choose the hyperparameters. Only subsequent
    # matched holdout outcomes can affect later adaptive weights.
    regimes=market_regime_archive(index_rows=index_rows,decision_dates=holdout_dates) if index_rows is not None else None
    ensemble=adaptive_five_blend(archives,regimes=regimes)
    selection=_hash(dict(recipe="tuned_five_components_v1",selection_cutoff=selection_cutoff,
                         selections={k:reports[k]["selection_sha256"] for k in MODELS}))
    return {"status":"TUNED_FIVE_RETROSPECTIVE_RESEARCH",
            "component_reports":reports,"selection_sha256":selection,
            "ensemble":ensemble,"hyperparameters_frozen":True,
            "regime_conditioned":regimes is not None,"regime_archive":regimes,
            "adaptive_weights_use_prior_holdout_only":True,
            "pristine_holdout_verified":False,"source_provenance_verified":False,
            "model_release":"BLOCKED","trading_approved":False}
