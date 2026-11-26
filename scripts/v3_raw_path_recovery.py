"""Bounded owner-local TWSE raw-close recovery. No database access or label approval."""
import argparse
import base64
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import time

def digest(rows):
    return sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),
                            ensure_ascii=True,allow_nan=False).encode()).hexdigest()

def day(v):
    if not isinstance(v,str) or date.fromisoformat(v).isoformat()!=v:
        raise ValueError("Invalid date")
    return date.fromisoformat(v)

class CapturePaused(Exception):
    pass

def recover(plan,actions,lookup,cutoff):
    m=plan["summary"]
    missing=plan["private_missing_keys"]
    paths=actions["private_matched_rows"]
    if (m["scope"]!="V3_OFFLINE_RAW_PATH_EXPANSION_PLAN_ONLY" or
        m["model_release"]!="BLOCKED" or m["execution_labels_approved"]!=0 or
        m["missing_path_rows"]!=len(missing) or not 1<=len(missing)<=100000 or
        digest(missing)!=m["missing_keys_sha256"] or
        digest(paths)!=m["existing_paths_sha256"] or
        actions["summary"]["matched_panel_sha256"]!=m["existing_paths_sha256"]):
        raise ValueError("Input plan or original paths changed")
    known=set()
    windows={}
    for r in paths:
        if r["market"].lower()!="twse":
            continue
        d=day(r["signal_date"])
        s=tuple(day(x) for x in r["sessions"])
        if len(s)!=6 or s[0]<=d or any(a>=b for a,b in zip(s,s[1:])):
            raise ValueError("Invalid original path window")
        if d in windows and windows[d]!=s:
            raise ValueError("Inconsistent original session window")
        windows[d]=s
        known.add((d,r["stock_id"]))
    groups=defaultdict(list)
    seen=set()
    for r in missing:
        d=day(r["signal_date"]); sid=r["stock_id"]
        if (r["market"]!="twse" or not isinstance(sid,str) or not re.fullmatch("[0-9]{4,6}",sid) or
            sid in ("1589","1808") or (d,sid) in seen or (d,sid) in known):
            raise ValueError("Invalid missing key")
        seen.add((d,sid))
        groups[d].append(sid)
    recovered=[]
    counts=Counter()
    reports=[]
    for d,stocks in sorted(groups.items()):
        s=windows.get(d)
        status="EXISTING_WINDOW_DATES" if s else "SEQUENTIAL_OFFICIAL_DATE_PROBE"
        observed=[]
        daily={}
        if d>=cutoff or (cutoff-d).days<6 or (s and s[-1]>cutoff):
            counts["not_yet_mature"]+=len(stocks)
            reports.append(dict(signal_date=d.isoformat(),status="NOT_YET_MATURE",requested=len(stocks),recovered=0))
            continue
        try:
            if s:
                for t in s:
                    prices=lookup(t)
                    if prices is None:
                        raise CapturePaused("Previously saved session returned no data")
                    daily[t]=prices
            else:
                for offset in range(1,32):
                    t=d+timedelta(days=offset)
                    if t>cutoff:
                        break
                    prices=lookup(t)
                    if prices is None:
                        continue
                    observed.append(t)
                    daily[t]=prices
                    if len(observed)==6:
                        break
                s=tuple(observed)
            if len(s)!=6:
                counts["window_unresolved"]+=len(stocks)
                reports.append(dict(signal_date=d.isoformat(),status="SIX_SESSIONS_UNRESOLVED",requested=len(stocks),recovered=0))
                continue
        except CapturePaused:
            counts["capture_pending"]+=len(stocks)
            reports.append(dict(signal_date=d.isoformat(),status="CAPTURE_PENDING",requested=len(stocks),recovered=0))
            continue
        n=0
        for sid in sorted(stocks):
            values=[daily[t].get(sid) for t in s]
            if any(v is None for v in values):
                counts["missing_stock_close"]+=1
                continue
            prices=[Decimal(v) for v in values]
            if any(not p.is_finite() or p<=0 for p in prices):
                raise ValueError("Invalid source price")
            recovered.append(dict(market="twse",stock_id=sid,signal_date=d.isoformat(),
                sessions=[t.isoformat() for t in s],raw_closes=values,
                raw_gross_return=str(prices[-1]/prices[0]-1),
                calendar_selection=status,approved_total_return=False,
                corporate_action_coverage_verified=False,execution_label_approved=False))
            n+=1
        counts["recovered"]+=n
        reports.append(dict(signal_date=d.isoformat(),status=status,requested=len(stocks),recovered=n))
    if sum(counts.values())!=len(missing):
        raise ValueError("Recovery accounting mismatch")
    return {"summary":dict(scope="V3_TWSE_RAW_CLOSE_RECOVERY_RESEARCH_ONLY",
             missing_plan_rows=len(missing),recovered_path_rows=len(recovered),
             remaining_path_rows=len(missing)-len(recovered),counts=dict(counts),
             per_window=reports,source_plan_sha256=m["missing_keys_sha256"],
             recovered_paths_sha256=digest(recovered),cutoff=cutoff.isoformat(),
             official_calendar_independently_verified=False,
             no_data_response_is_not_independent_holiday_proof=True,
             historical_publication_vintage_verified=False,
             approved_total_return_labels=0,execution_labels_approved=0,
             approved_training_feature_rows=0,v3_model_trained=False,model_release="BLOCKED",
             production_neon_reads=0,production_neon_writes=0,line_messages_sent=0),
            "private_recovered_paths":recovered}

