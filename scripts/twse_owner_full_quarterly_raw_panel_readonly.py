"""Owner-local all-current-listed TWSE quarterly panel, bounded read-only snapshot.

Raw 12-factor research only. One Neon snapshot, raw late rows buffered as
tuples, then local calculation in bounded issuer batches. No raw-price files,
no public issuer IDs/vectors, no production writes. All output stays private.
"""
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path

from scripts import twse_owner_quarterly_raw_feature_sample_readonly as q
from scripts import twse_owner_five_year_source_depth_readonly as depth
from scripts import twse_owner_early_economic_factor_pilot_readonly as early
from scripts import twse_private_history_receipt_overlay_offline as overlay
from src.raw_factor_feature_bridge import FEATURE_NAMES, VERSION

BATCH=40
MAX_LATE_ROWS=1_000_000
EXPECTED_SAMPLE_HASH="d287cbfcd2a5bc02068515b6c8a73b501ee47057f3af0f5a38f8595268590eef"
LATE_BATCH_SQL=depth.ELIGIBLE+"SELECT p.trade_date,p.stock_id,p.source,p.open,p.high,p.low,p.close,p.volume "+depth.BASE+" AND p.stock_id=ANY(%s) ORDER BY p.stock_id,p.trade_date LIMIT 64001"


def fingerprint(rows):
    return sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def batches(roster):
    roster=sorted(roster)
    return [roster[i:i+BATCH] for i in range(0,len(roster),BATCH)]


def read_budget(counts,expected):
    n=sum(r[2] for r in counts)
    if not 0<n<=MAX_LATE_ROWS or n!=expected:
        raise ValueError("Late read budget or prior annual count mismatch")
    return n


def capture(url,expected_late):
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
                raise ValueError("Official roster drifted")
            q.sample_roster(roster)
            cur.execute(depth.LATE_SQL,(depth.EARLY_END,depth.END))
            counts=cur.fetchall()
            if len(counts)>6000:
                raise ValueError("Late count bound exceeded")
            budget=read_budget(counts,expected_late)
            cur.execute(q.CALENDAR_SQL,(depth.EARLY_END,depth.END))
            calendar=cur.fetchall()
            if len(calendar)>1600:
                raise ValueError("Calendar bound exceeded")
            cur.execute(early.EARLY_BARS_SQL,(depth.START,depth.EARLY_END))
            first=cur.fetchall()
            if len(first)>180000:
                raise ValueError("Early row bound exceeded")
            late=defaultdict(list);total=0
            for batch in batches(roster):
                cur.execute(LATE_BATCH_SQL,(depth.EARLY_END,depth.END,batch))
                rows=cur.fetchall()
                if len(rows)>64000:
                    raise ValueError("Batch row bound exceeded")
                allowed=set(batch)
                for r in rows:
                    if r[1] not in allowed:
                        raise ValueError("Foreign batch stock")
                    late[r[1]].append(r)
                total+=len(rows)
                if total>budget:
                    raise ValueError("Read row budget exceeded")
            if total!=budget:
                raise ValueError("Late source count mismatch")
        conn.rollback()
    return roster,[dict(zip(early.COLS,r),market="twse") for r in first],counts,calendar,late


def prepare_early(roster,local,neon,calendar):
    allowed=set(roster)
    def index(rows,aes):
        result={}
        for r in rows:
            d,s=r.get("trade_date"),r.get("stock_id")
            if (type(d) is not date or not depth.START<=d<depth.EARLY_END or d not in calendar
                or s not in allowed or r.get("market")!="twse"
                or r.get("source") not in (("TWSE_MI_INDEX_ALLBUT0999",) if aes else depth.SOURCES)
                or (d,s) in result or early.exact_core(r) is None):
                raise ValueError("Early source identity or quality drift")
            result[d,s]=r
        return result
    a=index(local,True);b=index(neon,False)
    overlap=a.keys()&b.keys()
    if any(early.exact_core(a[k])!=early.exact_core(b[k]) for k in overlap):
        raise ValueError("Prior overlap parity drift")
    groups=defaultdict(list)
    for k in a.keys()|b.keys():
        groups[k[1]].append(a[k] if k in a else b[k])
    return groups,len(overlap),len(a.keys()|b.keys())


