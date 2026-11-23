"""Owner-only 2021 TWSE 28-day AES + Neon stock/date de-duplicated union.

Actual rolling 5-year baseline: 2021-11-23 to 2026-11-23 (exclusive).
Neon-only had 552 current-listed stock/date keys; owner authenticated AES
has 26,120 across the 28 source dates. Their overlap MUST be checked by
real (trade_date, stock_id) rather than adding published counts.

Only source-date presence is studied. No price exported, historical
as-of-issuer eligibility/total-return/economic K-bars not certified.
Never modifies Neon, private source files, LINE or published model.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from scripts.twse_2021_22_traded_240_warmup_readonly import (
    _private_archives, _private_file,
)
from scripts.twse_2021_28day_aes_current_cohort_density_readonly import (
    EXPECTED_DAYS, SCOPE as AES_SCOPE, MAX_SOURCE_ROWS,
    evaluate_2021_aes_current_cohort, verify_previous_baseline,
)
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_2022_aes_neon_eligible_density_readonly import ELIGIBLE_SQL
from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

SCOPE = "OWNER_2021_TWSE_AES_NEON_CURRENT_LISTED_28DAY_STOCK_DATE_UNION_READONLY"
BEGIN, END = date(2021, 11, 23), date(2022, 1, 1)
MAX_NEON_KEYS = 2000
MAX_REPORT_BYTES = 18_000
SOURCES = ("TWSE_STOCK_DAY", "TWSE_MI_INDEX_ALLBUT0999")

NEON_2021_SOURCE_KEYS_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible AS (
 SELECT o.stock_id FROM official_current_listed o
 WHERE o.market='twse' AND o.stock_id <> '1589'
   AND NOT EXISTS (
     SELECT 1 FROM public.model_stock_exclusions x
     WHERE x.market=o.market AND x.stock_id=o.stock_id
   )
)
SELECT p.trade_date,p.stock_id,p.source FROM public.daily_prices p
JOIN eligible e ON e.stock_id=p.stock_id
WHERE p.market='twse'
 AND p.trade_date >= DATE '2021-11-23'
 AND p.trade_date < DATE '2022-01-01'
 AND p.source IN ('TWSE_STOCK_DAY','TWSE_MI_INDEX_ALLBUT0999')
 AND p.close>0 AND p.volume>=0
ORDER BY p.trade_date,p.stock_id
"""


def _proof_241(prior_aes):
    if (not isinstance(prior_aes, dict)
            or prior_aes.get("schema_version")!=1
            or prior_aes.get("scope")!=AES_SCOPE
            or prior_aes.get("rolling_baseline_asof")!="2026-11-23"
            or prior_aes.get("authenticated_2021_owner_aes_source_days")!=28
            or prior_aes.get("2021_aes_current_2026_twse_survivor_eligible_count")!=1092
            or prior_aes.get("2021_aes_current_2026_twse_stock_date_presence_pairs")!=26120
            or prior_aes.get("2021_2026_current_stocks_with_all_28_observed_source_days")!=900
            or prior_aes.get("2021_2026_current_stocks_with_at_least_26_of_28_days")!=916
            or prior_aes.get("2021_2026_current_stocks_with_no_2021_source_day")!=153
            or prior_aes.get("neon_only_source_stock_date_count_in_2021_prior")!=552
            or prior_aes.get("2021_current_cohort_aes_neon_deduplicated_stock_day_union_verified") is not False
            or prior_aes.get("production_neon_writes")!=0
            or prior_aes.get("line_messages_sent")!=0
            or prior_aes.get("model_release")!="BLOCKED"):
        raise ValueError("Immutable owner PR241 AES 28-day per-stock receipt drifted")


