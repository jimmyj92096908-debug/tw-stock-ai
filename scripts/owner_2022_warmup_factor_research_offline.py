"""Offline 2022 warmup reconciliation and 48-date factor research.
Exact OHLCV overlap, no filling absent stock sessions, no labels or training.
Uses the same fixed sample and observed-market-session gate as prior research.
"""
import argparse
from collections import defaultdict,Counter
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from scripts import owner_five_stock_aes_direct_factor_research_offline as b
from scripts import twse_owner_quarterly_raw_feature_sample_readonly as q
from src import research_monthly_fold_plan as folds

def load_warmup(stocks,directory):
    directory=b.c.private_dir(directory)
    rows=[];hashes=[]
    for quarter in range(1,5):
        queue=b.five.queue_for(stocks,2022,quarter)
        for sid,month in queue:
            stem=f"twse-stock-day-{sid}-{month}"
            p=directory/(stem+".response.json")
            m=directory/(stem+".receipt.json")
            if (p.is_symlink() or m.is_symlink() or not p.is_file() or not m.is_file()
                or not 0<p.stat().st_size<=b.c.LIMIT or not 0<m.stat().st_size<=4096):
                raise ValueError("Missing or invalid warmup cache pair")
            raw=p.read_bytes()
            proof=json.loads(m.read_text(encoding="utf-8"),object_pairs_hook=b.m.strict_object)
            bars=b.c.parse_month(raw,sid,month,queue=queue)
            digest=sha256(raw).hexdigest()
            if (proof.get("scope")!="OWNER_TWSE_STOCK_DAY_DIRECT_CAPTURE"
                or proof.get("stock_id")!=sid or proof.get("month")!=month
                or proof.get("response_sha256")!=digest or proof.get("row_count")!=len(bars)
                or proof.get("endpoint")!=b.c.ENDPOINT):
                raise ValueError("Warmup receipt mismatch")
            hashes.append([sid,month,digest])
            for r in bars:
                row=dict(r,trade_date=date.fromisoformat(r["trade_date"]))
                for k in ("open","high","low","close"):row[k]=Decimal(row[k])
                rows.append(row)
    return rows,b.m.fingerprint(hashes)

def merge_warmup(stocks,aes,direct,late):
    allowed=set(stocks)
    def index(rows,start,end,source):
        out={}
        for r in rows:
            d,s=r["trade_date"],r["stock_id"]
            if (type(d) is not date or not start<=d<end or d.weekday()>=5
                or s not in allowed or r["market"]!="twse" or r["source"]!=source
                or (d,s) in out or b.early.exact_core(r) is None):
                raise ValueError("Invalid source row or duplicate")
            out[d,s]=r
        return out
    start22=date(2022,1,1)
    a=index(aes,b.depth.START,b.START,"TWSE_MI_INDEX_ALLBUT0999")
    w=index(direct,start22,b.START,"TWSE_STOCK_DAY")
    l=index(late,b.START,date(2026,12,1),"TWSE_STOCK_DAY")
    overlap=a.keys()&w.keys()
    conflicts=[k for k in overlap if b.early.exact_core(a[k])!=b.early.exact_core(w[k])]
    missing_2022_aes_in_direct=sum(k[0]>=start22 and k not in w for k in a)
    report={"aes_direct_overlap_rows":len(overlap),"aes_direct_conflicting_rows":len(conflicts),
        "aes_2022_rows_missing_from_direct":missing_2022_aes_in_direct,
        "new_2022_source_rows":len(w.keys()-a.keys()),"direct_2022_source_rows":len(w),
        "direct_2022_observed_days":len({k[0] for k in w}),
        "post_cutoff_rows_excluded":sum(k[0]>b.CUTOFF for k in l)}
    if conflicts or missing_2022_aes_in_direct:
        return report,None,None
    groups=defaultdict(list)
    for k,r in {**w,**a,**l}.items():
        if k[0]<=b.CUTOFF:groups[k[1]].append(r)
    calendar={r["trade_date"] for rows in groups.values() for r in rows}
    return report,groups,calendar

