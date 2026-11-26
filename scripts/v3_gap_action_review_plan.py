"""Offline gap and corporate-action queue from reconciled raw paths."""
import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
from scripts.v3_raw_path_overlap_audit import digest,key,positive_close
from scripts.v3_raw_path_recovery import day

def build_review(audit):
    m=audit["summary"]
    paths=audit["private_raw_paths"]
    gaps=audit["private_remaining_keys"]
    if (m["scope"]!="V3_FINAL_RAW_PATH_RESEARCH_ONLY" or
        m["offline_replay_verified"] is not True or m["model_release"]!="BLOCKED" or
        any(m[n]!=0 for n in ("approved_total_return_labels","execution_labels_approved","approved_training_feature_rows")) or
        len(paths)!=m["available_path_rows"] or len(gaps)!=m["remaining_rows"] or
        len(paths)+len(gaps)!=m["joined_rows"] or
        not 1<=len(paths)<=200000 or len(gaps)>10000 or
        digest(paths)!=m["raw_paths_sha256"] or digest(gaps)!=m["remaining_keys_sha256"]):
        raise ValueError("Final audit manifest mismatch")
    cutoff=day(m["cutoff"])
    windows={}
    seen=set()
    counts=Counter()
    for r in paths:
        k=key(r); s=r["sessions"]
        if (k in seen or k[0]!="twse" or k[1] in ("1589","1808") or
            len(s)!=6 or len(r["raw_closes"])!=6 or not all(positive_close(v) for v in r["raw_closes"]) or
            not day(k[2])<day(s[0]) or day(s[-1])>cutoff or
            any(day(a)>=day(b) for a,b in zip(s,s[1:])) or
            r["approved_total_return"] is not False or r["execution_label_approved"] is not False or
            r["corporate_action_coverage_verified"] is not False):
            raise ValueError("Invalid raw path")
        if k[2] in windows and windows[k[2]]!=s:
            raise ValueError("Conflicting calendar")
        windows[k[2]]=s
        seen.add(k); counts[k[2]]+=1
    if len(windows)!=m["available_signal_dates"]:
        raise ValueError("Window count mismatch")
    query=defaultdict(set)
    reasons=Counter()
    for r in gaps:
        k=key(r); missing=r["missing_sessions"]; reason=r["reason"]
        if k in seen or k[0]!="twse" or k[1] in ("1589","1808"):
            raise ValueError("Invalid unresolved key")
        seen.add(k); reasons[reason]+=1
        if reason=="NOT_YET_MATURE":
            if missing or k[2] in windows:
                raise ValueError("Unexpected immature window")
            continue
        if (reason!="MISSING_STOCK_CLOSE" or k[2] not in windows or
            not isinstance(missing,list) or not missing or len(set(missing))!=len(missing) or
            not set(missing)<=set(windows[k[2]])):
            raise ValueError("Invalid missing session")
        for d in missing:
            query[(k[1],d[:7])].add(d)
    if (reasons["MISSING_STOCK_CLOSE"]!=m["missing_stock_close_rows"] or
        reasons["NOT_YET_MATURE"]!=m["not_yet_mature_rows"]):
        raise ValueError("Gap counts mismatch")
    requests=[dict(stock_id=s,month=month,missing_sessions=sorted(ds)) for (s,month),ds in sorted(query.items())]
    action_windows=[dict(signal_date=d,entry_date=s[0],exit_date=s[-1],sessions=s,
                         available_rows=counts[d],entry_close_entitlement_excluded=True)
                    for d,s in sorted(windows.items())]
    return dict(summary=dict(scope="V3_GAP_AND_ACTION_REVIEW_PLAN_ONLY",
        raw_paths_sha256=m["raw_paths_sha256"],remaining_keys_sha256=m["remaining_keys_sha256"],
        missing_stock_paths=reasons["MISSING_STOCK_CLOSE"],immature_paths=reasons["NOT_YET_MATURE"],
        unique_stock_month_requests=len(requests),unique_missing_stock_dates=sum(len(r["missing_sessions"]) for r in requests),
        action_windows=len(action_windows),first_action_window=action_windows[0]["entry_date"],
        last_action_window=action_windows[-1]["exit_date"],stock_month_queue_sha256=digest(requests),
        action_windows_sha256=digest(action_windows),official_calendar_independently_verified=False,
        corporate_action_coverage_verified=False,approved_total_return_labels=0,execution_labels_approved=0,
        approved_training_feature_rows=0,model_release="BLOCKED",network_requests=0,
        production_neon_reads=0,production_neon_writes=0,line_messages_sent=0),
        private_stock_month_queue=requests,private_action_windows=action_windows)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.audit.stat().st_size>128*1024*1024:
        raise ValueError("Oversized input")
    dest=a.output.resolve()
    if any((x/".git").exists() for x in (dest,*dest.parents)):
        p.error("Private output must be outside Git")
    r=build_review(json.loads(a.audit.read_text(encoding="utf-8-sig")))
    with dest.open("x",encoding="utf-8") as f:
        json.dump(r,f,separators=(",",":"),allow_nan=False)
    print(json.dumps(r["summary"],indent=2))

if __name__=="__main__":
    main()
