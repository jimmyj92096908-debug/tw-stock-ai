"""Independent offline release blocker check for raw-price AI research prototype.

A raw-price retrospective model cannot inherit release approval from the
existing score-based Ridge, even if an exploratory window returns positive.
This gate compares ACTUAL experimental evidence against saved model-release
blockers without granting trading or LINE permissions.
"""
from __future__ import annotations

from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path

from src.model_release_acceptance import evaluate_release
from src.raw_factor_feature_bridge import VERSION as RAW_VERSION

REQUIRED_NONOVERLAP=10
SCOPE="TPEX_RAW_AI_PROTOTYPE_AND_EXISTING_RIDGE_RESEARCH_ACCEPTANCE"

def _hash(x):
    return sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,
                   separators=(",",":"),allow_nan=False).encode()).hexdigest()

def review(raw_probe,prototype,saved_model):
    if not all(isinstance(obj,dict) for obj in (raw_probe,prototype,saved_model)):
        raise ValueError("Complete actual raw/prototype/persisted model evidence required")
    if (raw_probe.get("scope")!="TPEX_RAW_ONLY_IN_MEMORY_MODEL_INPUT_AND_UNADJUSTED_PROTOTYPE"
        or raw_probe.get("feature_version")!=RAW_VERSION):
        raise ValueError("Missing approved experimental raw source feature schema")
    if (raw_probe.get("prototype_status")!=prototype.get("status") or
        raw_probe.get("holdout_independent_windows")!=len(
            prototype.get("nonoverlap_test_windows",[])) or
        raw_probe.get("purged_exploratory_development_dates")!=prototype.get(
            "development_dates")):
        raise ValueError("Inconsistent actual prototype fold counts")
    if (type(raw_probe.get("included_stocks")) is not int or
        raw_probe["included_stocks"]<5 or
        type(raw_probe.get("accepted_full_cohort_dates")) is not int or
        raw_probe["accepted_full_cohort_dates"]<1):
        raise ValueError("No fully preserved study cohorts")
    forbidden={
        "model_release_approved":raw_probe.get("model_release_approved"),
        "live_trading_approved":raw_probe.get("live_trading_approved"),
        "line_trade_signals_approved":raw_probe.get("line_trade_signals_approved"),
        "prototype_may_update_production_weights":prototype.get(
            "may_update_production_model_weights"),
        "prototype_may_release_alpha":prototype.get(
            "may_release_positive_alpha_or_trade_signals")
    }
    if any(value is not False for value in forbidden.values()):
        raise ValueError("Experimental model must remain blocked; unsafe claim")
    if (raw_probe.get("database_read_only") is not True or
        raw_probe.get("no_new_persistent_factor_rows") is not True or
        raw_probe.get("raw_return_labels_adjusted_for_dividends") is not False or
        raw_probe.get("future_source_capture_vintage_independently_audited") is not False or
        raw_probe.get("historical_issuer_listing_universe_audited") is not False):
        raise ValueError("Unverified raw data cannot be promoted")
    if (prototype.get("true_pristine_future_holdout") is not False or
        prototype.get("label_adjustment_vintage_proven") is not False or
        prototype.get("source_capture_vintage_proven") is not False or
        prototype.get("survivorship_population_verified") is not False):
        raise ValueError("Retroactive cohort cannot claim prospective proof")
    windows=prototype["nonoverlap_test_windows"]
    last_exit=None
    for x in windows:
        if (not isinstance(x,dict) or not
            isinstance(x.get("signal_date"),str) or not
            isinstance(x.get("entry_date"),str) or not
            isinstance(x.get("exit_date"),str) or
            x["signal_date"]>=x["entry_date"] or x["entry_date"]>=x["exit_date"] or
            (last_exit is not None and x["signal_date"]<=last_exit)):
            raise ValueError("Unverified overlapping prototype source holding periods")
        last_exit=x["exit_date"]
    old=evaluate_release(saved_model)
    if old.get("live_trading_approved") is not False or old.get(
        "line_signal_delivery_approved") is not False:
        raise RuntimeError("Unexpected existing Ridge model release result")
    blockers=[
        "RAW_PRICE_LABELS_NOT_VERIFIED_DIVIDEND_ADJUSTED_TOTAL_RETURNS",
        "NO_HISTORICAL_SOURCE_CAPTURE_VINTAGE_CERTIFICATION",
        "NO_POINT_IN_TIME_CORPORATE_ACTION_DISCLOSURE_PROOF",
        "NO_HISTORICALLY_COMPLETE_LISTED_AND_DELISTED_UNIVERSE",
        "NO_PRISTINE_INDEPENDENT_PROSPECTIVE_HOLDOUT",
    ]
    if len(windows)<REQUIRED_NONOVERLAP:
        blockers.append("FEWER_THAN_TEN_UNSEEN_NONOVERLAPPING_TEST_WINDOWS")
    if prototype.get("status")!="RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY":
        blockers.append("NO_MATURE_DEVELOPMENT_TRAINING_SAMPLE")
    if old["decision"]!="BLOCKED":
        blockers.append("OLD_COMPOSITE_RIDGE_RELEASE_REQUIRES_SEPARATE_REVIEW")
    return {
        "schema_version":1,"scope":SCOPE,
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "saved_model_version":old["model_version"],
        "saved_model_holdout_mean_net_excess":old["saved_holdout_mean_net_excess"],
        "saved_model_release_decision":old["decision"],
        "saved_model_blocking_reasons":old["blocking_reasons"],
        "new_raw_feature_version":RAW_VERSION,
        "new_raw_research_source_sha256":_hash(raw_probe),
        "new_raw_research_prototype_sha256":_hash(prototype),
        "new_raw_complete_cohort_dates":raw_probe["accepted_full_cohort_dates"],
        "new_raw_nonoverlap_windows":len(windows),
        "new_raw_prototype_status":prototype["status"],
        "blocking_reasons":sorted(set(blockers)),
        "recommendation":"RESEARCH_CONTINUE_NO_MODEL_DEPLOYMENT",
        "new_prototype_release_decision":"BLOCKED",
        "existing_frozen_ridge_weights_modified":False,
        "may_claim_positive_alpha":False,
        "live_trading_approved":False,
        "line_signals_approved":False,
        "database_writes":0,
        "no_extra_paid_services":True
    }

