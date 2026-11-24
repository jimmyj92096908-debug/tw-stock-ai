"""Owner-local free TWSE STOCK_DAY capture canary; no Neon connection.

A fixed two-issuer/two-month pilot anchored to the accepted quarterly panel.
Store exact official response bytes locally outside Git. Cached files are
reparsed and hash checked; capture time is not historical publication time.
Do not pass these bars as a full monthly model input or certify missing days.
"""
from collections import Counter
from datetime import date,datetime,timezone
from decimal import Decimal
from hashlib import sha256
import argparse
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs,urlparse

from scripts import owner_twse_tpex_quarterly_panel_merge_offline as panel
from scripts import owner_quarterly_chip_vintage_coverage_readonly as chip

ENDPOINT="https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
STOCKS=("1101","2330")
MONTHS=("2023-01","2023-02")
QUEUE=tuple((s,m) for s in STOCKS for m in MONTHS)
LIMIT=2_000_000
FIELDS=("日期","成交股數","成交金額","開盤價","最高價","最低價","收盤價")
NUMBER=re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?",re.ASCII)


def parse_number(v,*,integer=False):
    if type(v) is not str or len(v)>32 or not NUMBER.fullmatch(v.strip()):
        raise ValueError("Unverified numeric source value")
    n=Decimal(v.strip().replace(",",""))
    if integer:
        if n!=n.to_integral_value() or n>2**63-1:
            raise ValueError("Invalid source share volume")
        return int(n)
    return n


def parse_month(raw,stock,month,*,queue=QUEUE):
    if (stock,month) not in queue or type(raw) is not bytes or not 0<len(raw)<=LIMIT:
        raise ValueError("Outside fixed capture budget")
    body=json.loads(raw,object_pairs_hook=panel.strict_object,parse_constant=panel.reject_constant)
    if type(body) is not dict or body.get("stat")!="OK":
        raise ValueError("Unverified or no-data source response")
    title=body.get("title");fields=body.get("fields");rows=body.get("data")
    if (type(title) is not str or not re.search(r"(?<![0-9])"+stock+r"(?![0-9])",title)
        or type(fields) is not list or tuple(fields[:7])!=FIELDS
        or type(rows) is not list or not 1<=len(rows)<=31):
        raise ValueError("Wrong issuer or source column contract")
    result=[];seen=set()
    for rec in rows:
        if type(rec) is not list or len(rec)!=len(fields):
            raise ValueError("Malformed official row")
        d=rec[0]
        if type(d) is not str or not re.fullmatch(r"[0-9]{3}/[0-9]{2}/[0-9]{2}",d):
            raise ValueError("Unexpected ROC date")
        y,m,day=map(int,d.split("/"));day=date(y+1911,m,day)
        if day.strftime("%Y-%m")!=month or day.weekday()>=5 or day in seen:
            raise ValueError("Wrong month, weekend or duplicate official day")
        seen.add(day)
        v=parse_number(rec[1],integer=True)
        o,h,l,c=map(parse_number,rec[3:7])
        if not 0<l<=min(o,c)<=max(o,c)<=h:
            raise ValueError("Invalid official OHLC")
        result.append({"market":"twse","stock_id":stock,"trade_date":day.isoformat(),
            "open":format(o,"f"),"high":format(h,"f"),"low":format(l,"f"),"close":format(c,"f"),
            "volume":v,"source":"TWSE_STOCK_DAY"})
    return sorted(result,key=lambda r:r["trade_date"])


def fetch(stock,month,*,get):
    params={"response":"json","date":month.replace("-","")+"01","stockNo":stock}
    with get(ENDPOINT,params=params,headers={"Accept":"application/json","User-Agent":"tw-stock-ai-owner-source-canary"},
             timeout=(8,35),allow_redirects=False,stream=True) as r:
        r.raise_for_status();u=urlparse(r.url)
        if (r.status_code!=200 or u.scheme!="https" or u.netloc!="www.twse.com.tw"
            or u.path!="/rwd/zh/afterTrading/STOCK_DAY" or parse_qs(u.query)!={k:[v] for k,v in params.items()}):
            raise ValueError("Wrong official HTTPS response identity")
        content=bytearray()
        for chunk in r.iter_content(chunk_size=65536):
            content.extend(chunk)
            if len(content)>LIMIT:
                raise ValueError("Official response byte budget exceeded")
    return bytes(content)


