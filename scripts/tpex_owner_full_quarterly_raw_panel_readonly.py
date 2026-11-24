"""Owner-local TPEx full current-listed quarterly raw-feature panel.

One bounded read-only Neon snapshot, same fixed 17 dates as accepted TWSE
panel. Source-tagged TPEx volume is normalized only by the shared bridge.
Private feature rows stay local; no historical PIT/adjusted-return claims.
"""
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
import argparse
import json
import os

from scripts import twse_owner_five_year_source_depth_readonly as depth
from scripts import twse_owner_early_economic_factor_pilot_readonly as early
from scripts import twse_owner_quarterly_raw_feature_sample_readonly as q
from scripts import twse_private_history_receipt_overlay_offline as overlay
from scripts import twse_tpex_five_year_neon_only_cohort_readonly as baseline
from src.raw_factor_feature_bridge import FEATURE_NAMES, VERSION, OFFICIAL_SOURCE_TAGS
from src.build_adjusted_prices import LEGACY_TPEX_MONTHLY_SOURCE, MAX_BIGINT

BATCH=40
MAX_ROWS=1_350_000
EXPECTED_STOCKS=898
BASE_SHA="b1d2152c0919c26537e39d4620947777005961a9d8d3a96cd29a97a7309aea0d"
SIGNALS=[date.fromisoformat(d) for d in (
    "2022-12-30","2023-03-31","2023-06-30","2023-09-28","2023-12-29",
    "2024-03-29","2024-06-28","2024-09-30","2024-12-31","2025-03-31",
    "2025-06-30","2025-09-30","2025-12-31","2026-03-31","2026-06-30",
    "2026-09-30","2026-11-20")]
ELIGIBLE=baseline.ELIGIBLE
ROSTER_SQL=ELIGIBLE+"SELECT stock_id FROM eligible WHERE market='tpex' ORDER BY stock_id"
FROM_SQL="""
 FROM public.daily_prices p JOIN eligible e ON e.market=p.market AND e.stock_id=p.stock_id
 WHERE p.market='tpex' AND p.trade_date >= %s AND p.trade_date < %s
 AND p.close>0 AND p.volume>=0
 """+baseline.VALID_SOURCE
COUNT_SQL=ELIGIBLE+"SELECT p.stock_id,EXTRACT(YEAR FROM p.trade_date)::int,COUNT(*)::int,COUNT(DISTINCT p.trade_date)::int "+FROM_SQL+" GROUP BY 1,2 ORDER BY 1,2 LIMIT 5401"
CAL_SQL=ELIGIBLE+"SELECT p.trade_date,COUNT(*)::int "+FROM_SQL+" GROUP BY 1 ORDER BY 1 LIMIT 1601"
BARS_SQL=ELIGIBLE+"SELECT p.trade_date,p.stock_id,p.source,p.open,p.high,p.low,p.close,p.volume "+FROM_SQL+" AND p.stock_id=ANY(%s) ORDER BY p.stock_id,p.trade_date LIMIT 64001"


def fingerprint(rows):
    return sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def batches(roster):
    ids=sorted(roster)
    return [ids[i:i+BATCH] for i in range(0,len(ids),BATCH)]


