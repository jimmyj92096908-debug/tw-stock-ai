"""Bounded official issuer-month gap evidence; never alter original paths."""
import argparse
from collections import Counter
from datetime import datetime,timezone
from hashlib import sha256
import base64
import json
from pathlib import Path
import re
import time
from scripts.v3_gap_action_review_plan import build_review
from scripts.v3_raw_path_overlap_audit import digest,positive_close
from scripts.v3_raw_path_recovery import day
from scripts.twse_2022_30_gap_official_stock_day_monthly_readonly import _parse_roc_date,_decimal

URL="https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
LIMIT=2*1024*1024

def parse_month(raw,stock,month):
    body=json.loads(raw)
    if not isinstance(body,dict):
        raise ValueError("Invalid official JSON")
    if body.get("stat")!="OK":
        from src.twse_dated_history import NO_DATA_MARKERS
        if any(x in str(body.get("stat") or "") for x in NO_DATA_MARKERS):
            return {}, "NO_DATA_RESPONSE_NOT_HALT_PROOF"
        raise ValueError("Unexpected source status")
    title=body.get("title","")
    fields=body.get("fields")
    rows=body.get("data")
    if (not isinstance(title,str) or not re.search(r"(?<![0-9])"+stock+r"(?![0-9])",title)
        or not isinstance(fields,list) or len(fields)<7 or fields[0]!="日期"
        or "成交股數" not in fields[1] or fields[6]!="收盤價"
        or not isinstance(rows,list) or not 1<=len(rows)<=31):
        raise ValueError("Issuer or field mismatch")
    result={}
    for row in rows:
        if not isinstance(row,list) or len(row)<7:
            raise ValueError("Malformed row")
        d=_parse_roc_date(row[0],month).isoformat()
        if d in result:
            raise ValueError("Duplicate source session")
        c=_decimal(row[6]); v=_decimal(row[1])
        result[d]=str(c) if c is not None and c>0 and v is not None and v>=0 else None
    return result,"DATED_MONTH_RESPONSE"

def audit_queue(audit,plan,lookup):
    if build_review(audit)!=plan:
        raise ValueError("Frozen review queue mismatch")
    queue=plan["private_stock_month_queue"]
    if not 1<=len(queue)<=100:
        raise ValueError("Queue exceeds bound")
    evidence=[]
    for q in queue:
        s,m=q["stock_id"],q["month"]
        got=lookup(s,m)
        for d in q["missing_sessions"]:
            if got is None:
                row=dict(status="CAPTURE_PENDING",candidate_close=None,response_sha256=None)
            else:
                prices,kind,receipt=got
                value=prices.get(d)
                if value is not None and not positive_close(value):
                    raise ValueError("Invalid candidate price")
                status=("POSITIVE_CLOSE_CANDIDATE" if value is not None else
                        "INVALID_OR_MISSING_CLOSE" if d in prices else "DATE_NOT_IN_MONTH_RESPONSE")
                row=dict(status=status,candidate_close=value,response_sha256=receipt,source_category=kind)
            evidence.append(dict(stock_id=s,trade_date=d,month=m,**row))
    counts=Counter(r["status"] for r in evidence)
    index={(r["stock_id"],r["trade_date"]):r for r in evidence}
    ready=0
    for g in audit["private_remaining_keys"]:
        if g["reason"]=="MISSING_STOCK_CLOSE" and all(index[(g["stock_id"],d)]["status"]=="POSITIVE_CLOSE_CANDIDATE" for d in g["missing_sessions"]):
            ready+=1
    return dict(summary=dict(scope="V3_STOCK_MONTH_GAP_EVIDENCE_ONLY",
        queue_sha256=plan["summary"]["stock_month_queue_sha256"],
        requested_months=len(queue),missing_stock_dates=len(evidence),counts=dict(counts),
        fully_supported_missing_date_paths=ready,confirmed_halt_rows=0,
        evidence_sha256=digest(evidence),original_paths_modified=False,
        approved_total_return_labels=0,execution_labels_approved=0,approved_training_feature_rows=0,
        model_release="BLOCKED",production_neon_reads=0,production_neon_writes=0,line_messages_sent=0),
        private_evidence=evidence)

class Capture:
    def __init__(self,root,budget):
        self.root=root; self.budget=budget; self.requests=0; self.hits=0; self.stop=None
    def __call__(self,s,m):
        path=self.root/(s+"-"+m+".json")
        if path.exists():
            if path.stat().st_size>LIMIT*2:
                raise ValueError("Oversized cache")
            receipt=json.loads(path.read_text(encoding="utf-8"))
            raw=base64.b64decode(receipt["raw_base64"],validate=True)
            if (receipt["stock_id"]!=s or receipt["month"]!=m or receipt["endpoint"]!=URL
                or len(raw)>LIMIT or sha256(raw).hexdigest()!=receipt["response_sha256"]):
                raise ValueError("Cache mismatch")
            prices,kind=parse_month(raw,s,m)
            self.hits+=1
        else:
            if self.stop or self.requests>=self.budget:
                return None
            import requests
            if self.requests:
                time.sleep(15)
            self.requests+=1
            try:
                with requests.get(URL,params={"response":"json","date":m.replace("-","")+"01","stockNo":s},
                    headers={"Accept":"application/json","User-Agent":"tw-stock-ai-owner-gap-review"},
                    timeout=(10,35),stream=True,allow_redirects=False) as resp:
                    if resp.status_code!=200:
                        raise ValueError("HTTP not 200")
                    buf=bytearray()
                    for chunk in resp.iter_content(65536):
                        buf.extend(chunk)
                        if len(buf)>LIMIT:
                            raise ValueError("Oversized response")
                raw=bytes(buf)
                prices,kind=parse_month(raw,s,m)
            except (requests.RequestException,ValueError):
                self.stop="NETWORK_OR_SOURCE_VALIDATION_PAUSED"
                return None
            receipt=dict(stock_id=s,month=m,endpoint=URL,response_sha256=sha256(raw).hexdigest(),
                         captured_at_utc=datetime.now(timezone.utc).isoformat(),
                         raw_base64=base64.b64encode(raw).decode("ascii"))
            with path.open("x",encoding="utf-8") as f:
                json.dump(receipt,f,separators=(",",":"))
        return prices,kind,receipt["response_sha256"]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("audit","plan","cache","output"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--max-new",type=int,default=10)
    a=p.parse_args()
    if not 0<=a.max_new<=10:
        p.error("Maximum 10 new requests")
    for dest in (a.cache.resolve(),a.output.resolve()):
        if any((x/".git").exists() for x in (dest,*dest.parents)):
            p.error("Private output must be outside Git")
    if a.output.exists():
        p.error("New output required")
    def load(path):
        if path.stat().st_size>128*1024*1024:
            raise ValueError("Oversized input")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    audit,plan=load(a.audit),load(a.plan)
    a.cache.mkdir(exist_ok=True)
    capture=Capture(a.cache,a.max_new)
    result=audit_queue(audit,plan,capture)
    result["summary"].update(network_requests=capture.requests,source_cache_hits=capture.hits,
        network_stop_reason=capture.stop,paid_upgrade_requested=False)
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(result,f,separators=(",",":"),allow_nan=False)
    print(json.dumps(result["summary"],indent=2))
if __name__=="__main__":
    main()
