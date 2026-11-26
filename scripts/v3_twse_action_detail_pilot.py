"""Small owner-local pilot of TWSE historical ex-right detail, not approved returns."""
import argparse
import base64
from collections import Counter
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from scripts.v3_raw_path_overlap_audit import digest,key
from scripts.v3_action_economics_candidates import cash_candidate

URL="https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail"
LIMIT=1024*1024

def queue(scan,econ):
    sm=scan["summary"]; em=econ["summary"]
    events=scan["private_candidate_events"]; terms=econ["private_unresolved_event_terms"]
    if (sm["scope"]!="V3_TWSE_ACTION_CANDIDATE_SCAN_ONLY" or
        em["scope"]!="V3_OFFLINE_ACTION_ECONOMICS_CANDIDATES_ONLY" or
        em["offline_source_replay_verified"] is not True or
        sm["windows_with_both_candidate_scans"]!=sm["requested_windows"] or
        any(m["model_release"]!="BLOCKED" or m["approved_total_return_labels"]!=0 or
            m["execution_labels_approved"]!=0 for m in (sm,em)) or
        digest(events)!=sm["event_array_sha256"] or em["event_array_sha256"]!=sm["event_array_sha256"] or
        em["raw_paths_sha256"]!=sm["raw_paths_sha256"] or
        digest(terms)!=em["event_terms_queue_sha256"] or len(terms)!=em["unresolved_event_queue_rows"]):
        raise ValueError("Frozen evidence mismatch")
    index={(key(e),e["event_date"],e["kind"],e["source_row_sha256"]):e for e in events}
    unique={}
    for t in terms:
        k=(key(t),t["event_date"],t["kind"],t["source_row_sha256"])
        e=index[k]; s=e["stock_id"]; d=e["event_date"]
        if e["kind"]!="ex" or e["event_on_saved_session"] is not True:
            continue
        if not re.fullmatch("[0-9]{4}",s) or s in ("1589","1808") or e["source_row_sha256"]!=digest(e["raw_record"]):
            raise ValueError("Invalid issuer or source row")
        category=cash_candidate(e)[0]
        q=dict(stock_id=s,event_date=d,category=category,source_row_sha256=e["source_row_sha256"])
        if (s,d) in unique and unique[(s,d)]!=q:
            raise ValueError("Conflicting event identity")
        unique[(s,d)]=q
    # Spread six pilot requests across dates and both event types.
    all_rows=sorted(unique.values(),key=lambda r:(r["event_date"],r["stock_id"]))
    groups={}
    for r in all_rows:
        groups.setdefault((r["event_date"][:4],r["category"]),[]).append(r)
    pilot=[v[0] for _,v in sorted(groups.items(),key=lambda x:(x[0][1],x[0][0]))]
    pilot=pilot[:6]
    return all_rows,pilot