def private_dir(raw):
    p=Path(raw).expanduser()
    if p.is_symlink() or any(x.is_symlink() for x in p.parents):
        raise ValueError("No symlinked source cache")
    p=p.resolve()
    if not p.is_dir() or any((x/".git").exists() for x in (p,*p.parents)):
        raise ValueError("Existing private directory outside Git required")
    return p


def capture(directory,*,get,sleeper=time.sleep,queue=QUEUE):
    directory=private_dir(directory);counts=Counter();receipts=[];requests=0
    if (type(queue) is not tuple or not 1<=len(queue)<=15 or len(set(queue))!=len(queue)
        or any(type(s) is not str or not re.fullmatch(r"[0-9]{4}",s) or s=="1589"
               or type(m) is not str or not re.fullmatch(r"202[3-6]-(0[1-9]|1[012])",m)
               or m>"2026-11" for s,m in queue)):
        raise ValueError("Invalid bounded source queue")
    # One raw response and matching capture receipt per fixed key.
    # Missing/mismatched pairs stop rather than overwrite.
    for stock,month in queue:
        stem=f"twse-stock-day-{stock}-{month}"
        raw_path=directory/(stem+".response.json");meta=directory/(stem+".receipt.json")
        if raw_path.is_symlink() or meta.is_symlink():
            raise ValueError("No symlinked cache files")
        if raw_path.exists()!=meta.exists():
            raise ValueError("Incomplete prior cache pair; manual review required")
        if raw_path.exists():
            if not raw_path.is_file() or not meta.is_file() or raw_path.stat().st_size>LIMIT or meta.stat().st_size>4096:
                raise ValueError("Invalid local cache size")
            raw=raw_path.read_bytes();proof=json.loads(meta.read_text(encoding="utf-8"),object_pairs_hook=panel.strict_object)
            rows=parse_month(raw,stock,month,queue=queue)
            if (proof.get("scope")!="OWNER_TWSE_STOCK_DAY_DIRECT_CAPTURE" or proof.get("stock_id")!=stock
                or proof.get("month")!=month or proof.get("response_sha256")!=sha256(raw).hexdigest()
                or proof.get("row_count")!=len(rows) or proof.get("endpoint")!=ENDPOINT):
                raise ValueError("Cache receipt does not bind source bytes")
            counts["reused_months"]+=1
        else:
            if requests:sleeper(4)
            raw=fetch(stock,month,get=get);requests+=1
            rows=parse_month(raw,stock,month,queue=queue)
            proof={"scope":"OWNER_TWSE_STOCK_DAY_DIRECT_CAPTURE","stock_id":stock,"month":month,
                "endpoint":ENDPOINT,"response_sha256":sha256(raw).hexdigest(),"row_count":len(rows),
                "captured_at_utc":datetime.now(timezone.utc).isoformat(),
                "historical_publication_time_verified":False}
            with raw_path.open("xb") as f:f.write(raw)
            with meta.open("x",encoding="utf-8") as f:json.dump(proof,f,allow_nan=False)
            counts["new_months"]+=1
        counts["valid_source_rows"]+=len(rows);receipts.append(proof)
    return {"scope":"OWNER_TWSE_DIRECT_LOCAL_MONTHLY_SOURCE_CANARY","schema_version":1,
        "candidate_issuer_months":len(queue),"verified_format_issuer_months":len(receipts),
        "new_official_requests":requests,**dict(counts),
        "historical_publication_vintage_verified":False,"official_calendar_completeness_verified":False,
        "cached_source_bytes_independently_authenticated":False,"full_monthly_factor_panel_created":False,
        "production_neon_reads":0,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel",required=True);p.add_argument("--cache-dir",required=True)
    a=p.parse_args();stage="FROZEN_PANEL"
    try:
        payload,_=panel.read_panel(panel.private_path(a.panel,existing=True))
        groups=chip.verify_input(payload)
        # Historical approved current roster anchor, not a fresh listing certificate.
        if not set(STOCKS)<=set(groups["twse","2026-11-20"]):
            raise ValueError("Frozen owner roster anchor missing")
        stage="PRIVATE_OFFICIAL_CAPTURE"
        import requests
        with requests.Session() as s:
            result=capture(a.cache_dir,get=s.get)
        print(json.dumps(result,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; Neon and LINE untouched") from None


if __name__=="__main__":
    main()
