"""Bounded TWSE market-session witness for frozen holding paths, not release approval."""
import argparse
from datetime import date,datetime,timezone,timedelta
from hashlib import sha256
import json
import re
import time
from urllib.parse import urlparse,parse_qs
from scripts import owner_twse_action_window_candidates as a

URL="https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
FIELDS=("日期","成交股數","成交金額","成交筆數","發行量加權股價指數","漲跌點數")
LIMIT=1_000_000

def parse(raw,month):
    p=json.loads(raw,object_pairs_hook=a.b.m.strict_object,parse_constant=a.b.m.reject_constant)
    if p.get("stat")!="OK" or tuple(p.get("fields",[]))!=FIELDS:
        raise ValueError("Unexpected monthly market schema")
    rows=p["data"]
    if type(rows) is not list or not 1<=len(rows)<=31:raise ValueError("Invalid monthly rows")
    days=[]
    for r in rows:
        if type(r) is not list or len(r)!=len(FIELDS):raise ValueError("Row width")
        if not isinstance(r[0],str) or not re.fullmatch(r"[0-9]{3}/[0-9]{2}/[0-9]{2}",r[0]):
            raise ValueError("Unexpected ROC date")
        d=a.event_day(r[0])
        if d[:7]!=month or date.fromisoformat(d).weekday()>=5:
            raise ValueError("Out of month or weekend")
        if any(not isinstance(v,str) or not re.fullmatch(r"[0-9][0-9,]*",v) or int(v.replace(",",""))<=0 for v in r[1:4]):
            raise ValueError("No positive market trades")
        days.append(d)
    if days!=sorted(set(days)):raise ValueError("Unsorted or duplicate market dates")
    return days

def months_between(start,end):
    d=date.fromisoformat(start).replace(day=1);stop=date.fromisoformat(end).replace(day=1)
    out=[]
    while d<=stop:
        out.append(d.isoformat()[:7])
        d=(d.replace(day=28)+timedelta(days=4)).replace(day=1)
    return out

def compare(paths,market_days):
    by_signal={}
    for p in paths:
        d=p["signal_date"];s=p["sessions"]
        if d in by_signal and by_signal[d]!=s:raise ValueError("Unaligned cohort")
        by_signal[d]=s
    verified=0;pending=[];mismatch=[]
    for d,s in sorted(by_signal.items()):
        months=months_between(d,s[-1])
        if any(k not in market_days for k in months):
            pending.append(d);continue
        actual=sorted(x for k in months for x in market_days[k] if d<x<=s[-1])
        if d not in market_days[d[:7]] or actual!=s:
            mismatch.append({"signal_date":d,"expected_sessions":s,"observed_sessions":actual,
                             "signal_is_market_session":d in market_days[d[:7]]})
        else:verified+=1
    return {"windows_verified":verified,"windows_pending":len(pending),"window_mismatches":mismatch,
            "pending_signal_dates":pending}

def capture(directory,month,get):
    p=directory/("twse-fmtqik-"+month+".response.json")
    r=directory/("twse-fmtqik-"+month+".receipt.json")
    if p.is_symlink() or r.is_symlink() or p.exists()!=r.exists():raise ValueError("Invalid cache pair")
    binding={"source":URL,"month":month}
    if p.exists():
        if not p.is_file() or not r.is_file() or not 0<p.stat().st_size<=LIMIT or not 0<r.stat().st_size<=4096:
            raise ValueError("Cache bounds")
        raw=p.read_bytes();proof=json.loads(r.read_text(encoding="utf-8"),object_pairs_hook=a.b.m.strict_object)
        if any(proof.get(k)!=v for k,v in binding.items()) or proof.get("response_sha256")!=sha256(raw).hexdigest():
            raise ValueError("Cache hash mismatch")
        return parse(raw,month),0
    params={"date":month.replace("-","")+"01","response":"json"}
    with get(URL,params=params,timeout=(10,35),allow_redirects=False,stream=True,
             headers={"Accept":"application/json","User-Agent":"tw-stock-ai-owner-calendar-research"}) as resp:
        resp.raise_for_status();u=urlparse(resp.url);t=urlparse(URL)
        if resp.status_code!=200 or (u.scheme,u.netloc,u.path)!=(t.scheme,t.netloc,t.path) or parse_qs(u.query)!={k:[v] for k,v in params.items()}:
            raise ValueError("Unexpected response identity")
        raw=bytearray()
        for chunk in resp.iter_content(65536):
            raw.extend(chunk)
            if len(raw)>LIMIT:raise ValueError("Response bound")
    days=parse(bytes(raw),month)
    proof={**binding,"response_sha256":sha256(raw).hexdigest(),"captured_at_utc":datetime.now(timezone.utc).isoformat()}
    with p.open("xb") as f:f.write(raw)
    with r.open("x",encoding="utf-8") as f:json.dump(proof,f,allow_nan=False)
    return days,1

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ("raw-research","cache-dir","out"):parser.add_argument("--"+k,required=True)
    parser.add_argument("--max-new",type=int,default=1)
    opt=parser.parse_args();stage="INPUT"
    try:
        if not 0<=opt.max_new<=5:raise ValueError("Request budget")
        payload,_=a.b.m.read_panel(a.b.m.private_path(opt.raw_research,existing=True))
        paths=payload["private_action_window_paths"];queue=a.windows(paths)
        months=sorted({k for d,_,end,_ in queue for k in months_between(d,end)})
        directory=a.b.c.private_dir(opt.cache_dir);out=a.b.m.private_path(opt.out,existing=False)
        stage="MONTH_CAPTURE";new=0;market={}
        import requests
        with requests.Session() as session:
            for month in months:
                p=directory/("twse-fmtqik-"+month+".response.json")
                r=directory/("twse-fmtqik-"+month+".receipt.json")
                if not p.exists() and not r.exists() and new>=opt.max_new:continue
                if not p.exists() and new:time.sleep(4)
                market[month],n=capture(directory,month,session.get);new+=n
        stage="COMPARE"
        result=compare(paths,market)
        result.update(scope="OWNER_TWSE_MARKET_SESSION_WINDOW_WITNESS",months_required=len(months),
            months_cached=len(market),new_official_requests=new,windows_total=len(queue),
            calendar_window_witness_pass=result["windows_verified"]==len(queue) and not result["window_mismatches"],
            full_historical_calendar_verified=False,corporate_action_coverage_verified=False,
            approved_total_return_labels=0,alpha_verified=False,production_neon_reads=0,production_neon_writes=0,
            line_messages_sent=0,paid_upgrade_requested=False,model_release="BLOCKED")
        with out.open("x",encoding="utf-8") as f:json.dump(result,f,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps(result,allow_nan=False))
        if result["window_mismatches"]:raise SystemExit("Window mismatch; evidence retained")
    except Exception:
        raise SystemExit("FAILED safely; calendar_stage="+stage+"; no Neon or LINE actions") from None
if __name__=="__main__":main()
