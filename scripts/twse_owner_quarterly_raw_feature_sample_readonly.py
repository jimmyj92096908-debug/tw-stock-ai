"""Bounded owner-local five-year TWSE quarterly raw-feature research sample.

Fixed deterministic current-roster sample; every feature uses its own truncated
prefix. No historical PIT membership, adjusted returns, or release claims.
Only aggregate status is printed; private feature rows stay outside Git.
"""
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
import argparse
import json
import math
import os
from pathlib import Path

from scripts import twse_owner_five_year_source_depth_readonly as depth
from scripts import twse_owner_early_economic_factor_pilot_readonly as early
from scripts import twse_private_history_receipt_overlay_offline as overlay
from src.raw_factor_feature_bridge import build_research_features, FEATURE_NAMES, VERSION

SAMPLE_SIZE=20
SALT="twse-owner-quarterly-20261124-v1"
MAX_LATE_ROWS=32000
CALENDAR_SQL=depth.ELIGIBLE+"SELECT p.trade_date,COUNT(*)::int "+depth.BASE+" GROUP BY 1 ORDER BY 1 LIMIT 1601"
SAMPLE_SQL=depth.ELIGIBLE+"SELECT p.trade_date,p.stock_id,p.source,p.open,p.high,p.low,p.close,p.volume "+depth.BASE+" AND p.stock_id=ANY(%s) ORDER BY p.stock_id,p.trade_date LIMIT 32001"


def sample_roster(roster):
    if (not isinstance(roster,(list,tuple)) or not 20<=len(roster)<=1092
        or len(set(roster))!=len(roster)
        or any(type(s) is not str or len(s)!=4 or not s.isascii() or not s.isdigit() or s=="1589" for s in roster)):
        raise ValueError("Invalid current roster")
    return sorted(sorted(roster,key=lambda s:sha256((SALT+":"+s).encode()).digest())[:SAMPLE_SIZE])


