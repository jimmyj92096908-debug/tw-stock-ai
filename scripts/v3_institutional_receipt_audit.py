"""Offline audit of owner V3 institutional expansion receipt.

The receipt is a self-reported summary, not the underlying encrypted
source archive or a signed point-in-time record. Never promote candidates
to approved features. This tool performs no network or database access.
"""
import argparse
import json
import math
import re
from datetime import date
from pathlib import Path


def audit_receipt(receipt):
    s=receipt.get("summary",receipt)
    if s["scope"]!="OWNER_V3_TWSE_INSTITUTIONAL_HISTORY_EXPANSION":
        raise ValueError("Unexpected scope")
    def integer(row,key):
        v=row[key]
        if type(v) is not int or v<0:
            raise ValueError("Invalid count: "+key)
        return v
    verified=integer(s,"verified_source_dates")
    remaining=integer(s,"remaining_source_dates")
    windows=integer(s,"signal_windows")
    target=integer(s,"target_signal_windows")
    if (integer(s,"required_unique_source_dates")!=919 or verified+remaining!=919
            or target!=48 or windows+integer(s,"remaining_signal_windows")!=48
            or not windows<=integer(s,"calendar_ready_windows")<=48):
        raise ValueError("Source or window count mismatch")
    if any(integer(s,k)!=0 for k in ("production_neon_reads","production_neon_writes","line_messages_sent","approved_training_feature_rows")):
        raise ValueError("Unexpected production activity or approved features")
    if (s["model_release"]!="BLOCKED" or s["paid_upgrade_requested"] is not False
            or s["v3_model_trained"] is not False):
        raise ValueError("Unexpected release or payment state")
    if s["offline_replay_pass"] is not True or s["original_pilot_replay_pass"] is not True:
        raise ValueError("Replay not passed")
    complete=verified==919 and windows==48 and s["calendar_ready_windows"]==48
    if s["full_expansion_complete"] is not complete:
        raise ValueError("Completion flag mismatch")
    if not isinstance(s["factor_sha256"],str) or not re.fullmatch("[0-9a-f]{64}",s["factor_sha256"]):
        raise ValueError("Invalid declared factor digest")
    if len(s["reports"])!=windows or len(s["completed_signal_dates"])!=windows:
        raise ValueError("Report count mismatch")
    rows=[]
    for r in s["reports"]:
        d=r["signal_date"]
        if date.fromisoformat(d).isoformat()!=d:
            raise ValueError("Invalid date")
        n=integer(r,"candidate_rows")
        c=integer(r,"complete_factor_candidates")
        z=integer(r,"zero_institutional_turnover")
        pct=r["coverage_pct"]
        if not n or c>n or z>n or isinstance(pct,bool) or not isinstance(pct,(int,float)) or not math.isclose(pct,100*c/n,abs_tol=1e-7):
            raise ValueError("Invalid window coverage")
        rows.append(dict(signal_date=d,candidate_rows=n,complete_candidates=c,missing=n-c,
                         coverage_pct=100*c/n,zero_institutional_turnover=z))
    days=[r["signal_date"] for r in rows]
    if days!=s["completed_signal_dates"] or any(a>=b for a,b in zip(days,days[1:])):
        raise ValueError("Date order or identity mismatch")
    n=sum(r["candidate_rows"] for r in rows)
    c=sum(r["complete_candidates"] for r in rows)
    if c!=integer(s,"candidate_factor_rows"):
        raise ValueError("Complete factor count mismatch")
    for flag in ("historical_publication_time_verified","immutable_historical_vintage_verified"):
        if type(s[flag]) is not bool:
            raise ValueError("Invalid provenance declaration")
    return dict(status="RECEIPT_COUNTS_CONSISTENT",source_dates=verified,source_dates_remaining=remaining,
                source_expansion_complete=complete,signal_windows=windows,candidate_rows=n,
                complete_factor_candidates=c,missing_factor_candidates=n-c,
                weighted_coverage_pct=100*c/n if n else None,
                highest_missing_windows=sorted(rows,key=lambda r:(-r["missing"],r["signal_date"]))[:10],
                lowest_coverage_windows=sorted(rows,key=lambda r:(r["coverage_pct"],r["signal_date"]))[:10],
                declared_factor_sha256=s["factor_sha256"],underlying_digest_recomputed=False,
                historical_publication_time_declared=s["historical_publication_time_verified"],
                immutable_vintage_declared=s["immutable_historical_vintage_verified"],
                source_provenance_verified=False,missing_stock_identities_verified=False,
                approved_training_feature_rows=0,v3_model_trained=False,
                production_neon_reads=0,production_neon_writes=0,line_messages_sent=0,
                model_release="BLOCKED")