def process_batch(selected,early_groups,late,calendar,counts,signals):
    groups={s:list(early_groups.get(s,[])) for s in selected}
    bad={};observed=Counter()
    for sid in selected:
        seen=set()
        for raw in late.get(sid,[]):
            r=dict(zip(early.COLS,raw),market="twse")
            d,s=r["trade_date"],r["stock_id"]
            if (type(d) is not date or not depth.EARLY_END<=d<depth.END or d not in calendar
                or s!=sid or r["source"] not in depth.SOURCES or d in seen):
                raise ValueError("Late source identity or duplicate")
            seen.add(d);observed[s,d.year]+=1
            if early.exact_core(r) is None:
                bad[s]=min(d,bad.get(s,d))
            groups[s].append(r)
    expected={(s,y):n for s,y,n,distinct in counts if s in selected}
    if dict(observed)!=expected:
        raise ValueError("Batch annual key counts drifted")
    return q.calculate_cohort(selected,groups,bad,calendar,signals)


def panel(roster,early_groups,late,calendar,counts,signals):
    features=[];outcomes={d.isoformat():Counter() for d in signals};batch_reports=[]
    for batch in batches(roster):
        summary,rows=process_batch(batch,early_groups,late,calendar,counts,signals)
        for rec in summary["signal_date_outcomes"]:
            outcomes[rec["signal_date"]]["accepted"]+=rec["accepted"]
            outcomes[rec["signal_date"]].update(rec["excluded"])
        features.extend(rows)
        batch_reports.append({"issuer_count":len(batch),"accepted_rows":len(rows),"feature_rows_sha256":fingerprint(rows)})
    features.sort(key=lambda r:(r["signal_date"],r["stock_id"]))
    if (len({(r["signal_date"],r["stock_id"]) for r in features})!=len(features)
        or any(sum(v.values())!=len(roster) for v in outcomes.values())
        or sum(v["accepted"] for v in outcomes.values())!=len(features)
        or sum(b["issuer_count"] for b in batch_reports)!=len(roster)
        or sum(b["accepted_rows"] for b in batch_reports)!=len(features)):
        raise RuntimeError("Panel conservation failure")
    selected=set(q.sample_roster(roster))
    sample=[r for r in features if r["stock_id"] in selected]
    return {"schema_version":1,"scope":"OWNER_TWSE_ALL_CURRENT_LISTED_QUARTERLY_RAW_FEATURE_PANEL",
        "eligible_stocks":len(roster),"batch_count":len(batch_reports),
        "requested_signal_dates":len(signals),"candidate_stock_signal_pairs":len(roster)*len(signals),
        "accepted_feature_rows":len(features),"accepted_feature_values":len(features)*len(FEATURE_NAMES),
        "signal_date_outcomes":[{"signal_date":d.isoformat(),"accepted":outcomes[d.isoformat()]["accepted"],
            "excluded":{k:v for k,v in sorted(outcomes[d.isoformat()].items()) if k!="accepted"}} for d in signals],
        "feature_version":VERSION,"feature_names":list(FEATURE_NAMES),
        "sample_replay_feature_rows":len(sample),"sample_replay_sha256":fingerprint(sample),
        "private_feature_rows_sha256":fingerprint(features),
        "prefix_only_feature_computation":True,"current_roster_not_historical_pit":True,
        "official_market_calendar_independently_proven":False,
        "daily_full_five_year_factor_panel_recomputed":False,"forward_labels_created":False,
        "corporate_actions_adjusted":False,"historical_pit_total_return_verified":False,
        "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"},features,batch_reports


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("archive-2021","archive-2022","key-vault","union-2021","density-2022","neon-five-year","out"):
        p.add_argument("--"+arg,required=True)
    p.add_argument("--allow-bounded-full-read",action="store_true",required=True)
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
        expected_late=expected["twse_neon_only_baseline_stock_date_keys"]-552-83294
        stage="NEON_READONLY"
        roster,neon,counts,late_calendar,late=capture(os.environ.get("DATABASE_URL",""),expected_late)
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
        calendar={r["trade_date"] for r in a21+a22+neon}|q.validate_calendar(late_calendar,base,roster)
        groups,overlap,union=prepare_early(roster,a21+a22,neon,calendar)
        if (overlap,union)!=(3767,259395):
            raise ValueError("Early proof changed")
        stage="QUARTERLY_PANEL"
        summary,features,batch_reports=panel(roster,groups,late,calendar,counts,q.signal_schedule(calendar))
        stage="INDEPENDENT_SAMPLE_REPLAY"
        if summary["sample_replay_feature_rows"]!=267 or summary["sample_replay_sha256"]!=EXPECTED_SAMPLE_HASH:
            raise ValueError("Previously accepted sample feature values changed")
        summary.update({"prior_20_stock_sample_replay_exact":True,"early_overlap_exact_keys":overlap,
            "five_year_replayed_source_keys":fresh["merged_source_keys"],"late_neon_raw_rows":expected_late,
            "input_receipt_sha256":[x[1] for x in loaded]})
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump({"summary":summary,"private_batch_receipts":batch_reports,"private_feature_rows":features},f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(summary,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon writes or LINE action") from None


if __name__=="__main__":
    main()
