"""Exact frozen-panel replay plus 12 exchange-halt eligible rows, offline only."""
import argparse
from collections import defaultdict
from datetime import date
import json, math, os
from pathlib import Path
from scripts import owner_2022_warmup_factor_research_offline as w
from scripts import owner_known_halt_warmup_witness as h
from scripts import owner_raw_price_ridge_diagnostic_offline as r
from src.raw_factor_feature_bridge import build_research_features

b=w.b
def extend(stocks,features,groups,witnesses):
    if len(features)!=228 or b.m.fingerprint(features)!=r.FEATURE_HASH:
        raise ValueError("Frozen original rows changed")
    expected={(h.SID,d) for d in h.SIGNALS}
    if {(x["stock_id"],x["signal_date"]) for x in witnesses}!=expected or len(witnesses)!=12:
        raise ValueError("Wrong eligibility set")
    original={(x["stock_id"],x["signal_date"]):x for x in features}
    if len(original)!=228 or expected&original.keys():
        raise ValueError("Duplicate or overlapping rows")
    all_rows=[]
    for sid,signal in sorted(original.keys()|expected,key=lambda k:(k[1],k[0])):
        day=date.fromisoformat(signal)
        prefix=sorted((x for x in groups[sid] if x["trade_date"]<=day),key=lambda x:x["trade_date"])
        if (sid,signal) in expected:
            proof=next(x for x in witnesses if x["signal_date"]==signal)
            tail=[x["trade_date"].isoformat() for x in prefix[-240:]]
            if len(tail)!=240 or h.HALT in tail or b.m.fingerprint(tail)!=proof["session_sha256"]:
                raise ValueError("Actual prefix differs from calendar witness")
        z=build_research_features(prefix,stock_id=sid,cutoff=day,signal_dates=[day],market="twse")
        if z["included_signals"]!=1 or z["raw_last_date"]!=signal:
            raise ValueError("Factor engine rejected source prefix")
        f=z["signals"][0];v=f["feature_vector"]
        if f["as_of_date"]!=signal or f["label_or_forward_price_observed"] is not False or len(v)!=12 or not all(math.isfinite(x) for x in v):
            raise ValueError("Invalid feature vector")
        row={"stock_id":sid,"market":"twse","signal_date":signal,"feature_vector":v,
             "prefix_source_rows":len(prefix),"prefix_source_sha256":z["raw_source_fingerprint_sha256"]}
        if (sid,signal) in original and row!=original[sid,signal]:
            raise ValueError("Original exact factor replay mismatch")
        all_rows.append(row)
    by=defaultdict(set)
    for x in all_rows:by[x["signal_date"]].add(x["stock_id"])
    if len(all_rows)!=240 or len(by)!=48 or any(s!=set(stocks) for s in by.values()):
        raise ValueError("Incomplete reconstructed panel")
    return all_rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("monthly","price-cache","calendar-cache","archive-2021","archive-2022","key-vault","out"):
        p.add_argument("--"+k,required=True)
    a=p.parse_args();stage="INPUT"
    try:
        payload,_=b.m.read_panel(b.m.private_path(a.monthly,existing=True))
        stocks=tuple(payload["sample_stock_ids"]);features=payload["private_feature_rows"]
        if b.m.fingerprint(list(stocks))!=b.SAMPLE_HASH or b.m.fingerprint(features)!=r.FEATURE_HASH:
            raise ValueError("Frozen input mismatch")
        out=b.m.private_path(a.out,existing=False)
        stage="SOURCE_CACHE"
        late,lh=b.load_late(stocks,a.price_cache)
        direct,wh=w.load_warmup(stocks,a.price_cache)
        if lh!=r.LATE_HASH or wh!=payload["summary"]["warmup_response_hashes_sha256"]:
            raise ValueError("Source bytes drift")
        stage="HALT_WITNESS"
        directory=b.c.private_dir(a.calendar_cache)
        def deny(*args,**kwargs):raise ValueError("Network forbidden")
        market={k:h.c.capture(directory,k,deny)[0] for k in h.MONTHS}
        witnesses=h.verify(stocks,features,late,market)
        stage="AES_AUTHENTICATION"
        p21=b.depth._private_archives(a.archive_2021);p22=b.depth._private_archives(a.archive_2022)
        if set(p21)&set(p22):raise ValueError("Overlapping archives")
        key=b.depth.resolve_archive_key(vault_path=Path(a.key_vault),env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
        a21,d21=b.early.archive_bars(p21,key=key,start=b.depth.START,end=date(2022,1,1),expected_days=28,eligible=set(stocks))
        a22,d22=b.early.archive_bars(p22,key=key,start=date(2022,1,1),end=b.START,expected_days=162,eligible=set(stocks))
        if len(a21)+len(a22)!=950:raise ValueError("Early source count drift")
        stage="REPLAY"
        proof,groups,calendar=w.merge_warmup(stocks,a21+a22,direct,late)
        if groups is None or proof["direct_2022_observed_days"]!=246:
            raise ValueError("Source parity gate")
        rows=extend(stocks,features,groups,witnesses)
        stage="RAW_RESEARCH"
        report,paths,excluded=r.build_paths(stocks,rows,late)
        if len(paths)!=235 or len(report)!=47 or excluded!={b.CUTOFF.isoformat():"UNMATURED_WINDOW"}:
            raise ValueError("Expanded price paths mismatch")
        summary={"scope":"OWNER_HALT_RECOMPUTED_RAW_MONTHLY_PANEL","accepted_feature_rows":len(rows),
            "accepted_feature_values":len(rows)*12,"original_exact_rows_reproduced":228,"new_halt_feature_rows":12,
            "whole_five_stock_signal_dates":48,"complete_raw_path_dates":len(report),"raw_price_path_rows":len(paths),
            "excluded_signal_dates":excluded,"private_feature_rows_sha256":b.m.fingerprint(rows),
            "private_action_window_paths_sha256":b.m.fingerprint(paths),"source_cache_sha256":lh,
            "warmup_cache_sha256":wh,"price_rows_imputed":0,"official_requests":0,
            "approved_total_return_labels":0,"corporate_action_coverage_verified":False,
            "full_historical_calendar_verified":False,"historical_publication_vintage_verified":False,
            "current_roster_not_historical_pit":True,"source_selection_conditioned_on_later_availability":True,
            "model_trained":False,"alpha_verified":False,"production_neon_reads":0,"production_neon_writes":0,
            "line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}
        stage="OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump({"summary":summary,"sample_stock_ids":stocks,"private_feature_rows":rows,
                       "private_action_window_paths":paths},f,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps(summary,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; recompute_stage="+stage+"; no Neon or LINE actions") from None
if __name__=="__main__":main()