class LocalCapture:
    MAX_BYTES=8*1024*1024
    def __init__(self,root,budget,delay):
        self.root=root
        self.budget=budget
        self.delay=delay
        self.requests=0
        self.cache_hits=0
        self.stop_reason=None
        self.memo={}
        self.receipts={}
    def parse(self,raw,d):
        from src.official_market_feed import _parse_twse
        body=json.loads(raw)
        if not isinstance(body,dict):
            raise ValueError("Invalid official body")
        if body.get("stat")!="OK":
            from src.twse_dated_history import NO_DATA_MARKERS
            if any(marker in str(body.get("stat") or "") for marker in NO_DATA_MARKERS):
                return None
            raise ValueError("Unrecognized official status")
        bars=_parse_twse(body,d)
        result={}
        for b in bars:
            sid=b["stock_id"]
            if sid in result or b["trade_date"]!=d or b["market"]!="twse":
                raise ValueError("Invalid or duplicate daily bar")
            close=b["close"]
            if close is None or not Decimal(str(close)).is_finite() or close<=0:
                raise ValueError("Invalid daily close")
            result[sid]=str(close)
        if len(result)<500 or "2330" not in result:
            raise ValueError("Insufficient dated market evidence")
        return result
    def __call__(self,d):
        if d in self.memo:
            return self.memo[d]
        path=self.root/(d.isoformat()+".json")
        if path.exists():
            if path.stat().st_size>self.MAX_BYTES*2:
                raise ValueError("Oversized local cache")
            receipt=json.loads(path.read_text(encoding="utf-8"))
            raw=base64.b64decode(receipt["raw_base64"],validate=True)
            if receipt["date"]!=d.isoformat() or len(raw)>self.MAX_BYTES or sha256(raw).hexdigest()!=receipt["response_sha256"]:
                raise ValueError("Local source cache digest mismatch")
            result=self.parse(raw,d)
            self.cache_hits+=1
        else:
            if self.stop_reason or self.requests>=self.budget:
                raise CapturePaused("Batch limit")
            import requests
            from src.official_market_feed import TWSE_URL,HEADERS
            if self.requests:
                time.sleep(self.delay)
            self.requests+=1
            try:
                with requests.get(TWSE_URL,params={"date":d.strftime("%Y%m%d"),
                    "type":"ALLBUT0999","response":"json"},headers=HEADERS,
                    timeout=(10,35),stream=True,allow_redirects=False) as response:
                    if response.status_code!=200:
                        raise ValueError("HTTP response not 200")
                    buf=bytearray()
                    for chunk in response.iter_content(65536):
                        buf.extend(chunk)
                        if len(buf)>self.MAX_BYTES:
                            raise ValueError("Oversized response")
                raw=bytes(buf)
                result=self.parse(raw,d)
            except (requests.RequestException,ValueError):
                self.stop_reason="NETWORK_OR_SOURCE_VALIDATION_PAUSED"
                raise CapturePaused(self.stop_reason) from None
            receipt=dict(date=d.isoformat(),response_sha256=sha256(raw).hexdigest(),
                         captured_at_utc=datetime.now(timezone.utc).isoformat(),
                         raw_base64=base64.b64encode(raw).decode("ascii"))
            with path.open("x",encoding="utf-8") as f:
                json.dump(receipt,f,separators=(",",":"))
        self.receipts[d.isoformat()]=receipt["response_sha256"]
        self.memo[d]=result
        return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan",type=Path,required=True)
    p.add_argument("--actions",type=Path,required=True)
    p.add_argument("--cache",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--cutoff",type=day,required=True)
    p.add_argument("--max-new",type=int,default=10)
    a=p.parse_args()
    # Never query current or future sessions; same-day data can be incomplete.
    from zoneinfo import ZoneInfo
    if a.cutoff>=datetime.now(ZoneInfo("Asia/Taipei")).date() or not 0<=a.max_new<=10:
        p.error("Require a past cutoff and at most ten new calls")
    for path in (a.cache,a.output):
        path=path.resolve()
        if any((x/".git").exists() for x in (path,*path.parents)):
            p.error("Private files must be outside Git")
    if a.output.exists():
        p.error("Cannot overwrite output")
    def load(path):
        if path.stat().st_size>128*1024*1024:
            raise ValueError("Oversized private input")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    a.cache.mkdir(exist_ok=True)
    capture=LocalCapture(a.cache,a.max_new,15)
    result=recover(load(a.plan),load(a.actions),capture,a.cutoff)
    result["summary"].update(network_requests=capture.requests,
        source_cache_hits=capture.cache_hits,network_stop_reason=capture.stop_reason,
        paid_upgrade_requested=False,source_response_digests=capture.receipts)
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(result,f,separators=(",",":"),allow_nan=False)
    print(json.dumps(result["summary"],indent=2,allow_nan=False))

if __name__=="__main__":
    main()
