"""Bounded owner-local exchange corporate-action candidate capture.
Queries only frozen mature holding windows. Empty or out-of-range feeds
never prove no corporate action. No inferred cash amounts or labels.
"""
import argparse
from collections import defaultdict,Counter
from datetime import date,datetime,timezone
from hashlib import sha256
import json
import re
import time
from urllib.parse import urlparse,parse_qs
from scripts import owner_five_stock_aes_direct_factor_research_offline as b
from src.corporate_actions_data import TWSE_EX_URL,TWSE_REDUCTION_URL

PATH_HASH="9ee66121cf7727e9b907bb3daea8b3e3c1cf00493966d796b57fdd444bb799d6"
SOURCES={"ex":TWSE_EX_URL,"reduction":TWSE_REDUCTION_URL}
LIMIT=4_000_000
DATE_FIELDS={"ex":("除權息日期","除權日期","日期","資料日期"),
             "reduction":("恢復買賣日期","恢復交易日期","減資恢復買賣日期","日期")}
ID_FIELDS=("股票代號","證券代號","代號","股票代碼")
PATH_KEYS={"market","stock_id","signal_date","sessions","raw_closes","action_coverage_status"}

def windows(paths):
    if type(paths) is not list or len(paths)!=175 or b.m.fingerprint(paths)!=PATH_HASH:
        raise ValueError("Frozen owner paths changed")
    groups=defaultdict(list)
    for p in paths:
        if set(p)!=PATH_KEYS or p["market"]!="twse" or p["action_coverage_status"]!="NOT_VERIFIED":
            raise ValueError("Unexpected raw path")
        days=[date.fromisoformat(d) for d in p["sessions"]]
        signal=date.fromisoformat(p["signal_date"])
        if len(days)!=6 or days!=sorted(set(days)) or not signal<days[0] or days[-1]>b.CUTOFF:
            raise ValueError("Invalid path window")
        groups[signal].append(p)
    out=[]
    roster=None
    for signal,rows in sorted(groups.items()):
        ids=tuple(sorted(r["stock_id"] for r in rows))
        if (len(ids)!=5 or len(set(ids))!=5 or "1589" in ids
            or any(not b.m.CODE.fullmatch(s) for s in ids)
            or len({tuple(r["sessions"]) for r in rows})!=1):
            raise ValueError("Incomplete aligned cohort")
        if roster is None:roster=ids
        if ids!=roster:raise ValueError("Roster drift")
        out.append((signal.isoformat(),rows[0]["sessions"][0],rows[0]["sessions"][-1],ids))
    if len(out)!=35 or b.m.fingerprint(list(roster))!=b.SAMPLE_HASH:
        raise ValueError("Frozen cohort drift")
    return out

def event_day(value):
    if type(value) is not str:raise ValueError("Date string required")
    s=value.strip()
    m=re.fullmatch(r"([0-9]{2,4})[年./-]([0-9]{1,2})[月./-]([0-9]{1,2})日?",s)
    if m:y,mo,d=map(int,m.groups())
    elif re.fullmatch(r"[0-9]{6,8}",s):y,mo,d=int(s[:-4]),int(s[-4:-2]),int(s[-2:])
    else:raise ValueError("Unrecognized event date")
    return date(y+1911 if y<1911 else y,mo,d).isoformat()

def field(fields,choices):
    matches=[x for x in choices if x in fields]
    if len(matches)!=1:raise ValueError("Ambiguous or missing official column")
    return matches[0]