def capture(url):
    import psycopg
    if not isinstance(url,str) or not url.startswith(("postgres://","postgresql://")):
        raise ValueError("Protected local URL required")
    with psycopg.connect(url,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='90s'")
            cur.execute(depth.ELIGIBLE_SQL)
            roster=[r[0] for r in cur.fetchall()]
            if len(roster)!=1092:
                raise ValueError("Current owner roster drifted")
            selected=sample_roster(roster)
            cur.execute(early.EARLY_BARS_SQL,(depth.START,depth.EARLY_END))
            first=cur.fetchall()
            if len(first)>180000:
                raise ValueError("Early read bound exceeded")
            cur.execute(depth.LATE_SQL,(depth.EARLY_END,depth.END))
            counts=cur.fetchall()
            if len(counts)>6000:
                raise ValueError("Late count bound exceeded")
            cur.execute(CALENDAR_SQL,(depth.EARLY_END,depth.END))
            calendar=cur.fetchall()
            if len(calendar)>1600:
                raise ValueError("Calendar bound exceeded")
            cur.execute(SAMPLE_SQL,(depth.EARLY_END,depth.END,selected))
            last=cur.fetchall()
            if len(last)>MAX_LATE_ROWS:
                raise ValueError("Sample read bound exceeded")
        conn.rollback()
    return roster,[dict(zip(early.COLS,r),market="twse") for r in first],counts,calendar,[dict(zip(early.COLS,r),market="twse") for r in last]


def validate_calendar(rows,baseline,roster):
    days=set();year_counts=Counter();year_days=Counter();dense=Counter()
    for d,n in rows:
        if (type(d) is not date or not depth.EARLY_END<=d<depth.END
            or d.weekday()>=5 or d in days or type(n) is not int or not 1<=n<=len(roster)):
            raise ValueError("Invalid observed late calendar")
        days.add(d);year_counts[d.year]+=n;year_days[d.year]+=1;dense[d.year]+=n>=500
    previous=baseline["market"]["twse"]["yearly_neon_source_observations"]
    for r in previous:
        y=r["year"]
        if y>=2023 and (year_counts[y],year_days[y],dense[y])!=(
            r["neon_stored_valid_source_stock_bars"],r["days_with_any_neon_eligible_source_bars"],
            r["days_with_at_least_500_eligible_source_bars"]):
            raise ValueError("Late observed calendar baseline drifted")
    return days


def signal_schedule(calendar):
    quarters={}
    for d in sorted(calendar):
        if d>=depth.EARLY_END:
            quarters[d.year,(d.month-1)//3]=d
    expected={(y,q) for y in range(2023,2027) for q in range(4)}
    if set(quarters)!=expected or early.CUTOFF not in calendar:
        raise ValueError("Expected 16 observed late quarters and early anchor")
    return [early.CUTOFF]+[quarters[k] for k in sorted(quarters)]


def merge_sources(roster,local,neon,late,calendar,counts):
    """Recheck all early parity; validate bounded late sample key counts."""
    allowed=set(roster);selected=set(sample_roster(roster));days=set(calendar)
    def index(rows,permitted,start,end,aes=False):
        result={}
        for r in rows:
            d,s=r.get("trade_date"),r.get("stock_id")
            if (type(d) is not date or not start<=d<end or d not in days or s not in permitted
                or r.get("market")!="twse" or r.get("source") not in (("TWSE_MI_INDEX_ALLBUT0999",) if aes else depth.SOURCES)
                or (d,s) in result):
                raise ValueError("Duplicate/foreign/unverified source key")
            result[d,s]=r
        return result
    a=index(local,allowed,depth.START,depth.EARLY_END,True)
    b=index(neon,allowed,depth.START,depth.EARLY_END)
    c=index(late,selected,depth.EARLY_END,depth.END)
    overlap=a.keys()&b.keys()
    if any(early.exact_core(r) is None for r in a.values()) or any(early.exact_core(r) is None for r in b.values()):
        raise ValueError("Prior early economic proof changed")
    if any(early.exact_core(a[k])!=early.exact_core(b[k]) for k in overlap):
        raise ValueError("Prior early overlap parity changed")
    observed=Counter((s,d.year) for d,s in c)
    expected={(s,y):n for s,y,n,distinct in counts if s in selected}
    if dict(observed)!=expected:
        raise ValueError("Selected issuer annual source counts changed")
    bad={s for (d,s),r in c.items() if early.exact_core(r) is None}
    groups=defaultdict(list)
    for k in a.keys()|b.keys():
        if k[1] in selected:
            groups[k[1]].append(a[k] if k in a else b[k])
    for k,r in c.items():
        groups[k[1]].append(r)
    return groups,bad,len(overlap),len(a.keys()|b.keys())


def calculate_sample(selected,groups,bad,calendar,signals):
    """Recompute using an independent prefix per signal; no forward labels."""
    if signals!=signal_schedule(calendar) or len(selected)!=SAMPLE_SIZE or len(set(selected))!=SAMPLE_SIZE:
        raise ValueError("Fixed sample schedule required")
    dates=sorted(calendar);positions={d:i for i,d in enumerate(dates)}
    outcomes={d:Counter() for d in signals};features=[]
    for sid in sorted(selected):
        rows=sorted(groups.get(sid,[]),key=lambda r:r["trade_date"])
        if len(rows)>1600 or len({r["trade_date"] for r in rows})!=len(rows):
            raise ValueError("Invalid per-stock bounded source")
        observed={r["trade_date"] for r in rows}
        for day in signals:
            i=positions[day]
            if sid in bad:
                outcomes[day]["issuer_invalid_late_ohlcv"]+=1
                continue
            if i+1<240 or not set(dates[i-239:i+1])<=observed:
                outcomes[day]["incomplete_240_observed_market_dates"]+=1
                continue
            prefix=[r for r in rows if r["trade_date"]<=day]
            try:
                r=build_research_features(prefix,stock_id=sid,cutoff=day,signal_dates=[day],market="twse")
            except (ValueError,RuntimeError,ArithmeticError):
                outcomes[day]["raw_factor_rejected"]+=1
                continue
            if r["included_signals"]!=1:
                outcomes[day]["raw_factor_rejected"]+=1
                continue
            f=r["signals"][0]
            v=f["feature_vector"]
            if (f["as_of_date"]!=day.isoformat() or len(v)!=len(FEATURE_NAMES)
                or not all(type(x) in (int,float) and math.isfinite(x) for x in v)
                or r["raw_last_date"]!=day.isoformat() or f["label_or_forward_price_observed"] is not False):
                raise RuntimeError("Unexpected factor engine output")
            features.append({"stock_id":sid,"market":"twse","signal_date":day.isoformat(),
                "feature_vector":v,"prefix_source_rows":len(prefix),
                "prefix_source_sha256":r["raw_source_fingerprint_sha256"]})
            outcomes[day]["accepted"]+=1
    if any(sum(v.values())!=len(selected) for v in outcomes.values()):
        raise RuntimeError("Signal partition mismatch")
    features.sort(key=lambda r:(r["signal_date"],r["stock_id"]))
    summary={"schema_version":1,"scope":"OWNER_TWSE_FIXED_FIVE_YEAR_QUARTERLY_RAW_FEATURE_SAMPLE",
        "sample_size":len(selected),"requested_signal_dates":len(signals),
        "signal_date_outcomes":[{"signal_date":d.isoformat(),"accepted":outcomes[d]["accepted"],
            "excluded":{k:v for k,v in sorted(outcomes[d].items()) if k!="accepted"}} for d in signals],
        "accepted_feature_rows":len(features),"accepted_feature_values":len(features)*len(FEATURE_NAMES),
        "feature_version":VERSION,"feature_names":list(FEATURE_NAMES),
        "sample_selection":"fixed_hash_current_roster_not_historical_pit",
        "prefix_only_feature_computation":True,"forward_labels_created":False,
        "full_five_year_factor_panel_recomputed":False,"corporate_actions_adjusted":False,
        "historical_pit_total_return_verified":False,"production_neon_writes":0,
        "line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}
    return summary,features


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
        roster,neon,counts,late_calendar,late=capture(os.environ.get("DATABASE_URL",""))
        stage="ARCHIVE_AUTHENTICATION"
        p21=depth._private_archives(args.archive_2021);p22=depth._private_archives(args.archive_2022)
        if set(p21)&set(p22):
            raise ValueError("Archive directories overlap")
        key=depth.resolve_archive_key(vault_path=Path(args.key_vault),env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
        a21,d21=early.archive_bars(p21,key=key,start=depth.START,end=date(2022,1,1),expected_days=28,eligible=set(roster))
        a22,d22=early.archive_bars(p22,key=key,start=date(2022,1,1),end=depth.EARLY_END,expected_days=162,eligible=set(roster))
        stage="SOURCE_DEPTH_RECONCILIATION"
        def keys(rows): return {(r["trade_date"],r["stock_id"]) for r in rows}
        fresh=depth.depth_summary(roster,[(r["trade_date"],r["stock_id"],r["source"]) for r in neon],counts,
            keys(a21),keys(a22),d21,d22,expected=expected,baseline=base,report21=r21,report22=r22)
        calendar={r["trade_date"] for r in a21+a22+neon}|validate_calendar(late_calendar,base,roster)
        stage="ECONOMIC_PARITY"
        groups,bad,overlap,union=merge_sources(roster,a21+a22,neon,late,calendar,counts)
        if (overlap,union)!=(3767,259395):
            raise ValueError("Previously verified early parity counts changed")
        stage="QUARTERLY_FEATURES"
        selected=sample_roster(roster)
        summary,features=calculate_sample(selected,groups,bad,calendar,signal_schedule(calendar))
        summary.update({"five_year_replayed_source_keys":fresh["merged_source_keys"],
            "early_overlap_exact_keys":overlap,"sample_late_neon_raw_rows":len(late),
            "input_receipt_sha256":[x[1] for x in loaded],
            "private_feature_rows_sha256":sha256(json.dumps(features,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()})
        if not features:
            raise ValueError("No usable research feature rows")
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump({"summary":summary,"sample_stock_ids":selected,"private_feature_rows":features},f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(summary,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon writes or LINE action") from None


if __name__=="__main__":
    main()