def compute(stocks,aes,direct,late,prior):
    report,groups,calendar=merge_warmup(stocks,aes,direct,late)
    report.update(scope="OWNER_2022_WARMUP_RECONCILED_FACTOR_RESEARCH",schema_version=1,
        sample_stock_count=len(stocks),frozen_sample_sha256=b.m.fingerprint(list(stocks)),
        official_market_calendar_independently_proven=False,historical_publication_vintage_verified=False,
        current_roster_not_historical_pit=True,selection_conditioned_on_later_availability=True,
        forward_labels_created=False,corporate_actions_adjusted=False,model_trained=False,
        production_neon_reads=0,production_neon_writes=0,line_messages_sent=0,
        paid_upgrade_requested=False,model_release="BLOCKED")
    if groups is None:
        report["status"]="SOURCE_PARITY_BLOCKED"
        return report,[]
    if report["direct_2022_observed_days"]!=246:
        report["status"]="OBSERVED_2022_CALENDAR_COUNT_BLOCKED"
        return report,[]
    signals=q.monthly_signal_schedule(calendar)
    if [d.isoformat() for d in q.signal_schedule(calendar)]!=b.m.DATES:
        raise ValueError("Quarterly schedule drift")
    r,rows=q.calculate_cohort(stocks,groups,{},calendar,signals,market="twse",schedule="monthly",reference_calendar=calendar)
    previous={(x["stock_id"],x["signal_date"]):x for x in prior}
    compare=Counter()
    for x in rows:
        if x["signal_date"] not in b.m.DATES:continue
        old=previous.get((x["stock_id"],x["signal_date"]))
        compare["comparable"]+=int(old is not None)
        compare["vector_equal"]+=int(old is not None and old["feature_vector"]==x["feature_vector"])
        compare["exact_row_equal"]+=int(old==x)
    complete=[x["signal_date"] for x in r["signal_date_outcomes"] if x["accepted"]==len(stocks)]
    mature=[d for d in complete if d<b.CUTOFF.isoformat() and sum(x>date.fromisoformat(d) for x in calendar)>=6]
    potential=max(0,len(mature)-folds.MIN_TRAIN_DATES)
    report.update(status="FACTOR_RESEARCH_COMPUTED",requested_signal_dates=len(signals),
        accepted_feature_rows=len(rows),accepted_feature_values=len(rows)*len(b.m.FEATURES),
        signal_date_outcomes=r["signal_date_outcomes"],whole_five_stock_signal_dates=len(complete),
        upper_bound_mature_whole_cohort_dates=len(mature),upper_bound_test_windows=potential,
        date_count_capacity_gate_only=potential>=folds.MIN_TEST_WINDOWS,
        quarterly_comparisons=dict(compare),private_feature_rows_sha256=b.m.fingerprint(rows),
        feature_version=b.m.VERSION,feature_names=b.m.FEATURES,
        observed_market_dates=len(calendar),exact_prior_quarterly_panel_reproduced=False)
    return report,rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("panel","cache-dir","archive-2021","archive-2022","key-vault","out"):
        p.add_argument("--"+key,required=True)
    a=p.parse_args();stage="PANEL"
    try:
        payload,_=b.m.read_panel(b.m.private_path(a.panel,existing=True))
        stocks=b.five.select(b.chip.verify_input(payload))
        if b.m.fingerprint(list(stocks))!=b.SAMPLE_HASH:raise ValueError("Frozen roster changed")
        out=b.m.private_path(a.out,existing=False)
        stage="CACHE"
        late,late_hash=b.load_late(stocks,a.cache_dir)
        if late_hash!="40972bcffec77b8230f8aaea0016b4fc3797a61d572ae61725583fd39a5d6abb":
            raise ValueError("Prior late source bytes changed")
        direct,warmup_hash=load_warmup(stocks,a.cache_dir)
        stage="AES"
        p21=b.depth._private_archives(a.archive_2021);p22=b.depth._private_archives(a.archive_2022)
        if set(p21)&set(p22):raise ValueError("Overlapping archives")
        key=b.depth.resolve_archive_key(vault_path=Path(a.key_vault),env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
        a21,d21=b.early.archive_bars(p21,key=key,start=b.depth.START,end=date(2022,1,1),expected_days=28,eligible=set(stocks))
        a22,d22=b.early.archive_bars(p22,key=key,start=date(2022,1,1),end=b.START,expected_days=162,eligible=set(stocks))
        if len(a21)+len(a22)!=950:raise ValueError("Early row count changed")
        stage="RECONCILIATION"
        prior=[r for r in payload["private_feature_rows"] if r["market"]=="twse" and r["stock_id"] in stocks]
        report,rows=compute(stocks,a21+a22,direct,late,prior)
        report.update(warmup_response_hashes_sha256=warmup_hash,late_response_hashes_sha256=late_hash,
                      authenticated_early_archive_days=len(d21)+len(d22),warmup_cache_months=60)
        stage="OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump({"summary":report,"sample_stock_ids":stocks,"private_feature_rows":rows},f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(report,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon or LINE actions") from None

if __name__=="__main__":
    main()
