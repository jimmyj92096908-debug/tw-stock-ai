"""TWSE ex-action candidate scans for frozen raw-close windows; never certify labels."""
import argparse
import base64
from collections import Counter,defaultdict
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time

from scripts.v3_gap_action_review_plan import build_review
from scripts.v3_raw_path_overlap_audit import digest,key
from scripts.official_dividend_monthly_preview import _parse_official_event_date

URLS={"ex":"https://www.twse.com.tw/rwd/zh/exRight/TWT49U",
      "reduction":"https://www.twse.com.tw/exchangeReport/TWTAUU"}
LIMIT=4*1024*1024

def parse(raw,kind):
    body=json.loads(raw)
    if not isinstance(body,dict) or body.get("stat")!="OK":
        # An empty/error status cannot prove a complete event-free interval.
        raise ValueError("Unrecognized or non-OK action response")
    fields=body.get("fields")
    rows=body.get("data")
    if (not isinstance(fields,list) or not fields or
        any(not isinstance(x,str) for x in fields) or len(set(fields))!=len(fields) or
        not isinstance(rows,list) or len(rows)>8000):
        raise ValueError("Unexpected action table")
    symbols=("股票代號","證券代號","代號")
    dates=("除權息日期","除權日期","資料日期","日期") if kind=="ex" else ("恢復買賣日期","恢復交易日期","日期")
    s=next((x for x in symbols if x in fields),None)
    d=next((x for x in dates if x in fields),None)
    if s is None or d is None:
        raise ValueError("Missing action identity fields")
    result=[]
    for row in rows:
        if not isinstance(row,list) or len(row)!=len(fields):
            raise ValueError("Malformed action record")
        rec=dict(zip(fields,row))
        sid=str(rec[s]).strip()
        if not re.fullmatch("[0-9]{4,6}",sid):
            # Do not infer identity for securities with other codes.
            continue
        day=_parse_official_event_date(rec[d],market="twse",kind=kind,symbol=sid).isoformat()
        result.append(dict(stock_id=sid,event_date=day,kind=kind,raw_record=rec,
                           source_row_sha256=digest(rec)))
    return result

def parse_response(raw,kind):
    """Recognize explicit no-match for either official endpoint; never certify zero events."""
    body=json.loads(raw)
    if kind not in URLS:
        raise ValueError("Unknown action source")
    if isinstance(body,dict):
        stat=body.get("stat")
        if isinstance(stat,str):
            normalized=re.sub(r"[\s，。！!,.]", "",stat)
            if normalized in ("很抱歉沒有符合條件的資料","沒有符合條件的資料",
                              "查無資料","沒有資料","無符合條件的資料",
                              "NODATA","NoData","nodata"):
                if any(k in body and body[k] != [] for k in ("data","aaData","records","tables")):
                    raise ValueError("No-match response contains unexpected rows")
                return [],("OFFICIAL_REDUCTION_NO_MATCH_ONLY" if kind=="reduction" else "OFFICIAL_EX_NO_MATCH_ONLY")
    return parse(raw,kind),"CANDIDATE_SCAN_ONLY"

def scan(audit,plan,lookup):
    if build_review(audit)!=plan:
        raise ValueError("Frozen action window mismatch")
    paths={key(r):r for r in audit["private_raw_paths"]}
    windows=plan["private_action_windows"]
    if not 1<=len(windows)<=60:
        raise ValueError("Window bound exceeded")
    reports=[]; events=[]; affected=set(); entry=set(); outside=set()
    by_day=defaultdict(set)
    for _,s,d in paths:
        by_day[d].add(s)
    for w in windows:
        d=w["signal_date"]; start=w["entry_date"]; end=w["exit_date"]
        sources=[]
        for kind in URLS:
            result=lookup(kind,start,end)
            if result is None:
                sources.append(dict(kind=kind,status="CAPTURE_PENDING"))
                continue
            rows,receipt,status=result
            expected_empty="OFFICIAL_REDUCTION_NO_MATCH_ONLY" if kind=="reduction" else "OFFICIAL_EX_NO_MATCH_ONLY"
            if status not in ("CANDIDATE_SCAN_ONLY",expected_empty) or (status==expected_empty and rows):
                raise ValueError("Unexpected source classification")
            selected=[r for r in rows if start<=r["event_date"]<=end]
            sources.append(dict(kind=kind,status=status,response_sha256=receipt,
                                parsed_rows=len(rows),in_range_rows=len(selected),
                                outside_range_rows=len(rows)-len(selected)))
            for r in selected:
                sid=r["stock_id"]; event=r["event_date"]
                if sid not in by_day[d]:
                    continue
                k=("twse",sid,d)
                if event not in w["sessions"]:
                    outside.add(k)
                elif event==start:
                    entry.add(k)
                else:
                    affected.add(k)
                events.append(dict(r,market="twse",signal_date=d,entry_date=start,exit_date=end,
                                   event_on_saved_session=event in w["sessions"],
                                   entry_close_no_entitlement_candidate=event==start,
                                   response_sha256=receipt))
        reports.append(dict(signal_date=d,sources=sources,
                            both_candidate_scans_present=all(s["status"] in ("CANDIDATE_SCAN_ONLY","OFFICIAL_REDUCTION_NO_MATCH_ONLY","OFFICIAL_EX_NO_MATCH_ONLY") for s in sources)))
    counts=Counter(s["status"] for r in reports for s in r["sources"])
    return dict(summary=dict(scope="V3_TWSE_ACTION_CANDIDATE_SCAN_ONLY",
        action_windows_sha256=plan["summary"]["action_windows_sha256"],
        raw_paths_sha256=audit["summary"]["raw_paths_sha256"],requested_windows=len(windows),
        windows_with_both_candidate_scans=sum(r["both_candidate_scans_present"] for r in reports),
        source_status_counts=dict(counts),candidate_event_rows=len(events),
        reduction_no_match_is_not_zero_action_proof=True,
        ex_no_match_is_not_zero_action_proof=True,
        windows_with_both_non_no_match_scans=sum(all(s["status"]=="CANDIDATE_SCAN_ONLY" for s in r["sources"]) for r in reports),
        candidate_kind_counts=dict(Counter(r["kind"] for r in events)),
        in_holding_affected_paths=len(affected),entry_day_candidate_paths=len(entry),
        outside_saved_session_candidate_paths=len(outside),
        event_array_sha256=digest(events),source_reports_sha256=digest(reports),
        no_candidate_does_not_prove_no_action=True,corporate_action_coverage_verified=False,
        historical_issuer_announcement_vintage_verified=False,approved_total_return_labels=0,
        execution_labels_approved=0,approved_training_feature_rows=0,model_release="BLOCKED",
        production_neon_reads=0,production_neon_writes=0,line_messages_sent=0),
        private_candidate_events=events,private_window_reports=reports)

