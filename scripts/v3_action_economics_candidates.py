"""Offline cash entitlement candidate arithmetic; never certify executable labels."""
import argparse
from collections import Counter,defaultdict
from decimal import Decimal
import json
from pathlib import Path
import re
from scripts.v3_twse_action_candidate_scan import Capture,scan
from scripts.v3_raw_path_overlap_audit import digest,key

CASH_FIELDS=("現金股利","每股現金股利","每股配發現金股利")
KIND_FIELDS=("權/息","權或息","權息別","類別","權息")

def cash_candidate(event):
    row=event["raw_record"]
    if event["kind"]!="ex":
        return "REDUCTION_TERMS_REQUIRED",None
    kinds={str(row[k]).strip() for k in KIND_FIELDS if k in row}
    if kinds not in ({"息"},{"除息"},{"現金股利"}):
        return "NON_CASH_OR_UNCLASSIFIED_TERMS_REQUIRED",None
    values=[]
    for name in CASH_FIELDS:
        if name in row:
            value=str(row[name]).strip()
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",value) or len(value)>32:
                return "EXPLICIT_CASH_INVALID",None
            values.append(Decimal(value))
    if not values:
        return "EXPLICIT_CASH_NOT_AVAILABLE",None
    if len(set(values))!=1 or values[0]<=0:
        return "EXPLICIT_CASH_INVALID",None
    return "EXPLICIT_CASH_CANDIDATE",values[0]

def economics(audit,plan,saved,lookup):
    replay=scan(audit,plan,lookup)
    m=replay["summary"]
    if any(saved["summary"].get(k)!=v for k,v in m.items()) or any(
        saved[k]!=replay[k] for k in ("private_candidate_events","private_window_reports")):
        raise ValueError("Action source offline replay mismatch")
    if m["windows_with_both_candidate_scans"]!=m["requested_windows"]:
        raise ValueError("Incomplete action source capture")
    paths={key(p):p for p in audit["private_raw_paths"]}
    events=defaultdict(list)
    field_counts=Counter()
    event_counts=Counter()
    for ev in replay["private_candidate_events"]:
        k=key(ev)
        p=paths[k]
        if ev["source_row_sha256"]!=digest(ev["raw_record"]):
            raise ValueError("Action record digest mismatch")
        if ev["entry_date"]!=p["sessions"][0] or ev["exit_date"]!=p["sessions"][-1]:
            raise ValueError("Event window mismatch")
        status,amount=cash_candidate(ev)
        field_counts.update(ev["raw_record"].keys())
        event_counts[status]+=1
        events[k].append((ev,status,amount))
    result=[]; totals=Counter(); delta_sum=Decimal(0)
    term_queue=[]
    for k,items in sorted(events.items()):
        p=paths[k]; sessions=p["sessions"]
        identities=Counter((ev["event_date"],ev["kind"]) for ev,_,_ in items)
        reasons=set(); cash=Decimal(0)
        for ev,status,amount in items:
            d=ev["event_date"]
            if d not in sessions:
                reason="EVENT_OUTSIDE_SAVED_SESSIONS"
            elif identities[(d,ev["kind"])]>1:
                reason="DUPLICATE_OR_CONFLICTING_EVENT"
            elif d==sessions[0] and status in ("EXPLICIT_CASH_CANDIDATE","EXPLICIT_CASH_NOT_AVAILABLE","EXPLICIT_CASH_INVALID"):
                # An entry at the close occurs after a pure cash ex-date opening.
                reason="ENTRY_DAY_PURE_CASH_NO_ENTITLEMENT_CANDIDATE"
            elif status=="EXPLICIT_CASH_CANDIDATE":
                cash+=amount
                reason=status
            else:
                reason=status
            if reason not in ("EXPLICIT_CASH_CANDIDATE","ENTRY_DAY_PURE_CASH_NO_ENTITLEMENT_CANDIDATE"):
                reasons.add(reason)
                term_queue.append(dict(market=k[0],stock_id=k[1],signal_date=k[2],
                    event_date=d,kind=ev["kind"],reason=reason,source_row_sha256=ev["source_row_sha256"]))
        gross=Decimal(str(p["raw_closes"][-1]))/Decimal(str(p["raw_closes"][0]))-1
        adjusted=None
        if reasons:
            status="UNRESOLVED_EVENT_TERMS_OR_CALENDAR"
        elif cash>0:
            status="CASH_ENTITLEMENT_ARITHMETIC_CANDIDATE"
            adjusted=gross+cash/Decimal(str(p["raw_closes"][0]))
            delta_sum+=adjusted-gross
        else:
            status="ENTRY_DAY_ONLY_CANDIDATE"
        totals[status]+=1
        result.append(dict(market=k[0],stock_id=k[1],signal_date=k[2],status=status,
            unresolved_reasons=sorted(reasons),raw_gross_return=str(gross),
            cash_entitlement_gross_return_candidate=str(adjusted) if adjusted is not None else None,
            approved_total_return=False,execution_label_approved=False))
    n=len(paths)
    count=totals["CASH_ENTITLEMENT_ARITHMETIC_CANDIDATE"]
    return dict(summary=dict(scope="V3_OFFLINE_ACTION_ECONOMICS_CANDIDATES_ONLY",
        raw_paths_sha256=m["raw_paths_sha256"],event_array_sha256=m["event_array_sha256"],
        source_reports_sha256=m["source_reports_sha256"],offline_source_replay_verified=True,
        raw_path_rows=n,candidate_event_rows=m["candidate_event_rows"],paths_with_detected_events=len(events),
        paths_without_detected_events=n-len(events),event_term_counts=dict(event_counts),
        path_status_counts=dict(totals),raw_event_field_counts=dict(field_counts),
        unresolved_event_queue_rows=len(term_queue),event_terms_queue_sha256=digest(term_queue),
        candidate_paths_sha256=digest(result),mean_gross_cash_delta_supported_paths=float(delta_sum/count) if count else None,
        reference_price_difference_used_as_cash=False,missing_event_implies_no_action=False,
        dividends_payment_or_reinvestment_verified=False,corporate_action_coverage_verified=False,
        official_calendar_independently_verified=False,historical_publication_vintage_verified=False,
        approved_total_return_labels=0,execution_labels_approved=0,approved_training_feature_rows=0,
        v3_model_trained=False,model_release="BLOCKED",network_requests=0,
        production_neon_reads=0,production_neon_writes=0,line_messages_sent=0,paid_upgrade_requested=False),
        private_candidate_paths=result,private_unresolved_event_terms=term_queue)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("audit","plan","scan","cache","output"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    dest=a.output.resolve()
    if any((x/".git").exists() for x in (dest,*dest.parents)) or dest.exists() or not a.cache.is_dir():
        p.error("Existing private cache and new private output required")
    def load(path):
        if path.stat().st_size>128*1024*1024:
            raise ValueError("Oversized input")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    capture=Capture(a.cache,0)
    r=economics(load(a.audit),load(a.plan),load(a.scan),capture)
    if capture.requests:
        raise ValueError("Unexpected network request")
    r["summary"]["source_cache_hits"]=capture.hits
    with dest.open("x",encoding="utf-8") as f:
        json.dump(r,f,separators=(",",":"),allow_nan=False)
    print(json.dumps(r["summary"],indent=2,allow_nan=False))
if __name__=="__main__":
    main()