def classify(raw,kind,start,end,stocks):
    if type(raw) is not bytes or not 0<len(raw)<=LIMIT:raise ValueError("Source byte bound")
    body=json.loads(raw,object_pairs_hook=b.m.strict_object,parse_constant=b.m.reject_constant)
    if type(body) is not dict:raise ValueError("Official object required")
    # Owner positive control: startDate=20220919/endDate=20220919
    # returned 2603; 20230103..20230110 returned this exact no-match
    # status. strDate failed. Recognize only the observed reduction
    # contract, never certify absence of all corporate action types.
    if (kind=="reduction" and body.get("stat")=="很抱歉，沒有符合條件的資料!"
        and body.get("fields",[])==[] and body.get("data",[])==[]):
        return {"status":"OFFICIAL_REDUCTION_NO_MATCH_ONLY","received_rows":0,
                "outside_range_rows":0,"candidates":[]}
    # Owner hash-checked TWT49U response for 2023-05-02..09:
    # exact no-match status, fields/data absent or null.
    # This is an exchange response classification, not absence proof.
    if (kind=="ex" and body.get("stat")=="很抱歉，沒有符合條件的資料!"
        and body.get("fields") is None and body.get("data") is None):
        return {"status":"OFFICIAL_EX_NO_MATCH_ONLY","received_rows":0,
                "outside_range_rows":0,"candidates":[]}
    if body.get("stat")!="OK":
        return {"status":"NON_OK_UNVERIFIED","received_rows":0,"outside_range_rows":0,"candidates":[]}
    fields=body.get("fields");rows=body.get("data")
    if (type(fields) is not list or not fields or any(type(x) is not str for x in fields)
        or len(set(fields))!=len(fields) or type(rows) is not list or len(rows)>8000):
        return {"status":"SCHEMA_UNVERIFIED","received_rows":0,"outside_range_rows":0,"candidates":[]}
    try:
        dc=field(fields,DATE_FIELDS[kind]);sc=field(fields,ID_FIELDS)
        candidates=[];outside=0
        for row in rows:
            if type(row) is not list or len(row)!=len(fields):raise ValueError("Row width")
            item=dict(zip(fields,row));d=event_day(item[dc])
            sid=item[sc]
            if type(sid) is not str:raise ValueError("Invalid issuer field")
            sid=sid.strip()
            if not start<=d<=end:
                outside+=1;continue
            if sid in stocks:
                candidates.append({"stock_id":sid,"event_date":d,"kind":kind,
                    "at_entry_close_no_entitlement":d==start,
                    "source_row_sha256":b.m.fingerprint(item),"raw_event":item})
        return {"status":"OUT_OF_RANGE_UNVERIFIED" if outside else "CANDIDATE_SCAN_ONLY",
                "received_rows":len(rows),"outside_range_rows":outside,"candidates":candidates}
    except (ValueError,TypeError,KeyError):
        return {"status":"SCHEMA_UNVERIFIED","received_rows":len(rows),"outside_range_rows":0,"candidates":[]}

def fetch(kind,start,end,get):
    url=SOURCES[kind];params={"startDate":start.replace("-",""),"endDate":end.replace("-",""),"response":"json"}
    with get(url,params=params,headers={"Accept":"application/json","User-Agent":"tw-stock-ai-owner-action-research"},
             timeout=(10,40),allow_redirects=False,stream=True) as r:
        r.raise_for_status();u=urlparse(r.url);target=urlparse(url)
        if r.status_code!=200 or (u.scheme,u.netloc,u.path)!=(target.scheme,target.netloc,target.path) or parse_qs(u.query)!={k:[v] for k,v in params.items()}:
            raise ValueError("Unexpected official response identity")
        data=bytearray()
        for chunk in r.iter_content(chunk_size=65536):
            data.extend(chunk)
            if len(data)>LIMIT:raise ValueError("Response too large")
        if not data:raise ValueError("Empty response")
        return bytes(data)