def validate_snapshot(roster,counts,calendar,report):
    if (len(roster)!=EXPECTED_STOCKS or len(set(roster))!=len(roster)
        or any(type(s) is not str or len(s)!=4 or not s.isascii() or not s.isdigit() or s=="1589" for s in roster)
        or len(counts)>5400 or len(calendar)>1600):
        raise ValueError("Invalid or drifted current official TPEx roster")
    base=report["market"]["tpex"]
    if base["official_current_listed_stocks_excluding_1589"]!=len(roster):
        raise ValueError("Baseline cohort drift")
    allowed=set(roster);per_stock=Counter();annual=Counter();seen=set()
    for s,y,n,distinct in counts:
        if (s not in allowed or type(y) is not int or not 2021<=y<=2026
            or type(n) is not int or type(distinct) is not int or not 1<=n<=366
            or n!=distinct or (s,y) in seen):
            raise ValueError("Invalid annual stock-date counts")
        seen.add((s,y));per_stock[s]+=n;annual[y]+=n
    values=[per_stock[s] for s in roster]
    hist={"stock_days0":sum(n==0 for n in values),"stock_days1_59":sum(1<=n<60 for n in values),
        "stock_days60_239":sum(60<=n<240 for n in values),"stock_days240_479":sum(240<=n<480 for n in values),
        "stock_days480_999":sum(480<=n<1000 for n in values),"stock_days1000_plus":sum(n>=1000 for n in values)}
    if hist!=base["per_stock_5year_neon_valid_days_distribution"]:
        raise ValueError("Prior stock depth changed")
    days=set();day_counts=Counter();dense=Counter();day_totals=Counter()
    for d,n in calendar:
        if (type(d) is not date or not depth.START<=d<depth.END or d.weekday()>=5
            or d in days or type(n) is not int or not 1<=n<=len(roster)):
            raise ValueError("Invalid observed TPEx date")
        days.add(d);day_counts[d.year]+=1;dense[d.year]+=n>=500;day_totals[d.year]+=n
    years={r["year"]:r for r in base["yearly_neon_source_observations"]}
    if set(years)!=set(range(2021,2027)):
        raise ValueError("Prior baseline year schema changed")
    for y,r in years.items():
        if (annual[y]!=day_totals[y] or annual[y]!=r["neon_stored_valid_source_stock_bars"]
            or day_counts[y]!=r["days_with_any_neon_eligible_source_bars"]
            or dense[y]!=r["days_with_at_least_500_eligible_source_bars"]):
            raise ValueError("Prior annual source/date counts changed")
    total=sum(annual.values())
    if not 0<total<=MAX_ROWS or not days:
        raise ValueError("Read bound exceeded")
    return days,total


