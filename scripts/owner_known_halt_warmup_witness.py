"""Known 1101 halt witness; no price imputation, no general gap waiver."""
import argparse
from datetime import date
from collections import defaultdict
import json,time
from scripts import owner_raw_price_ridge_diagnostic_offline as r
from scripts import owner_twse_market_session_window_witness as c

HALT="2025-08-13"
SID="1101"
SIGNALS=("2025-08-29","2025-09-30","2025-10-31","2025-11-28","2025-12-31","2026-01-30","2026-02-26","2026-03-31","2026-04-30","2026-05-29","2026-06-30","2026-07-31")
SOURCES=(
"https://wwwc.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d697fc438f01989dd5fa3502a6.pdf",
"https://wwwc.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d697fc438f0198a36441f702b8.pdf")
MONTHS=c.months_between("2024-07-01","2026-08-31")

def verify(stocks,features,late,market):
    if set(market)!=set(MONTHS):raise ValueError("Complete bounded independent calendar required")
    days=sorted({d for v in market.values() for d in v})
    observed=defaultdict(set)
    for x in late:
        d=x["trade_date"].isoformat()
        if MONTHS[0]<=d[:7]<=MONTHS[-1]:
            if d in observed[x["stock_id"]]:raise ValueError("Duplicate bar")
            observed[x["stock_id"]].add(d)
    if set(days)!=set().union(*observed.values()):
        raise ValueError("Market calendar differs from stock union")
    if SID not in stocks or HALT not in days or HALT in observed[SID] or not {"2025-08-12","2025-08-14"}<=observed[SID]:
        raise ValueError("Halt boundary not corroborated")
    by=defaultdict(set)
    for f in features:by[f["signal_date"]].add(f["stock_id"])
    missing=[(d,s) for d,v in sorted(by.items()) for s in sorted(set(stocks)-v)]
    if missing!=[(d,SID) for d in SIGNALS]:raise ValueError("Unexpected missing cohort")
    witnesses=[]
    for d in SIGNALS:
        if d not in days or d not in observed[SID] or d!=max(x for x in days if x[:7]==d[:7]):
            raise ValueError("Invalid month end signal")
        eligible=[x for x in days if x<=d and x!=HALT]
        window=eligible[-240:]
        if len(window)!=240 or not set(window)<=observed[SID]:
            raise ValueError("Another missing real issuer session")
        witnesses.append({"signal_date":d,"stock_id":SID,"required_actual_sessions":240,
                          "first_actual_session":window[0],"last_actual_session":window[-1],
                          "session_sha256":r.b.m.fingerprint(window)})
    return witnesses

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("monthly","price-cache","calendar-cache","out"):p.add_argument("--"+k,required=True)
    p.add_argument("--max-new",type=int,default=5)
    a=p.parse_args();stage="INPUT"
    try:
        if not 0<=a.max_new<=5:raise ValueError("Request budget")
        b=r.b
        payload,_=b.m.read_panel(b.m.private_path(a.monthly,existing=True))
        stocks=tuple(payload["sample_stock_ids"]);features=payload["private_feature_rows"]
        if b.m.fingerprint(list(stocks))!=b.SAMPLE_HASH or len(features)!=228 or b.m.fingerprint(features)!=r.FEATURE_HASH:
            raise ValueError("Frozen panel changed")
        stage="PRICE_CACHE"
        late,h=b.load_late(stocks,a.price_cache)
        if h!=r.LATE_HASH:raise ValueError("Frozen source changed")
        stage="PRIVATE_PATHS"
        directory=b.c.private_dir(a.calendar_cache);out=b.m.private_path(a.out,existing=False)
        stage="CALENDAR";new=0;market={}
        import requests
        with requests.Session() as session:
            for month in MONTHS:
                raw=directory/("twse-fmtqik-"+month+".response.json")
                proof=directory/("twse-fmtqik-"+month+".receipt.json")
                if not raw.exists() and not proof.exists() and new>=a.max_new:continue
                if not raw.exists() and new:time.sleep(4)
                market[month],n=c.capture(directory,month,session.get);new+=n
        stage="VERIFY";witnesses=verify(stocks,features,late,market) if set(market)==set(MONTHS) else []
        result={"scope":"OWNER_KNOWN_HALT_WARMUP_ELIGIBILITY_WITNESS",
                "months_required":len(MONTHS),"months_cached":len(market),"new_official_requests":new,
                "halt_stock_id":SID,"halt_date":HALT,"resume_date":"2025-08-14","reviewed_exchange_notice_urls":list(SOURCES),
                "notice_reviewed_not_local_byte_archived":True,
                "verified_eligible_missing_rows":len(witnesses),"witnesses":witnesses,
                "factors_recomputed":False,"price_rows_imputed":0,"production_neon_reads":0,
                "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}
        with out.open("x",encoding="utf-8") as f:json.dump(result,f,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps(result,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; halt_stage="+stage+"; no Neon or LINE actions") from None
if __name__=="__main__":main()
