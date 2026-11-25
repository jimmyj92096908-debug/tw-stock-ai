"""Owner-local AES + direct STOCK_DAY source bridge; no DB or network.
Early AES is incomplete (190 source dates, vs prior 274 observed days).
Compute only after 240 late observed sessions; compare original quarterly
vectors and exact row hashes separately. Never forge replay or label proof.
"""
import argparse
from collections import Counter,defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from scripts import owner_twse_direct_monthly_five_stock as five
from scripts import owner_twse_direct_monthly_source_canary as c
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m
from scripts import owner_twse_five_stock_cache_audit_offline as audit
from scripts import owner_quarterly_chip_vintage_coverage_readonly as chip
from scripts import twse_owner_early_economic_factor_pilot_readonly as early
from scripts import twse_owner_five_year_source_depth_readonly as depth
from src.raw_factor_feature_bridge import build_research_features

CUTOFF=date(2026,11,20)
START=date(2023,1,1)
SAMPLE_HASH="2f84991de7f5be5a5888b4c60adce05a577338c028d3f3143b3952bcf017148f"

def load_late(stocks,directory):
    check=audit.audit(stocks,directory)
    if (check["valid_months"]!=235 or check["valid_source_rows"]!=4694
        or check["frozen_sample_sha256"]!=SAMPLE_HASH):
        raise ValueError("Frozen 235-month owner cache changed")
    directory=c.private_dir(directory)
    rows=[];digests=[]
    for year in range(2023,2027):
        for quarter in range(1,5):
            q=five.queue_for(stocks,year,quarter)
            for stock,month in q:
                stem=f"twse-stock-day-{stock}-{month}"
                p=directory/(stem+".response.json")
                meta=directory/(stem+".receipt.json")
                if p.is_symlink() or meta.is_symlink():
                    raise ValueError("No symlink")
                with p.open("rb") as f: raw=f.read(c.LIMIT+1)
                with meta.open("rb") as f: receipt=json.loads(f.read(4097),object_pairs_hook=m.strict_object)
                bars=c.parse_month(raw,stock,month,queue=q)
                digest=sha256(raw).hexdigest()
                if (receipt.get("response_sha256")!=digest or receipt.get("row_count")!=len(bars)
                    or receipt.get("stock_id")!=stock or receipt.get("month")!=month
                    or receipt.get("endpoint")!=c.ENDPOINT
                    or receipt.get("scope")!="OWNER_TWSE_STOCK_DAY_DIRECT_CAPTURE"):
                    raise ValueError("Source changed during replay")
                digests.append([stock,month,digest])
                for r in bars:
                    row=dict(r,trade_date=date.fromisoformat(r["trade_date"]))
                    for k in ("open","high","low","close"): row[k]=Decimal(row[k])
                    rows.append(row)
    if len(rows)!=4694:
        raise ValueError("Source count changed during replay")
    return rows,m.fingerprint(digests)