def capture(url,report):
    import psycopg
    if not isinstance(url,str) or not url.startswith(("postgres://","postgresql://")):
        raise ValueError("Protected local URL required")
    raw=defaultdict(list)
    with psycopg.connect(url,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='90s'")
            cur.execute(ROSTER_SQL)
            roster=[r[0] for r in cur.fetchall()]
            cur.execute(COUNT_SQL,(depth.START,depth.END))
            counts=cur.fetchall()
            cur.execute(CAL_SQL,(depth.START,depth.END))
            calendar=cur.fetchall()
            days,budget=validate_snapshot(roster,counts,calendar,report)
            total=0
            for batch in batches(roster):
                cur.execute(BARS_SQL,(depth.START,depth.END,batch))
                rows=cur.fetchall()
                if len(rows)>64000:
                    raise ValueError("Batch read bound exceeded")
                allowed=set(batch)
                for r in rows:
                    if r[1] not in allowed:
                        raise ValueError("Foreign source stock")
                    raw[r[1]].append(r)
                total+=len(rows)
                if total>budget:
                    raise ValueError("Full read budget exceeded")
            if total!=budget:
                raise ValueError("Source count drift")
        conn.rollback()
    return roster,counts,days,raw,budget


def process_batch(selected,raw,calendar,counts):
    groups=defaultdict(list);bad={};observed=Counter();source_counts=Counter()
    for sid in selected:
        seen=set()
        for row in raw.get(sid,[]):
            r=dict(zip(early.COLS,row),market="tpex")
            d,s=r["trade_date"],r["stock_id"]
            if (type(d) is not date or d not in calendar or s!=sid or d in seen or r["source"] not in OFFICIAL_SOURCE_TAGS):
                raise ValueError("Duplicate, foreign or invalid-provenance source key")
            seen.add(d);observed[s,d.year]+=1;source_counts[r["source"]]+=1
            valid=early.exact_core(r) is not None
            if valid and r["source"]==LEGACY_TPEX_MONTHLY_SOURCE and r["volume"]>MAX_BIGINT//1000:
                valid=False
            if not valid:
                bad[s]=min(d,bad.get(s,d))
            groups[s].append(r)
    expected={(s,y):n for s,y,n,distinct in counts if s in selected}
    if dict(observed)!=expected:
        raise ValueError("Batch source count mismatch")
    report,features=q.calculate_cohort(selected,groups,bad,calendar,SIGNALS,market="tpex")
    return report,features,source_counts


def panel(roster,raw,calendar,counts):
    features=[];receipts=[];source_counts=Counter();outcomes={d.isoformat():Counter() for d in SIGNALS}
    for batch in batches(roster):
        result,rows,sources=process_batch(batch,raw,calendar,counts)
        source_counts.update(sources)
        for r in result["signal_date_outcomes"]:
            outcomes[r["signal_date"]]["accepted"]+=r["accepted"]
            outcomes[r["signal_date"]].update(r["excluded"])
        features.extend(rows)
        receipts.append({"issuer_count":len(batch),"accepted_rows":len(rows),"feature_rows_sha256":fingerprint(rows)})
    features.sort(key=lambda r:(r["signal_date"],r["stock_id"]))
    if (len({(r["signal_date"],r["stock_id"]) for r in features})!=len(features)
        or sum(v["accepted"] for v in outcomes.values())!=len(features)
        or any(sum(v.values())!=len(roster) for v in outcomes.values())
        or sum(source_counts.values())!=sum(r[2] for r in counts)):
        raise RuntimeError("Panel conservation failure")
    return {"schema_version":1,"scope":"OWNER_TPEX_ALL_CURRENT_LISTED_QUARTERLY_RAW_FEATURE_PANEL",
        "eligible_stocks":len(roster),"batch_count":len(receipts),"requested_signal_dates":len(SIGNALS),
        "candidate_stock_signal_pairs":len(roster)*len(SIGNALS),"accepted_feature_rows":len(features),
        "accepted_feature_values":len(features)*len(FEATURE_NAMES),"feature_names":list(FEATURE_NAMES),
        "feature_version":VERSION,"signal_date_outcomes":[{"signal_date":d.isoformat(),
        "accepted":outcomes[d.isoformat()]["accepted"],"excluded":{k:v for k,v in sorted(outcomes[d.isoformat()].items()) if k!="accepted"}} for d in SIGNALS],
        "original_source_row_counts":dict(sorted(source_counts.items())),"legacy_monthly_source_units_normalized_in_feature_engine_only":True,
        "private_feature_rows_sha256":fingerprint(features),"prefix_only_feature_computation":True,
        "same_fixed_signal_dates_as_twse":True,"current_roster_not_historical_pit":True,
        "official_market_calendar_independently_proven":False,"daily_full_five_year_factor_panel_recomputed":False,
        "forward_labels_created":False,"corporate_actions_adjusted":False,"historical_pit_total_return_verified":False,
        "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"},features,receipts


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--neon-five-year",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--allow-bounded-full-read",action="store_true",required=True)
    a=p.parse_args()
    stage="RECEIPT"
    try:
        source=overlay.private_path(a.neon_five_year)
        report,digest=overlay.load(source)
        if (digest!=BASE_SHA or report.get("scope")!=baseline.SCOPE
            or report.get("window_start_inclusive")!=depth.START.isoformat()
            or report.get("window_end_exclusive")!=depth.END.isoformat()):
            raise ValueError("Expected exact prior owner baseline receipt")
        out=depth._private_file(a.out,should_exist=False)
        if out==source:
            raise ValueError("Distinct private output required")
        stage="NEON_READONLY"
        roster,counts,calendar,raw,budget=capture(os.environ.get("DATABASE_URL",""),report)
        stage="QUARTERLY_PANEL"
        result,features,receipts=panel(roster,raw,calendar,counts)
        if not features:
            raise ValueError("No usable factor rows")
        result.update({"neon_source_rows":budget,"baseline_receipt_sha256":digest})
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump({"summary":result,"private_batch_receipts":receipts,"private_feature_rows":features},f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(result,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon writes or LINE action") from None


if __name__=="__main__":
    main()
