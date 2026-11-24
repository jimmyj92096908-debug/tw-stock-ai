"""Owner-local, fixed-window TWSE per-stock source depth; no price export or writes."""
from collections import Counter
from datetime import date
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path

from scripts import twse_private_history_receipt_overlay_offline as overlay
from scripts.twse_2021_22_traded_240_warmup_readonly import _private_archives, _private_file
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_2022_aes_neon_eligible_density_readonly import ELIGIBLE_SQL, classify_current_stock_source_absences
from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

START, END = map(date.fromisoformat, overlay.WINDOW)
SOURCES = ("TWSE_STOCK_DAY","TWSE_MI_INDEX_ALLBUT0999")
EARLY_END = date(2023,1,1)
ELIGIBLE = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible AS (
 SELECT o.stock_id FROM official_current_listed o WHERE o.market='twse'
 AND o.stock_id <> '1589' AND NOT EXISTS (
 SELECT 1 FROM public.model_stock_exclusions x
 WHERE x.market=o.market AND x.stock_id=o.stock_id))
"""
BASE = """
 FROM public.daily_prices p JOIN eligible e ON p.stock_id=e.stock_id
 WHERE p.market='twse' AND p.trade_date >= %s AND p.trade_date < %s
 AND p.source IN ('TWSE_STOCK_DAY','TWSE_MI_INDEX_ALLBUT0999')
 AND p.close>0 AND p.volume>=0
