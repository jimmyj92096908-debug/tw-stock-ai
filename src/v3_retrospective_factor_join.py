"""Join screened institutional rows to existing raw technical/SMC bridge reports.

Exact date/market/stock joins only. Retrospective source vintages are not
verified. No labels, model approval, imputation or production I/O.
"""
from collections import Counter
from datetime import date
from hashlib import sha256
import json
import math
import re
from src.raw_factor_feature_bridge import FEATURE_NAMES, VERSION

CHIP_FIELDS=("institutional_net_shares_20","institutional_turnover_shares_20",
             "institutional_imbalance_20")


def _digest(rows):
    return sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),
                             ensure_ascii=True,allow_nan=False).encode("utf-8")).hexdigest()


def _key(market,stock,day):
    if market not in ("twse","TWSE") or not isinstance(stock,str) or not re.fullmatch("[0-9]{4,6}",stock) or stock in ("1589","1808"):
        raise ValueError("Invalid or excluded TWSE key")
    if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:
        raise ValueError("Invalid signal date")
    return ("TWSE",stock,day)


def _finite(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError("Invalid finite feature")
    return value


def join_reconstructed_factors(*, screened, raw_reports):
    m=screened["summary"]
    factors=screened["retrospective_research_factors"]
    if (m["scope"]!="V3_TWSE_RETROSPECTIVE_SCREENED_RESEARCH_ONLY" or
            m["model_release"]!="BLOCKED" or m["approved_training_feature_rows"]!=0 or
            m["source_expansion_complete"] is not True or
            not isinstance(factors,list) or not 1<=len(factors)<=200000 or
            len(factors)!=m["screened_factor_rows"] or _digest(factors)!=m["screened_factor_sha256"]):
        raise ValueError("Invalid screened source manifest")
    chip={}
    for r in factors:
        key=_key(r["market"],r["stock_id"],r["signal_date"])
        if key in chip or r["historical_reconstruction_only"] is not True or r["strict_point_in_time_verified"] is not False or r["approved_training_feature"] is not False:
            raise ValueError("Duplicate or unexpected approval flag")
        net,turnover,ratio=(_finite(r[f]) for f in CHIP_FIELDS)
        if turnover<=0 or not math.isclose(net/turnover,ratio,rel_tol=1e-8,abs_tol=1e-10):
            raise ValueError("Invalid institutional factor arithmetic")
        chip[key]=r
    if not isinstance(raw_reports,list) or len(raw_reports)>10000:
        raise ValueError("Expected bounded list of raw bridge reports")
    tech={}
    for report in raw_reports:
        if (report["feature_version"]!=VERSION or report["feature_names"]!=list(FEATURE_NAMES) or
                report["research_use_only"] is not True or report["live_trading_approved"] is not False or
                report["source_capture_vintage_at_old_signals_independently_proven"] is not False or
                report["corporate_actions_not_applied_to_features"] is not True or
                report["included_signals"]!=len(report["signals"])):
            raise ValueError("Unexpected raw bridge report")
        for r in report["signals"]:
            key=_key(r["market"],r["stock_id"],r["as_of_date"])
            if (key[:2]!=_key(report["market"],report["stock_id"],r["as_of_date"])[:2] or
                    key[2]>report["requested_cutoff"] or key in tech or
                    r["label_or_forward_price_observed"] is not False or
                    len(r["feature_vector"])!=len(FEATURE_NAMES)):
                raise ValueError("Invalid or duplicate technical key")
            tech[key]=[_finite(v) for v in r["feature_vector"]]
            if len(tech)>200000:
                raise ValueError("Raw feature cap exceeded")
    matched=[]
    by_day=Counter()
    for key in sorted(chip):
        if key not in tech:
            continue
        row=chip[key]
        matched.append(dict(market=key[0],stock_id=key[1],signal_date=key[2],
                     features=dict(zip((*FEATURE_NAMES,*CHIP_FIELDS),
                                     [*tech[key],*(row[f] for f in CHIP_FIELDS)])),
                     historical_reconstruction_only=True,strict_point_in_time_verified=False,
                     approved_training_feature=False))
        by_day[key[2]]+=1
    expected=Counter(k[2] for k in chip)
    return {"summary":dict(status="RETROSPECTIVE_JOIN_RESEARCH_ONLY",
                institutional_rows=len(chip),technical_smc_rows=len(tech),matched_rows=len(matched),
                institutional_only_rows=len(set(chip)-set(tech)),technical_only_rows=len(set(tech)-set(chip)),
                coverage_by_signal_date=[dict(signal_date=d,expected_rows=expected[d],
                     matched_rows=by_day[d]) for d in sorted(expected)],
                feature_names=list((*FEATURE_NAMES,*CHIP_FIELDS)),matched_rows_sha256=_digest(matched),
                fundamental_features_integrated=False,source_provenance_verified=False,
                historical_listing_eligibility_verified=False,selection_bias_possible=True,
                approved_training_feature_rows=0,v3_model_trained=False,model_release="BLOCKED"),
            "retrospective_joined_factors":matched}