def markdown(result):
    return "\n".join([
        "# 台股 AI 研究版放行關卡（不准實盤）","",
        "## 已儲存的正式 Ridge 模型",
        "- 評估狀態："+result["saved_model_release_decision"],
        "- 淨超額報酬："+format(result["saved_model_holdout_mean_net_excess"]*100,"+.3f")+"%",
        "- 舊模型阻擋條件："+", ".join(result["saved_model_blocking_reasons"]),
        "",
        "## 原始行情按需計算實驗",
        "- 不重疊測試窗："+str(result["new_raw_nonoverlap_windows"]),
        "- 完整研究群組日："+str(result["new_raw_complete_cohort_dates"]),
        "- 評估狀態："+result["new_prototype_release_decision"],
        "- 必須補齊："+", ".join(result["blocking_reasons"]),
        "",
        "沒有證明可預測投資報酬。未修改正式權重、資料庫、LINE或下單功能。",""
    ])

def main():
    import argparse
    p=argparse.ArgumentParser(description="Offline raw experimental alpha blockade audit")
    p.add_argument("--raw-report",type=Path,required=True)
    p.add_argument("--prototype",type=Path,required=True)
    p.add_argument("--saved-model",type=Path,default=Path("models/tw-factor-ridge-1-evaluation.json"))
    p.add_argument("--json-out",type=Path,required=True)
    p.add_argument("--md-out",type=Path,required=True)
    a=p.parse_args()
    report=review(
        json.loads(a.raw_report.read_text(encoding="utf-8")),
        json.loads(a.prototype.read_text(encoding="utf-8")),
        json.loads(a.saved_model.read_text(encoding="utf-8")))
    a.json_out.parent.mkdir(parents=True,exist_ok=True)
    a.md_out.parent.mkdir(parents=True,exist_ok=True)
    a.json_out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    a.md_out.write_text(markdown(report),encoding="utf-8")
    print(json.dumps({"existing_ridge_model":report["saved_model_release_decision"],
       "raw_prototype":report["new_prototype_release_decision"],
       "raw_nonoverlap_windows":report["new_raw_nonoverlap_windows"],
       "remaining_independent_blockers":len(report["blocking_reasons"]),
       "live_trading_approved":False},ensure_ascii=False))

if __name__=="__main__":
    main()
