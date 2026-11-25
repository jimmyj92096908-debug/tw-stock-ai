"""Owner-only 2021/22 economic source parity and raw factor pilot, no DB writes.

One current-listed snapshot; fixed historical receipts; no prices or individual
features in the public-facing summary. A stock with conflicting or malformed
OHLCV, or incomplete final 240 observed market days, is quarantined.
This is NOT corporate-action-adjusted or historical PIT model validation.
"""
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
import argparse
import json
import os
from pathlib import Path

from scripts import twse_owner_five_year_source_depth_readonly as depth
from scripts import twse_private_history_receipt_overlay_offline as overlay
from src.raw_factor_feature_bridge import build_research_features, FEATURE_NAMES

CUTOFF = date(2022,12,30)
FIELDS = ("open","high","low","close","volume")
COLS = ("trade_date","stock_id","source",*FIELDS)
EARLY_BARS_SQL = depth.ELIGIBLE + """
 SELECT p.trade_date,p.stock_id,p.source,p.open,p.high,p.low,p.close,p.volume
 """ + depth.BASE + " ORDER BY p.trade_date,p.stock_id LIMIT 180001"


def capture(url):
    import psycopg
    if not isinstance(url,str) or not url.startswith(("postgres://","postgresql://")):
        raise ValueError("Protected local connection required")
    with psycopg.connect(url,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='90s'")
            cur.execute(depth.ELIGIBLE_SQL)
            roster=[r[0] for r in cur.fetchall()]
            cur.execute(EARLY_BARS_SQL,(depth.START,depth.EARLY_END))
            raw=cur.fetchall()
            if len(raw)>180000:
                raise ValueError("Early source bound exceeded")
            cur.execute(depth.LATE_SQL,(depth.EARLY_END,depth.END))
            late=cur.fetchall()
        conn.rollback()
    return roster,[dict(zip(COLS,row),market="twse") for row in raw],late


def archive_bars(paths, *, key, start, end, expected_days, eligible):
    before={p:depth.digest(p) for p in paths}
    proof=depth.authenticated_archive_days(paths,hex_key=key,start=start,end=end)
    if proof["full_file_integrity_verified"] is not True or len(proof["days"])!=expected_days:
        raise ValueError("Authenticated archive calendar changed")
    rows=[];seen=set();total=0
    for p in paths:
        def collect(r):
            nonlocal total
            total+=1
            if total>600000:
                raise ValueError("Archive replay bound exceeded")
            d,s=r["trade_date"],r["stock_id"]
            if start<=d<end and s in eligible:
                if (d,s) in seen:
                    raise ValueError("Duplicate archive key")
                seen.add((d,s))
                rows.append({k:r[k] for k in COLS+("market",)})
        proof_file=depth.verify_archive(p,hex_key=key,on_verified_row=collect)
        if proof_file["archive_integrity_verified"] is not True:
            raise ValueError("Archive authentication failed")
    if before!={p:depth.digest(p) for p in paths}:
        raise ValueError("Archive bytes changed")
    return rows,proof["days"]


def exact_core(r):
    p=tuple(r.get(k) for k in FIELDS[:4])
    v=r.get("volume")
    if (any(type(x) is not Decimal or not x.is_finite() or x<=0 for x in p)
        or not p[2]<=min(p[0],p[3])<=max(p[0],p[3])<=p[1]
        or type(v) is not int or v<0):
        return None
    return (*p,v)


def factor_pilot(roster, local, neon, calendar):
    """Strict source-key partition, exact Decimal parity, raw final-day pilot."""
    if (not roster or len(roster)>1092 or len(set(roster))!=len(roster)
        or any(type(s) is not str or len(s)!=4 or not s.isascii() or not s.isdigit() or s=="1589" for s in roster)
        or len(calendar)!=274 or len(set(calendar))!=274
        or any(type(d) is not date or not depth.START<=d<=CUTOFF or d.weekday()>=5 for d in calendar)
        or max(calendar)!=CUTOFF or len(local)>600000 or len(neon)>180000):
        raise ValueError("Invalid bounded source pilot scope")
    allowed=set(roster);days=set(calendar);required=set(sorted(days)[-240:])
    def index(rows,aes):
        result={}
        for r in rows:
            d,s=r.get("trade_date"),r.get("stock_id")
            if (type(d) is not date or d not in days or s not in allowed
                or r.get("market")!="twse" or r.get("source") not in (("TWSE_MI_INDEX_ALLBUT0999",) if aes else depth.SOURCES)
                or (d,s) in result):
                raise ValueError("Duplicate/foreign/unverified raw key")
            result[d,s]=r
        return result
    a=index(local,True);b=index(neon,False)
    overlap=a.keys()&b.keys()
    invalid_a={k for k,r in a.items() if exact_core(r) is None}
    if invalid_a:
        raise ValueError("Authenticated archive core OHLCV invalid")
    invalid_b={k for k,r in b.items() if exact_core(r) is None}
    conflicts={k for k in overlap if k not in invalid_b and exact_core(a[k])!=exact_core(b[k])}
    exact=overlap-invalid_b-conflicts
    bad_invalid={s for d,s in invalid_b}
    bad_conflict={s for d,s in conflicts}
    groups=defaultdict(list)
    for k in a.keys()|b.keys():
        # No source preference may hide a conflict: affected issuer is excluded.
        groups[k[1]].append(a[k] if k in a else b[k])
    reasons=Counter(); accepted=0
    for sid in sorted(roster):
        rows=sorted(groups[sid],key=lambda r:r["trade_date"])
        if sid in bad_invalid:
            reasons["invalid_neon_ohlcv"]+=1
        elif sid in bad_conflict:
            reasons["overlap_ohlcv_conflict"]+=1
        elif not required<={r["trade_date"] for r in rows}:
            reasons["incomplete_last_240_observed_market_dates"]+=1
        else:
            try:
                report=build_research_features(rows,stock_id=sid,cutoff=CUTOFF,signal_dates=[CUTOFF],market="twse")
            except (ValueError,ArithmeticError,RuntimeError):
                reasons["raw_factor_computation_rejected"]+=1
                continue
            if report["included_signals"]!=1 or len(report["signals"][0]["feature_vector"])!=len(FEATURE_NAMES):
                reasons["raw_factor_computation_rejected"]+=1
                continue
            accepted+=1
    if accepted+sum(reasons.values())!=len(roster) or len(exact)+len(conflicts)+len(overlap&invalid_b)!=len(overlap):
        raise RuntimeError("Source partition conservation failed")
    return {"schema_version":1,"scope":"OWNER_2021_22_TWSE_CURRENT_COHORT_ECONOMIC_PARITY_RAW_FACTOR_PILOT",
        "cutoff":CUTOFF.isoformat(),"eligible_stocks":len(roster),"observed_market_source_days":len(days),
        "aes_source_keys":len(a),"neon_source_keys":len(b),"deduplicated_source_keys":len(a.keys()|b.keys()),
        "overlap_source_keys":len(overlap),"exact_core_ohlcv_overlap_keys":len(exact),
        "conflicting_valid_ohlcv_overlap_keys":len(conflicts),"invalid_neon_overlap_keys":len(overlap&invalid_b),
        "invalid_neon_ohlcv_keys":len(invalid_b),"issuers_with_overlap_conflict":len(bad_conflict),
        "issuers_with_invalid_neon_ohlcv":len(bad_invalid),
        "raw_factor_pilot_accepted_stocks":accepted,"excluded_stocks_by_primary_reason":dict(sorted(reasons.items())),
        "raw_feature_count":len(FEATURE_NAMES),"raw_features_computed_for_one_fixed_signal_only":True,
        "full_five_year_factor_panel_recomputed":False,"official_market_calendar_independently_proven":False,
        "historical_pit_total_return_verified":False,"corporate_actions_adjusted":False,
        "production_neon_writes":0,"line_messages_sent":0,"model_release":"BLOCKED"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("archive-2021","archive-2022","key-vault","union-2021","density-2022","neon-five-year","out"):
        p.add_argument("--"+arg,required=True)
    args=p.parse_args()
    stage="RECEIPTS"
    try:
        inputs=[overlay.private_path(x) for x in (args.union_2021,args.density_2022,args.neon_five_year)]
        out=depth._private_file(args.out,should_exist=False)
        if len(set([*inputs,out]))!=4:
            raise ValueError("Distinct private files required")
        loaded=[overlay.load(x) for x in inputs]
        r21,r22,base=[x[0] for x in loaded]
        expected=overlay.reconcile(r21,r22,base)
        stage="NEON_READONLY"
        roster,neon,late=capture(os.environ.get("DATABASE_URL",""))
        stage="ARCHIVE_AUTHENTICATION"
        p21=depth._private_archives(args.archive_2021)
        p22=depth._private_archives(args.archive_2022)
        if set(p21)&set(p22):
            raise ValueError("Archive directories overlap")
        key=depth.resolve_archive_key(vault_path=Path(args.key_vault),env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
        a21,d21=archive_bars(p21,key=key,start=depth.START,end=date(2022,1,1),expected_days=28,eligible=set(roster))
        a22,d22=archive_bars(p22,key=key,start=date(2022,1,1),end=depth.EARLY_END,expected_days=162,eligible=set(roster))
        stage="SOURCE_DEPTH_RECONCILIATION"
        def keys(rows): return {(r["trade_date"],r["stock_id"]) for r in rows}
        fresh=depth.depth_summary(roster,[(r["trade_date"],r["stock_id"],r["source"]) for r in neon],late,
            keys(a21),keys(a22),d21,d22,expected=expected,baseline=base,report21=r21,report22=r22)
        stage="ECONOMIC_PARITY_AND_RAW_PILOT"
        calendar={r["trade_date"] for r in a21+a22+neon}
        result=factor_pilot(roster,a21+a22,neon,calendar)
        if result["deduplicated_source_keys"]!=expected["twse_2021_2022_observed_keys_sum"]:
            raise ValueError("Early union count changed")
        result["five_year_replayed_source_keys"]=fresh["merged_source_keys"]
        result["input_receipt_sha256"]=[x[1] for x in loaded]
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump(result,f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(result,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon writes or LINE action") from None


if __name__=="__main__":
    main()
