"""Pinned three-event witness and two affected-path sensitivity; not a label ledger."""
import argparse
from collections import Counter
from fractions import Fraction
import json
from scripts import owner_twse_action_window_candidates as m
from src.research_entitlement_return import num,rounded

FACTS={
 ("1101","2024-07-01"):{"hash":"2c381ef853cdd897e2955f088739826891d875b5efdcf8ce67c7f9a4f501a5cd",
   "signal":"2024-06-28","cash":"1","shares":"1","prior":"34.20","ref":"33.20","type":"息",
   "sources":["https://www.findprice.com.tw/f/1101/dividend"]},
 ("1231","2024-08-05"):{"hash":"3338fe7bd16d9626b20063091b1f8e4b5c2e7a9a85c89350ea42ba293814a4ea",
   "signal":"2024-07-31","cash":"1.6","shares":"1.1","prior":"117.50","ref":"105.36","type":"權息",
   "sources":["https://www.lianhwa.com.tw/cc-36","https://m.esunsec.com.tw/news/instant-detail.aspx?id=%7BC2A455CD-A235-4258-8AB3-0F0611AC22BF%7D"]},
 ("1101","2025-07-02"):{"hash":"85fef50b0c7be3bd6727327f08d816d62b08372db8c7c31378c9f768600a4ad0",
   "signal":"2025-06-30","cash":"1","shares":"1","prior":"26.15","ref":"25.15","type":"息",
   "sources":["https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=6b864b63-1979-43c2-b4fe-3b86bd29b6cf","https://m.cnyes.com/news/print/6045793"]}}
EXPECTED={"CANDIDATE_SCAN_ONLY":39,"OFFICIAL_REDUCTION_NO_MATCH_ONLY":30,"OFFICIAL_EX_NO_MATCH_ONLY":1}

def sensitivity(closes,cash,shares):
    if len(closes)!=6:raise ValueError("Six closes required")
    prices=[num(x,positive=True) for x in closes]
    c=num(cash);s=num(shares,positive=True)
    raw=prices[-1]/prices[0]-1
    economic=(s*prices[-1]+c)/prices[0]-1
    if not -1<raw<=10 or not -1<economic<=10:raise ValueError("Return bounds")
    return {"raw_gross":rounded(raw),"event_only_gross":rounded(economic),
            "event_only_delta":rounded(economic-raw)}

def verify(paths,directory):
    queue=m.windows(paths)
    counts=Counter();seen=set();results=[]
    by_key={(p["stock_id"],p["signal_date"]):p for p in paths}
    def deny(*args,**kwargs):raise ValueError("No network permitted")
    for window in queue:
        r=m.capture(directory,window,get=deny,sleeper=lambda _:None)
        if r["new_requests"]:raise ValueError("Unexpected request")
        for src in r["sources"]:
            counts[src["status"]]+=1
            for e in src["candidates"]:
                key=(e["stock_id"],e["event_date"])
                f=FACTS.get(key)
                if f is None or key in seen or e["kind"]!="ex" or e["source_row_sha256"]!=f["hash"] or r["signal_date"]!=f["signal"]:
                    raise ValueError("Event identity changed")
                seen.add(key);raw=e["raw_event"]
                if (raw["除權息前收盤價"]!=f["prior"] or raw["除權息參考價"]!=f["ref"]
                    or raw["權/息"]!=f["type"]):raise ValueError("Source economics changed")
                prior=num(f["prior"],positive=True);ref=num(f["ref"],positive=True)
                cash=num(f["cash"]);shares=num(f["shares"],positive=True)
                unrounded=(prior-cash)/shares
                if abs(unrounded-ref)>=Fraction(1,100):raise ValueError("Reference parity")
                if abs((prior-unrounded)-num(raw["權值+息值"]))>=Fraction(1,1000000):
                    raise ValueError("Combined reference gap mismatch")
                p=by_key[(key[0],f["signal"])]
                ix=p["sessions"].index(key[1])
                if e["at_entry_close_no_entitlement"]!=(ix==0):
                    raise ValueError("Entry boundary drift")
                if ix and num(p["raw_closes"][ix-1],positive=True)!=prior:
                    raise ValueError("Previous close parity failure")
                result={"stock_id":key[0],"event_date":key[1],"signal_date":f["signal"],
                    "source_row_sha256":f["hash"],"cash_per_old_share_candidate":f["cash"],
                    "share_multiplier_candidate":f["shares"],"reference_arithmetic_match":True,
                    "entry_close_excluded":ix==0,"prior_close_path_matched":ix>0,
                    "sources":f["sources"],"issuer_terms_reviewed_from_web_not_archived":True}
                result.update(sensitivity(p["raw_closes"],f["cash"] if ix else "0",f["shares"] if ix else "1"))
                results.append(result)
    if counts!=EXPECTED or seen!=set(FACTS):raise ValueError("Frozen evidence incomplete")
    return {"scope":"OWNER_PINNED_KNOWN_EVENT_ONLY_SENSITIVITY",
        "windows_reverified":len(queue),"source_status_counts":dict(counts),
        "matched_event_count":len(results),"in_holding_events":sum(not r["entry_close_excluded"] for r in results),
        "events":results,"approved_total_return_labels":0,"all_action_types_coverage_verified":False,
        "stock_entitlement_marked_at_exit_not_actual_sale":True,"cash_not_reinvested":True,
        "model_trained":False,"production_neon_reads":0,"production_neon_writes":0,
        "official_requests":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("raw-research","cache-dir","out"):p.add_argument("--"+key,required=True)
    a=p.parse_args()
    try:
        payload,_=m.b.m.read_panel(m.b.m.private_path(a.raw_research,existing=True))
        out=m.b.m.private_path(a.out,existing=False)
        result=verify(payload["private_action_window_paths"],a.cache_dir)
        with out.open("x",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=True,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps(result,ensure_ascii=True,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; known-event witness not approved; no Neon or LINE actions") from None
if __name__=="__main__":main()
