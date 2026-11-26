"""Owner-local final raw-path reconciliation. Features and outcomes stay separate."""
import argparse
from collections import Counter
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path

from scripts.v3_raw_path_overlap_audit import expansion_plan,key,digest,positive_close,audit_overlap
from scripts.v3_raw_path_recovery import recover,LocalCapture,day

def reconcile(joined,actions,plan,saved,lookup):
    expected=expansion_plan(joined,actions)
    if expected!=plan:
        raise ValueError("Frozen plan differs from exact source join")
    sm=saved["summary"]
    cutoff=day(sm["cutoff"])
    restored=recover(plan,actions,lookup,cutoff)
    rm=restored["summary"]
    for name,value in rm.items():
        if sm.get(name)!=value:
            raise ValueError("Recovery replay mismatch: "+name)
    if restored["private_recovered_paths"]!=saved["private_recovered_paths"]:
        raise ValueError("Recovery payload differs from offline replay")
    if rm["counts"].get("capture_pending",0) or rm["counts"].get("window_unresolved",0):
        raise ValueError("Incomplete capture; resolve pending windows first")
    if hasattr(lookup,"receipts") and sm.get("source_response_digests")!=lookup.receipts:
        raise ValueError("Cached response receipt mismatch")
    index={key(r):r for r in joined["retrospective_joined_factors"]}
    original={key(r):r for r in actions["private_matched_rows"] if key(r) in index}
    added={key(r):r for r in restored["private_recovered_paths"]}
    if set(original)&set(added) or not set(added)<=set(index):
        raise ValueError("Recovery overlaps or escapes frozen keys")
    windows={}
    for k,r in list(original.items())+list(added.items()):
        sessions=r["sessions"]
        closes=r["raw_closes"]
        if (len(sessions)!=6 or len(closes)!=6 or not all(positive_close(v) for v in closes)
            or not day(k[2])<day(sessions[0]) or day(sessions[-1])>cutoff
            or any(day(a)>=day(b) for a,b in zip(sessions,sessions[1:]))):
            raise ValueError("Malformed or premature path")
        if k[2] in windows and windows[k[2]]!=sessions:
            raise ValueError("Inconsistent same-date path")
        windows[k[2]]=sessions
    names=joined["summary"]["feature_names"]
    outcomes=[]
    # Preserve provenance, never represent reconstructed rows as original vectors.
    proxy_paths=[]
    for k,r in sorted((original|added).items(),key=lambda x:(x[0][2],x[0][0],x[0][1])):
        gross=Decimal(str(r["raw_closes"][-1]))/Decimal(str(r["raw_closes"][0]))-1
        stated=Decimal(str(r["raw_gross_return"]))
        if not stated.is_finite() or abs(gross-stated)>Decimal("0.00000001"):
            raise ValueError("Raw return mismatch")
        outcome=dict(market=k[0],stock_id=k[1],signal_date=k[2],
                     sessions=r["sessions"],raw_closes=r["raw_closes"],
                     raw_gross_return=str(gross),origin="ORIGINAL_ACTION_PANEL" if k in original else "RECOVERED_OFFICIAL_CACHE",
                     approved_total_return=False,corporate_action_coverage_verified=False,
                     execution_label_approved=False)
        outcomes.append(outcome)
        proxy_paths.append(dict(outcome,feature_vector=[index[k]["features"][n] for n in names[:12]]))
    gaps=[]
    reports={r["signal_date"]:r for r in rm["per_window"]}
    for k in sorted(set(index)-set(original)-set(added),key=lambda k:(k[2],k[0],k[1])):
        report=reports[k[2]]
        if report["status"]=="NOT_YET_MATURE":
            gaps.append(dict(market=k[0],stock_id=k[1],signal_date=k[2],reason="NOT_YET_MATURE",missing_sessions=[]))
            continue
        sessions=windows.get(k[2])
        if not sessions:
            raise ValueError("No dated window available for individual gap review")
        absent=[]
        for s in sessions:
            prices=lookup(day(s))
            if prices is None:
                raise ValueError("Saved session missing")
            if k[1] not in prices:
                absent.append(s)
        if not absent:
            raise ValueError("Unexplained missing stock path")
        gaps.append(dict(market=k[0],stock_id=k[1],signal_date=k[2],reason="MISSING_STOCK_CLOSE",missing_sessions=absent))
    counts=Counter(r["reason"] for r in gaps)
    if counts["MISSING_STOCK_CLOSE"]!=rm["counts"].get("missing_stock_close",0) or counts["NOT_YET_MATURE"]!=rm["counts"].get("not_yet_mature",0):
        raise ValueError("Remaining gap count mismatch")
    # Reuse audited cost formula only. Reattached vectors are not independent parity evidence.
    proxy=dict(summary=dict(actions["summary"],matched_raw_feature_label_rows=len(proxy_paths),
                             matched_panel_sha256=digest(proxy_paths)),private_matched_rows=proxy_paths)
    stats=audit_overlap(joined,proxy)
    if stats["jointly_valid_post_signal_price_paths"]!=len(outcomes) or stats["raw_gross_return_reconciliation"].get("recomputed_match",0)!=len(outcomes):
        raise ValueError("Final outcome arithmetic mismatch")
    total=len(index)
    mature=total-counts["NOT_YET_MATURE"]
    return dict(summary=dict(scope="V3_FINAL_RAW_PATH_RESEARCH_ONLY",
        joined_rows=total,original_path_rows=len(original),recovered_path_rows=len(added),
        available_path_rows=len(outcomes),remaining_rows=len(gaps),
        missing_stock_close_rows=counts["MISSING_STOCK_CLOSE"],not_yet_mature_rows=counts["NOT_YET_MATURE"],
        total_coverage_pct=100*len(outcomes)/total,mature_coverage_pct=100*len(outcomes)/mature if mature else None,
        available_signal_dates=len(windows),feature_names=names,feature_rows_sha256=joined["summary"]["matched_rows_sha256"],
        raw_paths_sha256=digest(outcomes),remaining_keys_sha256=digest(gaps),offline_replay_verified=True,
        original_technical_vector_parity_rows=len(original),recovered_vectors_independently_verified=False,
        cutoff=cutoff.isoformat(),close_to_close_proxy_mean_gross=stats["close_to_close_proxy_mean_gross"],
        close_to_close_cost_sensitivity=stats["close_to_close_cost_sensitivity"],
        proxy_cost_assumptions=stats["proxy_cost_assumptions"],proxy_statistics_not_model_performance=True,
        coverage_by_signal_date=[{k:v for k,v in r.items() if k!="vector_parity_rows"} for r in stats["coverage_by_signal_date"]],
        official_calendar_independently_verified=False,historical_publication_vintage_verified=False,
        approved_total_return_labels=0,execution_labels_approved=0,approved_training_feature_rows=0,
        v3_model_trained=False,model_release="BLOCKED",network_requests=0,
        production_neon_reads=0,production_neon_writes=0,line_messages_sent=0),
        private_raw_paths=outcomes,private_remaining_keys=gaps)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("joined","actions","plan","recovery","cache","output"):
        p.add_argument("--"+arg,type=Path,required=True)
    a=p.parse_args()
    for path in (a.cache,a.output):
        path=path.resolve()
        if any((x/".git").exists() for x in (path,*path.parents)):
            p.error("Private files must be outside Git")
    if not a.cache.is_dir() or a.output.exists():
        p.error("Existing cache and new output required")
    def load(path):
        if path.stat().st_size>128*1024*1024:
            raise ValueError("Oversized private input")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    capture=LocalCapture(a.cache,0,0)
    result=reconcile(load(a.joined),load(a.actions),load(a.plan),load(a.recovery),capture)
    if capture.requests:
        raise ValueError("Unexpected network request")
    result["summary"]["source_cache_hits"]=capture.cache_hits
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(result,f,separators=(",",":"),allow_nan=False)
    print(json.dumps(result["summary"],indent=2,allow_nan=False))

if __name__=="__main__":
    main()