def capture(directory,window,*,get,sleeper=time.sleep):
    directory=b.c.private_dir(directory)
    signal,start,end,stocks=window
    reports=[];new=0
    for kind in SOURCES:
        stem=f"twse-action-{start}-{end}-{kind}"
        p=directory/(stem+".response.json");m=directory/(stem+".receipt.json")
        if p.is_symlink() or m.is_symlink() or p.exists()!=m.exists():
            raise ValueError("Incomplete or symlinked pair")
        binding={"scope":"OWNER_TWSE_ACTION_WINDOW_CAPTURE","source":SOURCES[kind],"kind":kind,"start":start,"end":end}
        if p.exists():
            if not p.is_file() or not m.is_file() or not 0<p.stat().st_size<=LIMIT or not 0<m.stat().st_size<=4096:
                raise ValueError("Invalid cache bounds")
            raw=p.read_bytes()
            proof=json.loads(m.read_text(encoding="utf-8"),object_pairs_hook=b.m.strict_object)
            if any(proof.get(k)!=v for k,v in binding.items()) or proof.get("response_sha256")!=sha256(raw).hexdigest():
                raise ValueError("Cache receipt mismatch")
        else:
            if new:sleeper(4)
            raw=fetch(kind,start,end,get);new+=1
            proof={**binding,"response_sha256":sha256(raw).hexdigest(),
                   "captured_at_utc":datetime.now(timezone.utc).isoformat()}
            with p.open("xb") as f:f.write(raw)
            with m.open("x",encoding="utf-8") as f:json.dump(proof,f,allow_nan=False)
        report=classify(raw,kind,start,end,stocks)
        reports.append({**binding,**report,"response_sha256":proof["response_sha256"]})
    return {"signal_date":signal,"entry_date":start,"exit_date":end,"new_requests":new,"sources":reports}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("raw-research","cache-dir","out"):p.add_argument("--"+key,required=True)
    p.add_argument("--offset",type=int,default=0);p.add_argument("--count",type=int,default=1)
    a=p.parse_args();stage="MANIFEST"
    try:
        payload,_=b.m.read_panel(b.m.private_path(a.raw_research,existing=True))
        queue=windows(payload["private_action_window_paths"])
        if not 0<=a.offset<len(queue) or not 1<=a.count<=5 or a.offset+a.count>len(queue):
            raise ValueError("Bounded batch required")
        out=b.m.private_path(a.out,existing=False)
        stage="OFFICIAL_CAPTURE"
        import requests
        reports=[]
        with requests.Session() as session:
            for w in queue[a.offset:a.offset+a.count]:
                if reports:time.sleep(4)
                reports.append(capture(a.cache_dir,w,get=session.get))
                if any(s["status"] not in ("CANDIDATE_SCAN_ONLY","OFFICIAL_REDUCTION_NO_MATCH_ONLY","OFFICIAL_EX_NO_MATCH_ONLY")
                       for s in reports[-1]["sources"]):
                    break
        summary={"scope":"OWNER_TWSE_ACTION_CANDIDATE_SCAN_ONLY","offset":a.offset,"windows_scanned":len(reports),
            "batch_requested_windows":a.count,
            "batch_source_contract_pass":len(reports)==a.count and all(s["status"] in ("CANDIDATE_SCAN_ONLY","OFFICIAL_REDUCTION_NO_MATCH_ONLY","OFFICIAL_EX_NO_MATCH_ONLY") for r in reports for s in r["sources"]),
            "total_frozen_windows":35,"new_official_requests":sum(r["new_requests"] for r in reports),
            "source_status_counts":dict(Counter(s["status"] for r in reports for s in r["sources"])),
            "matched_candidate_rows":sum(len(s["candidates"]) for r in reports for s in r["sources"]),
            "candidate_receipts_sha256":b.m.fingerprint(reports),
            "all_action_types_coverage_verified":False,"zero_event_windows_certified":0,
            "approved_total_return_labels":0,"production_neon_reads":0,"production_neon_writes":0,
            "line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}
        stage="OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump({"summary":summary,"private_window_receipts":reports},f,ensure_ascii=False,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(summary,allow_nan=False))
        if not summary["batch_source_contract_pass"]:
            raise SystemExit("Stopped on unverified source contract; receipt preserved")
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon or LINE actions") from None
if __name__=="__main__":main()