class Capture:
    def __init__(self,root,budget):
        self.root=root; self.budget=budget; self.requests=0; self.hits=0; self.stop=None; self.diagnostic=None
    def __call__(self,kind,start,end):
        path=self.root/(kind+"-"+start+"-"+end+".json")
        params={"startDate":start.replace("-",""),"endDate":end.replace("-",""),"response":"json"}
        if path.exists():
            if path.stat().st_size>LIMIT*2:
                raise ValueError("Oversized cache")
            receipt=json.loads(path.read_text(encoding="utf-8"))
            raw=base64.b64decode(receipt["raw_base64"],validate=True)
            if (receipt["endpoint"]!=URLS[kind] or receipt["params"]!=params or
                len(raw)>LIMIT or sha256(raw).hexdigest()!=receipt["response_sha256"]):
                raise ValueError("Action source cache mismatch")
            rows,status=parse_response(raw,kind)
            self.hits+=1
        else:
            if self.stop or self.requests>=self.budget:
                return None
            import requests
            if self.requests:
                time.sleep(15)
            self.requests+=1
            try:
                with requests.get(URLS[kind],params=params,headers={
                    "User-Agent":"tw-stock-ai-owner-action-review","Accept":"application/json"},
                    timeout=(10,35),stream=True,allow_redirects=False) as resp:
                    if resp.status_code!=200:
                        self.diagnostic=dict(kind=kind,start=start,end=end,category="HTTP_STATUS",http_status=resp.status_code)
                        raise ValueError("HTTP not 200")
                    buf=bytearray()
                    for chunk in resp.iter_content(65536):
                        buf.extend(chunk)
                        if len(buf)>LIMIT:
                            raise ValueError("Oversized response")
                raw=bytes(buf)
                rows,status=parse_response(raw,kind)
            except (requests.RequestException,ValueError) as exc:
                self.stop="NETWORK_OR_ACTION_SCHEMA_PAUSED"
                if self.diagnostic is None:
                    self.diagnostic=dict(kind=kind,start=start,end=end,
                        category="NETWORK_EXCEPTION" if isinstance(exc,requests.RequestException) else "RESPONSE_SCHEMA_REJECTED",
                        exception_type=type(exc).__name__)
                    if "raw" in locals():
                        self.diagnostic["response_sha256"]=sha256(raw).hexdigest()
                        try:
                            obj=json.loads(raw)
                            if isinstance(obj,dict):
                                self.diagnostic["response_keys"]=sorted(str(k)[:80] for k in obj)[:25]
                                stat=obj.get("stat")
                                if isinstance(stat,str):
                                    self.diagnostic["official_status"]=stat[:150]
                        except ValueError:
                            pass
                return None
            receipt=dict(endpoint=URLS[kind],params=params,response_sha256=sha256(raw).hexdigest(),
                         captured_at_utc=datetime.now(timezone.utc).isoformat(),
                         raw_base64=base64.b64encode(raw).decode("ascii"))
            with path.open("x",encoding="utf-8") as f:
                json.dump(receipt,f,separators=(",",":"))
        return rows,receipt["response_sha256"],status

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("audit","plan","cache","output"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--max-new",type=int,default=10)
    a=p.parse_args()
    if not 0<=a.max_new<=10:
        p.error("Maximum ten new source requests")
    for dest in (a.cache.resolve(),a.output.resolve()):
        if any((x/".git").exists() for x in (dest,*dest.parents)):
            p.error("Private output outside Git required")
    if a.output.exists():
        p.error("New output required")
    def load(path):
        if path.stat().st_size>128*1024*1024:
            raise ValueError("Oversized input")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    audit,plan=load(a.audit),load(a.plan)
    a.cache.mkdir(exist_ok=True)
    capture=Capture(a.cache,a.max_new)
    r=scan(audit,plan,capture)
    r["summary"].update(network_requests=capture.requests,source_cache_hits=capture.hits,
                        network_stop_reason=capture.stop,stop_diagnostic=capture.diagnostic,paid_upgrade_requested=False)
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(r,f,separators=(",",":"),allow_nan=False)
    print(json.dumps(r["summary"],indent=2))
if __name__=="__main__":
    main()