"""
EARLY_SQL = ELIGIBLE + "SELECT p.trade_date,p.stock_id,p.source " + BASE + " ORDER BY p.trade_date,p.stock_id LIMIT 180001"
LATE_SQL = ELIGIBLE + """
 SELECT p.stock_id,EXTRACT(YEAR FROM p.trade_date)::int,
 COUNT(*)::int,COUNT(DISTINCT p.trade_date)::int
 """ + BASE + " GROUP BY 1,2 ORDER BY 1,2 LIMIT 6001"


def capture(url):
    import psycopg
    if not url.startswith(("postgres://","postgresql://")):
        raise ValueError("Protected local connection required")
    with psycopg.connect(url,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='90s'")
            cur.execute(ELIGIBLE_SQL)
            roster=[r[0] for r in cur.fetchall()]
            cur.execute(EARLY_SQL,(START,EARLY_END))
            early=cur.fetchall()
            cur.execute(LATE_SQL,(EARLY_END,END))
            late=cur.fetchall()
        conn.rollback()
    return roster,early,late


def digest(path):
    h=sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def archive_keys(paths, *, key, start, end, expected_days, eligible):
    before={p:digest(p) for p in paths}
    proof=authenticated_archive_days(paths,hex_key=key,start=start,end=end)
    if proof["full_file_integrity_verified"] is not True or len(proof["days"])!=expected_days:
        raise ValueError("Authenticated archive day count changed")
    keys=set()
    total=0
    for p in paths:
        def collect(row):
            nonlocal total
            d,sid=row["trade_date"],row["stock_id"]
            total+=1
            if total>600000:
                raise ValueError("Archive row budget exceeded")
            if start<=d<end and sid in eligible:
                if (d,sid) in keys:
                    raise ValueError("Duplicate authenticated stock/date")
                keys.add((d,sid))
        verified=verify_archive(p,hex_key=key,on_verified_row=collect)
        if verified["archive_integrity_verified"] is not True:
            raise ValueError("Archive authentication failed")
    if before!={p:digest(p) for p in paths}:
        raise ValueError("Archive bytes changed")
    return keys,proof["days"]


def depth_summary(roster, early, late, aes21, aes22, days21, days22, *, expected, baseline, report21, report22):
    """Reconcile frozen aggregate receipts against fresh individual source keys."""
    if (len(roster)!=1092 or len(set(roster))!=1092 or
        any(not isinstance(s,str) or len(s)!=4 or not s.isascii() or not s.isdigit() or s=="1589" for s in roster)):
        raise ValueError("Official roster changed")
    allowed=set(roster)
    if len(early)>180000 or len(late)>6000:
        raise ValueError("Read budget exceeded")
    neon=set()
    for d,s,tag in early:
        if type(d) is not date or not START<=d<EARLY_END or d.weekday()>=5 or s not in allowed or tag not in SOURCES or (d,s) in neon:
            raise ValueError("Invalid early Neon key")
        neon.add((d,s))
    for keys,days,year,n in ((aes21,days21,2021,28),(aes22,days22,2022,162)):
        if len(days)!=n or any(type(d) is not date or d.year!=year or not START<=d<EARLY_END or d.weekday()>=5 for d in days):
            raise ValueError("Wrong authenticated calendar")
        if any(d not in days or s not in allowed for d,s in keys):
            raise ValueError("Wrong authenticated key")
    n21={k for k in neon if k[0].year==2021}
    n22=neon-n21
    u21=n21|aes21
    u22=n22|aes22
    if (len(n21),len(n22),len(aes21),len(u21),len(u22))!=(552,83294,26120,expected["twse_2021_union_observed_keys"],expected["twse_2022_union_observed_keys_from_absence_conservation"]):
        raise ValueError("Early source receipts drifted")
    # Validate the full original 2021 distribution and 2022 absence partition,
    # not merely two coincidentally equal annual totals.
    c21=Counter(s for d,s in u21)
    hist=Counter(str(c21[s]) for s in roster)
    previous=overlay.normalize_2021(report21)["current_stock_source_day_count_histogram"]
    if any(hist[str(i)]!=previous.get(str(i),0) for i in range(29)):
        raise ValueError("2021 source depth distribution drifted")
    calendar=sorted({d for d,s in u22})
    if len(calendar)!=246 or set(calendar)!={d for d,s in n22} or {d for d,s in u21}!=set(days21):
        raise ValueError("Early source calendar drifted")
    idx={d:i for i,d in enumerate(calendar)}
    c22=Counter();first={};last={}
    for d,s in sorted(u22):
        c22[s]+=1
        first.setdefault(s,idx[d])
        last[s]=idx[d]
    actual=classify_current_stock_source_absences(roster,c22,first,last,source_day_count=246)
    prior=report22["current_listed_source_date_observation_absence_signatures"]
    if any(actual.get(k)!=prior.get(k) for k in actual):
        raise ValueError("2022 source absence signatures drifted")
    annual=Counter();later=Counter();seen=set()
    for s,y,n,distinct in late:
        if s not in allowed or type(y) is not int or not 2023<=y<=2026 or type(n) is not int or type(distinct) is not int or not 1<=n<=366 or n!=distinct or (s,y) in seen:
            raise ValueError("Invalid or duplicated late source depth")
        seen.add((s,y));annual[y]+=n;later[s]+=n
    years={x["year"]:x["neon_stored_valid_source_stock_bars"] for x in baseline["market"]["twse"]["yearly_neon_source_observations"]}
    if any(annual[y]!=years[y] for y in range(2023,2027)):
        raise ValueError("Later annual baseline totals drifted")
    neon_counts=Counter(s for d,s in neon)
    old=[neon_counts[s]+later[s] for s in roster]
    new=[c21[s]+c22[s]+later[s] for s in roster]
    def buckets(values):
        return {"stock_days0":sum(n==0 for n in values),
          "stock_days1_59":sum(1<=n<60 for n in values),
          "stock_days60_239":sum(60<=n<240 for n in values),
          "stock_days240_479":sum(240<=n<480 for n in values),
          "stock_days480_999":sum(480<=n<1000 for n in values),
          "stock_days1000_plus":sum(n>=1000 for n in values)}
    previous_depth=baseline["market"]["twse"]["per_stock_5year_neon_valid_days_distribution"]
    if buckets(old)!=previous_depth or sum(old)!=expected["twse_neon_only_baseline_stock_date_keys"] or sum(new)!=expected["conditional_twse_baseline_replacement_keys"] or any(a>b for a,b in zip(old,new)):
        raise ValueError("Five-year conservation or baseline depth drifted")
    return {"schema_version":1,"scope":"OWNER_FIXED_5Y_TWSE_CURRENT_COHORT_SOURCE_DEPTH_REPLAY",
        "window_start_inclusive":START.isoformat(),"window_end_exclusive":END.isoformat(),
        "eligible_stocks":len(roster),"neon_only_keys":sum(old),"merged_source_keys":sum(new),
        "additional_keys":sum(new)-sum(old),
        "neon_only_depth_distribution":buckets(old),"merged_depth_distribution":buckets(new),
        "neon_only_at_least_240":sum(n>=240 for n in old),"merged_at_least_240":sum(n>=240 for n in new),
        "neon_only_at_least_1000":sum(n>=1000 for n in old),"merged_at_least_1000":sum(n>=1000 for n in new),
        "same_current_roster_used_for_this_replay":True,"prior_roster_identity_independently_proven":False,
        "ohlcv_overlap_economic_parity_verified":False,"five_year_complete":False,
        "historical_pit_total_return_verified":False,"factor_values_recomputed":False,
        "production_neon_writes":0,"line_messages_sent":0,"model_release":"BLOCKED"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("archive-2021","archive-2022","key-vault","union-2021","density-2022","neon-five-year","out"):
        p.add_argument("--"+arg,required=True)
    a=p.parse_args()
    stage="RECEIPTS"
    try:
        inputs=[overlay.private_path(x) for x in (a.union_2021,a.density_2022,a.neon_five_year)]
        out=_private_file(a.out,should_exist=False)
        if len(set([*inputs,out]))!=4:
            raise ValueError("Distinct private paths required")
        loaded=[overlay.load(x) for x in inputs]
        r21,r22,base=[x[0] for x in loaded]
        expected=overlay.reconcile(r21,r22,base)
        stage="NEON_READONLY"
        roster,early,late=capture(os.environ.get("DATABASE_URL",""))
        stage="ARCHIVE_AUTHENTICATION"
        p21=_private_archives(a.archive_2021);p22=_private_archives(a.archive_2022)
        if set(p21)&set(p22):
            raise ValueError("Archive directories overlap")
        key=resolve_archive_key(vault_path=Path(a.key_vault),env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
        k21,d21=archive_keys(p21,key=key,start=START,end=date(2022,1,1),expected_days=28,eligible=set(roster))
        k22,d22=archive_keys(p22,key=key,start=date(2022,1,1),end=EARLY_END,expected_days=162,eligible=set(roster))
        stage="SOURCE_DEPTH_RECONCILIATION"
        result=depth_summary(roster,early,late,k21,k22,d21,d22,expected=expected,baseline=base,report21=r21,report22=r22)
        result["input_receipt_sha256"]=[x[1] for x in loaded]
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump(result,f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(result))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon writes or LINE action") from None


if __name__=="__main__":
    main()