def compute(stocks,late,old,prior):
    allowed=set(stocks)
    groups=defaultdict(list);early_groups=defaultdict(list)
    seen=set();after=0
    for row,is_early in [(r,True) for r in old]+[(r,False) for r in late]:
        sid=row["stock_id"];d=row["trade_date"]
        if (sid not in allowed or row["market"]!="twse" or type(d) is not date
            or d.weekday()>=5 or (sid,d) in seen or early.exact_core(row) is None
            or (is_early and not depth.START<=d<START)
            or (not is_early and not START<=d<date(2026,12,1))
            or row["source"]!=("TWSE_MI_INDEX_ALLBUT0999" if is_early else "TWSE_STOCK_DAY")):
            raise ValueError("Invalid or duplicate source row")
        seen.add((sid,d))
        if d>CUTOFF:
            after+=1;continue
        (early_groups if is_early else groups)[sid].append(row)
    calendar=sorted({r["trade_date"] for rows in groups.values() for r in rows})
    month_end={}
    for d in calendar:month_end[d.year,d.month]=d
    expected=[(y,j) for y in range(2023,2027) for j in range(1,12 if y==2026 else 13)]
    if sorted(month_end)!=expected or month_end[2026,11]!=CUTOFF:
        raise ValueError("Incomplete observed late month schedule")
    dates=[month_end[k] for k in expected]
    if not set(m.DATES[1:])<=set(d.isoformat() for d in dates):
        raise ValueError("Late quarterly signal calendar changed")
    positions={d:i for i,d in enumerate(calendar)}
    previous={(r["stock_id"],r["signal_date"]):r for r in prior}
    outcomes=[];features=[];comparisons=Counter()
    for d in dates:
        count=Counter()
        for sid in stocks:
            i=positions[d]
            prefix=sorted((r for r in groups[sid] if r["trade_date"]<=d),key=lambda r:r["trade_date"])
            observed={r["trade_date"] for r in prefix}
            if i+1<240 or not set(calendar[i-239:i+1])<=observed:
                count["incomplete_240_late_observed_dates"]+=1;continue
            joined=sorted(early_groups[sid]+prefix,key=lambda r:r["trade_date"])
            a=build_research_features(prefix,stock_id=sid,cutoff=d,signal_dates=[d],market="twse")
            b=build_research_features(joined,stock_id=sid,cutoff=d,signal_dates=[d],market="twse")
            if a["included_signals"]!=1 or b["included_signals"]!=1:
                count["factor_rejected"]+=1;continue
            x=a["signals"][0]["feature_vector"];y=b["signals"][0]["feature_vector"]
            count["accepted"]+=1
            comparisons["late_vs_aes_join_vector_equal"]+=int(x==y)
            item={"stock_id":sid,"market":"twse","signal_date":d.isoformat(),
                "feature_vector":y,"prefix_source_rows":len(joined),
                "prefix_source_sha256":b["raw_source_fingerprint_sha256"]}
            features.append(item)
            if d.isoformat() in m.DATES:
                original=previous.get((sid,d.isoformat()))
                comparisons["quarterly_anchor_comparable"]+=int(original is not None)
                comparisons["quarterly_vector_equal"]+=int(original is not None and original["feature_vector"]==y)
                comparisons["quarterly_exact_row_equal"]+=int(original==item)
        outcomes.append({"signal_date":d.isoformat(),"accepted":count["accepted"],
                         "excluded":{k:v for k,v in count.items() if k!="accepted"}})
    if any(o["accepted"]+sum(o["excluded"].values())!=len(stocks) for o in outcomes):
        raise RuntimeError("Cohort count conservation failed")
    report={"scope":"OWNER_FIVE_STOCK_AES_DIRECT_SOURCE_FACTOR_RESEARCH",
        "schema_version":1,"sample_stock_count":len(stocks),"frozen_sample_sha256":m.fingerprint(list(stocks)),
        "early_aes_sample_rows":len(old),"late_cache_source_rows":len(late),
        "excluded_after_cutoff_rows":after,"late_observed_market_dates":len(calendar),
        "requested_signal_dates":len(dates),"accepted_feature_rows":len(features),
        "accepted_feature_values":len(features)*12,"whole_five_stock_signal_dates":sum(o["accepted"]==len(stocks) for o in outcomes),
        "signal_date_outcomes":outcomes,"comparisons":dict(comparisons),
        "feature_version":m.VERSION,"feature_names":m.FEATURES,"private_feature_rows_sha256":m.fingerprint(features),
        "early_84_observed_market_dates_not_recovered_from_aes":84,
        "exact_prior_quarterly_panel_reproduced":False,"historical_publication_vintage_verified":False,
        "official_market_calendar_independently_proven":False,"forward_labels_created":False,
        "corporate_actions_adjusted":False,"model_trained":False,"production_neon_reads":0,
        "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}
    return report,features

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("panel","cache-dir","archive-2021","archive-2022","key-vault","out"):
        p.add_argument("--"+key,required=True)
    a=p.parse_args();stage="FROZEN_PANEL"
    try:
        payload,_=m.read_panel(m.private_path(a.panel,existing=True))
        stocks=five.select(chip.verify_input(payload))
        if m.fingerprint(list(stocks))!=SAMPLE_HASH:raise ValueError("Sample drift")
        out=m.private_path(a.out,existing=False)
        stage="LATE_CACHE"
        late,digest=load_late(stocks,a.cache_dir)
        stage="AES_AUTHENTICATION"
        p21=depth._private_archives(a.archive_2021);p22=depth._private_archives(a.archive_2022)
        if set(p21)&set(p22):raise ValueError("Overlapping archive folders")
        key=depth.resolve_archive_key(vault_path=Path(a.key_vault),env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
        old21,d21=early.archive_bars(p21,key=key,start=depth.START,end=START.replace(year=2022),expected_days=28,eligible=set(stocks))
        old22,d22=early.archive_bars(p22,key=key,start=START.replace(year=2022),end=START,expected_days=162,eligible=set(stocks))
        stage="FACTOR_RESEARCH"
        prior=[r for r in payload["private_feature_rows"] if r["market"]=="twse" and r["stock_id"] in stocks]
        report,features=compute(stocks,late,old21+old22,prior)
        report.update(authenticated_early_archive_days=len(d21)+len(d22),late_source_response_hashes_sha256=digest)
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump({"summary":report,"sample_stock_ids":stocks,"private_feature_rows":features},f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(report,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; zero Neon or LINE actions") from None

if __name__=="__main__":
    main()
