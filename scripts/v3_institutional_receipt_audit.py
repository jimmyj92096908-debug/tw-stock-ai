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


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("receipt",type=Path)
    p.add_argument("--structure",action="store_true",help="Audit only aggregate private row structure")
    a=p.parse_args()
    if a.receipt.stat().st_size>64*1024*1024:
        raise ValueError("Receipt too large")
    receipt=json.loads(a.receipt.read_text(encoding="utf-8-sig"))
    report=audit_private_structure(receipt) if a.structure else audit_receipt(receipt)
    print(json.dumps(report,
                     ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