def capture_neon_current_2021_readonly(uri):
    """One current official listing roster and 2021 source keys in 1 snapshot."""
    if not isinstance(uri,str) or not uri.startswith(
            ("postgres://","postgresql://")):
        raise ValueError("Protected existing owner Neon URI required")
    import psycopg
    with psycopg.connect(uri, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='45000ms'")
            cur.execute(ELIGIBLE_SQL)
            roster=[x[0] for x in cur.fetchall()]
            cur.execute(NEON_2021_SOURCE_KEYS_SQL)
            rows=cur.fetchall()
            if len(rows)>MAX_NEON_KEYS:
                raise ValueError("Unbounded 2021 Neon current-issuer source keys")
        conn.rollback()
    return roster, rows


def evaluate_2021_union(*, prior_aes, prior_neon, recomputed_aes,
                        roster, aes_by_day, neon_rows):
    """Conserve per-source stock/date sets without assuming historic tradability."""
    _proof_241(prior_aes)
    verify_previous_baseline(prior_neon)
    if recomputed_aes != prior_aes:
        raise ValueError("Owner 2021 authenticated AES private source proof changed")
    if (not isinstance(roster,(tuple,list)) or len(roster)!=1092
            or len(set(roster))!=1092
            or any(not isinstance(s,str) or not re.fullmatch(r"\d{4}",s)
                   or s=="1589" for s in roster)):
        raise ValueError("Latest official current TWSE survivor cohort invalid")
    if (not isinstance(aes_by_day,dict)
            or set(aes_by_day)!=set(EXPECTED_DAYS)):
        raise ValueError("2021 authenticated 28 source-day AES stock/date keys missing")
    allowed=set(roster)
    aes=set()
    for d,stocks in aes_by_day.items():
        if (type(d) is not date or
                not isinstance(stocks,set) or
                not stocks<=allowed or len(stocks)<500):
            raise ValueError("2021 AES source contains unverified stock/date key")
        aes.update((d,s) for s in stocks)
    if len(aes)!=26120:
        raise ValueError("2021 AES keys differ from immutable 26,120 owner receipt")
    if not isinstance(neon_rows,(list,tuple)) or len(neon_rows)!=552:
        raise ValueError("2021 Neon 552 current-stock source rows drifted")
    neon=set()
    neon_dates=set()
    for item in neon_rows:
        if not isinstance(item,(tuple,list)) or len(item)!=3:
            raise ValueError("Malformed 2021 source tag row")
        d,sid,source=item
        if (type(d) is not date or d not in aes_by_day or
                sid not in allowed or source not in SOURCES or
                (d,sid) in neon):
            raise ValueError("Duplicate or non-2021 Neon stock/date key")
        neon.add((d,sid))
        neon_dates.add(d)
    if (len(neon)!=552 or neon_dates!=set(EXPECTED_DAYS)):
        raise ValueError("2021 original Neon observed source-date calendar drifted")
    common = aes & neon
    neon_only=neon-aes
    aes_only=aes-neon
    combined=aes|neon
    per_stock=Counter(s for _,s in combined)
    hist={str(i):0 for i in range(29)}
    for s in allowed:
        hist[str(per_stock[s])]+=1
    month={}
    for d in EXPECTED_DAYS:
        m=d.strftime("%Y-%m")
        a=sum((d,s) in aes for s in aes_by_day[d])
        n=sum((d,s) in neon for _,s in neon_rows if _==d)
        union_here=sum(day==d for day,s in combined)
        overlap_here=a+n-union_here
        row=month.setdefault(m,{
            "source_dates":0,
            "aes_source_stock_date_pairs":0,
            "neon_source_stock_date_pairs":0,
            "duplicate_aes_neon_stock_date_pairs":0,
            "deduplicated_source_stock_date_pairs":0,
        })
        row["source_dates"]+=1
        row["aes_source_stock_date_pairs"]+=a
        row["neon_source_stock_date_pairs"]+=n
        row["duplicate_aes_neon_stock_date_pairs"]+=overlap_here
        row["deduplicated_source_stock_date_pairs"]+=union_here
    full_28=sum(per_stock[s]==28 for s in allowed)
    at_least_26=sum(per_stock[s]>=26 for s in allowed)
    never=sum(per_stock[s]==0 for s in allowed)
    if (len(aes_only)+len(common)!=len(aes)
            or len(neon_only)+len(common)!=len(neon)
            or len(combined)!=len(aes)+len(neon_only)
            or sum(hist.values())!=1092
            or sum(int(k)*v for k,v in hist.items())!=len(combined)
            or sum(x["source_dates"] for x in month.values())!=28
            or sum(x["deduplicated_source_stock_date_pairs"]
                   for x in month.values())!=len(combined)
            or full_28<900 or at_least_26<916 or never>153):
        raise ValueError("2021 AES+Neon current cohort conservation failed")
    return {
        "schema_version":1,"scope":SCOPE,
        "five_year_baseline_window_start":"2021-11-23",
        "five_year_baseline_window_end_exclusive":"2026-11-23",
        "official_current_survivor_tickers_excluding_1589":1092,
        "authenticated_owner_2021_source_dates":28,
        "prior_2021_aes_source_stock_date_pairs":26120,
        "prior_2021_neon_source_stock_date_pairs":552,
        "aes_neon_overlapping_source_stock_date_pairs":len(common),
        "aes_exclusive_source_stock_date_pairs":len(aes_only),
        "neon_exclusive_source_stock_date_pairs":len(neon_only),
        "actual_deduplicated_aes_neon_stock_date_pairs":len(combined),
        "current_stocks_with_all_28_original_source_dates":full_28,
        "current_stocks_with_at_least_26_of_28_source_dates":at_least_26,
        "current_stocks_with_no_source_day_in_2021":never,
        "current_stock_source_day_count_histogram":hist,
        "source_monthly_deduplicated_density":month,
        "unobserved_issuer_source_day_not_proven_missing_price":True,
        "current_issuer_2026_roster_is_not_historical_2021_pit_roster":True,
        "official_historic_ipo_halts_board_trading_eligibility_verified":False,
        "delisted_or_excluded_stock_source_added":False,
        "2021_2026_full_five_year_price_panel_validated":False,
        "full_corporate_action_total_return_adjusted":False,
        "model_walkforward_release_approved":False,
        "production_neon_writes":0,
        "line_messages_sent":0,
        "paid_services_used":False,
        "model_release":"BLOCKED",
    }


def run_owner(*,archive_2021,key_vault,prior_aes_report,
              prior_five_year_report,out,db_url,today=None):
    day=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if (type(day) is not date or
            not date(2026,11,23)<=day<=date(2026,12,7)):
        raise ValueError("Frozen 2026-11-23 current-cohort receipt too old")
    paths=_private_archives(archive_2021)
    prior241path=_private_file(prior_aes_report,should_exist=True)
    prior5ypath=_private_file(prior_five_year_report,should_exist=True)
    output=_private_file(out,should_exist=False)
    if (prior241path==prior5ypath or output in (prior241path,prior5ypath)
            or any(x in (prior241path,prior5ypath,output) for x in paths)):
        raise ValueError("Owner report/source/output must be different files")
    prior241=json.loads(prior241path.read_text(encoding="utf-8"))
    prior5y=json.loads(prior5ypath.read_text(encoding="utf-8"))
    _proof_241(prior241)
    verify_previous_baseline(prior5y)
    key=resolve_archive_key(vault_path=Path(key_vault),
                            env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
    rawhash={p.name:sha256(p.read_bytes()).hexdigest() for p in paths}
    authed=authenticated_archive_days(
        paths,hex_key=key,start=BEGIN,end=END)
    if (authed.get("full_file_integrity_verified") is not True or
            authed["days"]!=frozenset(EXPECTED_DAYS)):
        raise ValueError("Owner private 2021 AES 28 source dates fail authentication")
    roster,neon_rows=capture_neon_current_2021_readonly(db_url)
    allowed=set(roster)
    data={d:set() for d in EXPECTED_DAYS}
    raw_rows=0
    for p in paths:
        def accept(row):
            nonlocal raw_rows
            raw_rows+=1
            d,sid=row["trade_date"],row["stock_id"]
            if d not in data or raw_rows>MAX_SOURCE_ROWS:
                raise ValueError("Owner 2021 AES stock/day outside authenticated source window")
            if sid in allowed:
                if sid in data[d]:
                    raise ValueError("Duplicate original 2021 AES stock/day key")
                data[d].add(sid)
        proof=verify_archive(p,hex_key=key,on_verified_row=accept)
        if proof.get("archive_integrity_verified") is not True:
            raise ValueError("2021 AES footer not cryptographically verified")
    if {p.name:sha256(p.read_bytes()).hexdigest() for p in paths}!=rawhash:
        raise ValueError("Original AES ciphertext changed during repeated replay")
    prior_old=evaluate_2021_aes_current_cohort(
        prior5y,eligible=roster,source_days=set(EXPECTED_DAYS),
        per_day_stocks=data,source_rows=raw_rows,aes_file_hashes=rawhash)
    report=evaluate_2021_union(
        prior_aes=prior241,prior_neon=prior5y,recomputed_aes=prior_old,
        roster=roster,aes_by_day=data,neon_rows=neon_rows)
    payload=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if len(payload.encode("utf-8"))>MAX_REPORT_BYTES:
        raise ValueError("2021 28-date AES+Neon private union report exceeds limit")
    with output.open("x",encoding="utf-8") as f:
        f.write(payload)
    print(json.dumps({
        "status":"TWSE_2021_28DAY_AES_NEON_STOCK_DATE_UNION_READONLY_PASS",
        "aes_source_stock_date_pairs":len(
            [1 for stocks in data.values() for _ in stocks]),
        "neon_source_stock_date_pairs":len(neon_rows),
        "duplicate_aes_neon_stock_date_pairs":report[
            "aes_neon_overlapping_source_stock_date_pairs"],
        "net_new_from_neon_stock_date_pairs":report[
            "neon_exclusive_source_stock_date_pairs"],
        "actual_2021_union_stock_date_pairs":report[
            "actual_deduplicated_aes_neon_stock_date_pairs"],
        "2021_current_stocks_with_all_28_dates":report[
            "current_stocks_with_all_28_original_source_dates"],
        "2021_current_stocks_with_no_source_days":report[
            "current_stocks_with_no_source_day_in_2021"],
        "neon_writes":0,
        "line_messages_sent":0,"model_release":"BLOCKED",
    },ensure_ascii=False))


def main():
    ap=argparse.ArgumentParser(
        description="Owner 2021 AES + Neon 28-day precise per-stock-date dedup, 1 bounded Neon read-only snapshot")
    ap.add_argument("--archive-2021",required=True)
    ap.add_argument("--key-vault",required=True)
    ap.add_argument("--prior-241-aes-report",required=True)
    ap.add_argument("--prior-five-year-neon-report",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    try:
        run_owner(
            archive_2021=a.archive_2021,key_vault=a.key_vault,
            prior_aes_report=a.prior_241_aes_report,
            prior_five_year_report=a.prior_five_year_neon_report,
            out=a.out,db_url=os.environ.get("DATABASE_URL",""))
    except Exception:
        raise SystemExit(
            "Owner 2021 AES + Neon source stock/date union FAILED; "
            "Neon and LINE untouched and no prices/URI/AES keys revealed"
        ) from None


if __name__=="__main__":
    main()