def inspect(raw,stock,day):
    obj=json.loads(raw)
    if not isinstance(obj,dict):
        raise ValueError("Expected detail object")
    stat=obj.get("stat")
    if not isinstance(stat,str):
        raise ValueError("Missing detail status")
    if stat!="OK":
        normalized=re.sub(r"[\s，。！!,.]","",stat)
        if normalized in ("很抱歉沒有符合條件的資料","沒有符合條件的資料","查無資料","沒有資料") and all(obj.get(k,[])==[] for k in ("data","tables","aaData","records")):
            return dict(status="NO_MATCH_NOT_ZERO_PROOF",fields=[],rows=0,issuer_matched=False,event_date_independently_matched=False)
        raise ValueError("Unexpected detail status")
    fields=obj.get("fields"); rows=obj.get("data")
    if not isinstance(rows,list) or len(rows)>20:
        raise ValueError("Unexpected detail row count")
    if not rows:
        return dict(status="EMPTY_NOT_ZERO_PROOF",fields=[],rows=0,issuer_matched=False,event_date_independently_matched=False)
    if (not isinstance(fields,list) or len(fields)>100 or
        any(not isinstance(f,str) or len(f)>200 for f in fields) or len(set(fields))!=len(fields)):
        raise ValueError("Unexpected detail fields")
    idfield=next((f for f in ("股票代號","證券代號","代號") if f in fields),None)
    if idfield is None:
        raise ValueError("Missing explicit issuer")
    datefield=next((f for f in ("除權息日期","除權除息日期","資料日期","日期") if f in fields),None)
    from scripts.official_dividend_monthly_preview import _parse_official_event_date
    for row in rows:
        if not isinstance(row,list) or len(row)!=len(fields) or str(row[fields.index(idfield)]).strip()!=stock:
            raise ValueError("Issuer mismatch")
        if datefield and _parse_official_event_date(row[fields.index(datefield)],market="twse",kind="ex",symbol=stock).isoformat()!=day:
            raise ValueError("Detail date mismatch")
    return dict(status="DETAIL_CANDIDATE_ONLY",fields=fields,rows=len(rows),issuer_matched=True,
                event_date_independently_matched=bool(datefield))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("scan","economics","cache","output"):
        p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args()
    for dest in (a.cache.resolve(),a.output.resolve()):
        if any((x/".git").exists() for x in (dest,*dest.parents)):
            p.error("Private paths required")
    if a.output.exists():
        p.error("New output required")
    def load(path):
        if path.stat().st_size>128*1024*1024:
            raise ValueError("Oversized input")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    all_rows,pilot=queue(load(a.scan),load(a.economics))
    a.cache.mkdir(exist_ok=True)
    import requests
    evidence=[]; calls=0; hits=0; stop=None
    for q in pilot:
        s,d=q["stock_id"],q["event_date"]
        params={"STK_NO":s,"T1":d.replace("-",""),"response":"json"}
        path=a.cache/(s+"-"+d+".json")
        if path.exists():
            if path.stat().st_size>LIMIT*2:
                raise ValueError("Oversized cache")
            receipt=load(path)
            raw=base64.b64decode(receipt["raw_base64"],validate=True)
            if receipt["endpoint"]!=URL or receipt["params"]!=params or len(raw)>LIMIT or sha256(raw).hexdigest()!=receipt["response_sha256"]:
                raise ValueError("Detail cache mismatch")
            hits+=1
        else:
            if calls:
                time.sleep(15)
            calls+=1
            try:
                with requests.get(URL,params=params,headers={"Accept":"application/json","User-Agent":"tw-stock-ai-owner-detail-pilot"},
                                  stream=True,allow_redirects=False,timeout=(10,35)) as resp:
                    if resp.status_code!=200:
                        raise ValueError("HTTP status "+str(resp.status_code))
                    buf=bytearray()
                    for chunk in resp.iter_content(65536):
                        buf.extend(chunk)
                        if len(buf)>LIMIT:
                            raise ValueError("Oversized detail response")
                raw=bytes(buf)
                receipt=dict(endpoint=URL,params=params,response_sha256=sha256(raw).hexdigest(),
                    captured_at_utc=datetime.now(timezone.utc).isoformat(),raw_base64=base64.b64encode(raw).decode("ascii"))
                # Preserve actual response even if its schema is unsupported.
                with path.open("x",encoding="utf-8") as f:
                    json.dump(receipt,f,separators=(",",":"))
            except (requests.RequestException,ValueError) as exc:
                stop=dict(category="HTTP_OR_NETWORK_PAUSE",exception_type=type(exc).__name__)
                break
        try:
            result=inspect(raw,s,d)
        except ValueError as exc:
            result=dict(status="SCHEMA_REVIEW_REQUIRED",fields=[],rows=0,issuer_matched=False,event_date_independently_matched=False)
            stop=dict(category="DETAIL_SCHEMA_REVIEW_REQUIRED",reason=str(exc)[:120])
        evidence.append(dict(**q,**result,response_sha256=receipt["response_sha256"]))
        if stop:
            break
    summary=dict(scope="V3_TWSE_DETAIL_SOURCE_PILOT_ONLY",
        eligible_event_queries=len(all_rows),pilot_queries=len(pilot),reviewed_queries=len(evidence),
        status_counts=dict(Counter(r["status"] for r in evidence)),
        field_counts=dict(Counter(f for r in evidence for f in r["fields"])),
        independently_dated_rows=sum(r["event_date_independently_matched"] for r in evidence),
        query_queue_sha256=digest(all_rows),evidence_sha256=digest(evidence),network_requests=calls,
        source_cache_hits=hits,stop_diagnostic=stop,corporate_action_coverage_verified=False,
        approved_total_return_labels=0,execution_labels_approved=0,approved_training_feature_rows=0,
        production_neon_reads=0,production_neon_writes=0,line_messages_sent=0,paid_upgrade_requested=False,model_release="BLOCKED")
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(dict(summary=summary,private_queue=all_rows,private_pilot_evidence=evidence),f,separators=(",",":"),allow_nan=False)
    print(json.dumps(summary,indent=2,ensure_ascii=True))
if __name__=="__main__":
    main()