def audit_private_structure(receipt):
    """Return only aggregate field statistics; do not print row values or paths."""
    report=audit_receipt(receipt)
    from collections import Counter
    factors=receipt["private_candidate_factors"]
    sources=receipt["source_receipts"]
    def inspect(rows, expected):
        if not isinstance(rows,list) or len(rows)!=expected:
            raise ValueError("Private row count mismatch")
        fields=Counter()
        nulls=Counter()
        types={}
        for row in rows:
            if not isinstance(row,dict):
                raise ValueError("Invalid private row")
            for k,v in row.items():
                fields[k]+=1
                if v is None:
                    nulls[k]+=1
                types.setdefault(k,set()).add(type(v).__name__)
        return {"row_count":len(rows),"fields":[
            {"name":k,"present":fields[k],"null":nulls[k],
             "types":sorted(types[k])} for k in sorted(fields)]}
    report["private_candidate_structure"]=inspect(factors,report["complete_factor_candidates"])
    report["source_receipt_structure"]=inspect(sources,report["source_dates"])
    report["private_payload_counts_consistent"]=True
    report["stock_date_keys_verified"]=False
    return report


def audit_factor_integrity(receipt):
    """Audit actual private rows without exposing values, IDs or source URLs.

    Source receipts are retrospective captures, not verified original releases.
    The ratio check is a diagnostic hypothesis until the producer recipe is
    independently reproduced. All anomalies remain visible in aggregate.
    """
    from collections import Counter
    from datetime import datetime, timezone, timedelta
    from hashlib import sha256
    from bisect import bisect_left
    report=audit_private_structure(receipt)
    factors=receipt["private_candidate_factors"]
    sources=receipt["source_receipts"]
    summary=receipt["summary"]
    problems=Counter()
    dates=set()
    capture_days={}
    def day(value):
        if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:
            raise ValueError("Invalid canonical date")
        return date.fromisoformat(value)
    for source in sources:
        d=day(source["date"])
        if d in dates:
            problems["duplicate_source_date"]+=1
        dates.add(d)
        if not isinstance(source["response_sha256"],str) or not re.fullmatch("[0-9a-fA-F]{64}",source["response_sha256"]):
            problems["invalid_response_digest"]+=1
        if not isinstance(source["source"],str) or not source["source"] or not isinstance(source["params"],dict):
            problems["invalid_source_metadata"]+=1
        try:
            timestamp=datetime.fromisoformat(source["captured_at_utc"].replace("Z","+00:00"))
            if timestamp.utcoffset()!=timedelta(0):
                raise ValueError("Non-UTC timestamp")
            capture_days[d]=timestamp.astimezone(timezone.utc).date()
            if capture_days[d]<d:
                problems["capture_before_source_date"]+=1
        except (ValueError,TypeError,AttributeError):
            problems["invalid_capture_timestamp"]+=1
    ordered=sorted(dates)
    keys=set()
    per_date=Counter()
    markets=Counter()
    retrospective=0
    ratio_mismatch=0
    late_capture_rows=0
    unexpected_windows=0
    for row in factors:
        d=day(row["signal_date"])
        stock=row["stock_id"]
        market=row["market"]
        if not isinstance(market,str) or market.upper()!="TWSE":
            problems["unexpected_market"]+=1
        else:
            markets[market.upper()]+=1
        if (not isinstance(stock,str) or not re.fullmatch("[0-9]{4,6}",stock)
                or stock in ("1589","1808")):
            problems["invalid_or_excluded_stock"]+=1
        key=(d,market.upper() if isinstance(market,str) else str(market),str(stock))
        if key in keys:
            problems["duplicate_stock_signal_key"]+=1
        keys.add(key)
        per_date[d.isoformat()]+=1
        if (row["historical_reconstruction_only"] is not True or
            row["strict_point_in_time_verified"] is not False or
            row["approved_training_feature"] is not False):
            problems["unexpected_training_flag"]+=1
        else:
            retrospective+=1
        if not isinstance(row["source_dates"],list):
            problems["invalid_source_window"]+=1
            continue
        window=[day(x) for x in row["source_dates"]]
        if len(window)!=20 or len(set(window))!=20 or window!=sorted(window):
            problems["invalid_source_window"]+=1
        if any(x>=d for x in window):
            problems["source_not_strictly_before_signal"]+=1
        if any(x not in dates for x in window):
            problems["missing_source_receipt"]+=1
        idx=bisect_left(ordered,d)
        if window!=ordered[max(0,idx-20):idx]:
            unexpected_windows+=1
        if any(capture_days.get(x,date.min)>d for x in window):
            late_capture_rows+=1
        net=row["institutional_net_shares_20"]
        turnover=row["institutional_turnover_shares_20"]
        ratio=row["institutional_imbalance_20"]
        if (type(net) is not int or type(turnover) is not int or turnover<=0
                or isinstance(ratio,bool) or not isinstance(ratio,(int,float)) or not math.isfinite(ratio)):
            problems["invalid_factor_numbers"]+=1
        elif not math.isclose(ratio,net/turnover,rel_tol=1e-8,abs_tol=1e-10):
            ratio_mismatch+=1
    expected={r["signal_date"]:r["complete_factor_candidates"] for r in summary["reports"]}
    if dict(per_date)!=expected:
        problems["per_signal_count_mismatch"]+=1
    canonical=json.dumps(factors,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)
    report.update(private_integrity_status="STRUCTURE_CHECKS_PASS" if not problems else "INTEGRITY_REVIEW_REQUIRED",
                  anomaly_counts=dict(sorted(problems.items())),unique_stock_signal_keys=len(keys),
                  unique_source_dates=len(dates),per_signal_counts_match=dict(per_date)==expected,
                  market_counts=dict(markets),retrospective_flag_rows=retrospective,
                  post_signal_capture_date_rows=late_capture_rows,
                  trailing_20_receipt_window_mismatch_rows=unexpected_windows,
                  net_over_turnover_hypothesis_mismatch_rows=ratio_mismatch,
                  canonical_factor_array_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
                  original_producer_digest_recipe_verified=False,
                  stock_date_keys_verified=not any(problems[k] for k in
                      ("duplicate_stock_signal_key","invalid_or_excluded_stock","unexpected_market")),
                  approved_training_feature_rows=0)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("receipt",type=Path)
    p.add_argument("--structure",action="store_true",help="Audit only aggregate private row structure")
    p.add_argument("--integrity",action="store_true",help="Audit private stock/date keys and source windows offline")
    a=p.parse_args()
    if a.receipt.stat().st_size>64*1024*1024:
        raise ValueError("Receipt too large")
    receipt=json.loads(a.receipt.read_text(encoding="utf-8-sig"))
    report=audit_factor_integrity(receipt) if a.integrity else (audit_private_structure(receipt) if a.structure else audit_receipt(receipt))
    print(json.dumps(report,
                     ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
