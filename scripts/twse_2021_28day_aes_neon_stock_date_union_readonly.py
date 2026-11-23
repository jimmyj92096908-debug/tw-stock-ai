"""2021 Nov23-Dec30 per-stock-date union of owner AES and read-only Neon.

Authenticated local AES prices stay owner-side; only stock/date *presence*
is combined with a single Neon REPEATABLE READ READ ONLY snapshot. The
immutable accepted owner PR241 receipt is fully recomputed from actual AES
before any output. Never write OHLCV, inferred halt bars, or LINE messages.

This proves observed 2021 source-key overlap, NOT historical issuer PIT
membership, IPO eligibility, OHLCV economic parity, dividend adjustments or
release readiness. No live provider HTTP requests or paid services.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date,datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from scripts.twse_2021_28day_aes_current_cohort_density_readonly import (
    EXPECTED_DAYS,MAX_SOURCE_ROWS,
    evaluate_2021_aes_current_cohort,verify_previous_baseline,
)
from scripts.twse_2021_22_traded_240_warmup_readonly import (
    _private_archives,_private_file,
)
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_2022_aes_neon_eligible_density_readonly import ELIGIBLE_SQL

SCOPE="OWNER_TWSE_2021_28DAY_AES_NEON_CURRENT_COHORT_STOCK_DATE_UNION"
SOURCES=frozenset(("TWSE_MI_INDEX_ALLBUT0999","TWSE_STOCK_DAY"))
MAX_REPORT_BYTES=16500
MAX_NEON_ROWS=800
EXPECTED_NEON_ROWS=552
EXPECTED_AES_PAIRS=26120
EXPECTED_AES_FULL=900
EXPECTED_AES_26PLUS=916
EXPECTED_AES_ZERO=153

# Only the official-current-listed CTE; no fallback to stock_master.
from scripts.twse_tpex_five_year_neon_only_cohort_readonly import CURRENT_OFFICIAL_LISTED_CTE

STOCK_DATE_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible AS (
 SELECT o.stock_id FROM official_current_listed o
 WHERE o.market='twse' AND o.stock_id <> '1589'
 AND NOT EXISTS (
  SELECT 1 FROM public.model_stock_exclusions x
  WHERE x.market=o.market AND x.stock_id=o.stock_id
 ))
SELECT p.trade_date,p.stock_id,p.source
FROM public.daily_prices p JOIN eligible e ON e.stock_id=p.stock_id
WHERE p.market='twse'
  AND p.trade_date >= DATE '2021-11-23'
  AND p.trade_date < DATE '2022-01-01'
  AND p.source IN ('TWSE_MI_INDEX_ALLBUT0999','TWSE_STOCK_DAY')
  AND p.close > 0 AND p.volume >= 0
ORDER BY p.trade_date,p.stock_id
"""


def validate_immutable_241(previous):
    if (not isinstance(previous,dict)
            or previous.get("schema_version")!=1
            or previous.get("scope")!=
                "OWNER_TWSE_2021_28_REAL_AES_SOURCE_DATE_CURRENT_COHORT_DENSITY_READONLY"
            or previous.get("five_year_baseline_window_start")!="2021-11-23"
            or previous.get("five_year_baseline_window_end_exclusive")!="2026-11-23"
            or previous.get("authenticated_2021_owner_aes_source_days")!=28
            or previous.get("2021_aes_current_2026_twse_survivor_eligible_count")!=1092
            or previous.get("2021_aes_current_2026_twse_stock_date_presence_pairs")!=EXPECTED_AES_PAIRS
            or previous.get("2021_2026_current_stocks_with_all_28_observed_source_days")!=EXPECTED_AES_FULL
            or previous.get("2021_2026_current_stocks_with_at_least_26_of_28_days")!=EXPECTED_AES_26PLUS
            or previous.get("2021_2026_current_stocks_with_no_2021_source_day")!=EXPECTED_AES_ZERO
            or previous.get("neon_only_source_stock_date_count_in_2021_prior")!=EXPECTED_NEON_ROWS
            or previous.get("2021_current_cohort_aes_neon_deduplicated_stock_day_union_verified") is not False
            or previous.get("source_days_do_not_prove_all_issuer_ipo_or_tradability") is not True
            or previous.get("production_neon_writes")!=0
            or previous.get("line_messages_sent")!=0
            or previous.get("model_release")!="BLOCKED"):
        raise ValueError("Original accepted PR241 28-day AES density receipt changed")
    return True


def capture_neon_2021(date_base_url):
    """2021 source-day identifiers only; transaction explicitly READ ONLY."""
    if not isinstance(date_base_url,str) or not date_base_url.startswith(
            ("postgresql://","postgres://")):
        raise ValueError("Private owner Neon PostgreSQL URI required")
    import psycopg
    with psycopg.connect(date_base_url,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='45000ms'")
            cur.execute(ELIGIBLE_SQL)
            roster=[r[0] for r in cur.fetchall()]
            cur.execute(STOCK_DATE_SQL)
            rows=cur.fetchall()
            if len(rows)>MAX_NEON_ROWS:
                raise ValueError("2021 Neon original source rows exceeded safe upper bound")
        conn.rollback()
    return roster,rows


def reconcile_union(base,original_241,*,roster,aes_by_day,
                    neon_rows,reverified_241):
    """Exact 28-day current survivor stock/source key union (pure/offline)."""
    verify_previous_baseline(base)
    validate_immutable_241(original_241)
    if not isinstance(reverified_241,dict) or reverified_241!=original_241:
        raise ValueError("Cryptographically replayed current 2021 AES panel changed")
    if (not isinstance(roster,(list,tuple)) or len(roster)!=1092
            or len(set(roster))!=1092
            or any(not isinstance(s,str) or
                   re.fullmatch(r"[0-9]{4}",s) is None or s=="1589"
                   for s in roster)
            or not isinstance(aes_by_day,dict)
            or set(aes_by_day)!=set(EXPECTED_DAYS)
            or not isinstance(neon_rows,(tuple,list))
            or len(neon_rows)!=EXPECTED_NEON_ROWS):
        raise ValueError("2021 owner AES or Neon source key roster drifted")
    eligible=set(roster)
    if (sum(len(v) for v in aes_by_day.values())!=EXPECTED_AES_PAIRS
            or any(not isinstance(aes_by_day[d],set)
                   or not aes_by_day[d]<=eligible
                   or len(aes_by_day[d])<500 for d in EXPECTED_DAYS)):
        raise ValueError("2021 authenticated original AES source-key count drifted")
    observed_neon={d:set() for d in EXPECTED_DAYS}
    labels=Counter()
    seen=set()
    for entry in neon_rows:
        if not isinstance(entry,(tuple,list)) or len(entry)!=3:
            raise ValueError("Malformed valid 2021 Neon source stock-date key")
        day,sid,tag=entry
        if (type(day) is not date or day not in observed_neon
                or sid not in eligible or tag not in SOURCES
                or (day,sid) in seen):
            raise ValueError("2021 Neon duplicate, invalid source, foreign issuer or day")
        seen.add((day,sid))
        observed_neon[day].add(sid)
        labels[tag]+=1
    if (sum(bool(v) for v in observed_neon.values())!=28
            or sum(labels.values())!=EXPECTED_NEON_ROWS):
        raise ValueError("2021 Neon-only previous 28 source-day receipt drifted")
    total_neon=0
    total_aes=0
    total_overlap=0
    total_union=0
    per_stock=Counter()
    monthly={}
    for d in EXPECTED_DAYS:
        aes=aes_by_day[d]
        neon=observed_neon[d]
        both=aes&neon
        union=aes|neon
        n_a,n_n,n_b,n_u=len(aes),len(neon),len(both),len(union)
        if not n_u==n_a+n_n-n_b or n_u>1092:
            raise ValueError("Impossible 2021 source stock-date union")
        total_aes+=n_a
        total_neon+=n_n
        total_overlap+=n_b
        total_union+=n_u
        per_stock.update(union)
        m=d.strftime("%Y-%m")
        bucket=monthly.setdefault(m,{
            "observed_official_source_days":0,
            "owner_aes_current_stock_date_pairs":0,
            "neon_current_stock_date_pairs":0,
            "duplicate_aes_neon_stock_date_pairs":0,
            "neon_new_stock_date_pairs_not_in_aes":0,
            "union_unique_current_stock_date_pairs":0,
            "minimum_union_current_stocks_per_source_day":1092,
            "maximum_union_current_stocks_per_source_day":0,
        })
        bucket["observed_official_source_days"]+=1
        bucket["owner_aes_current_stock_date_pairs"]+=n_a
        bucket["neon_current_stock_date_pairs"]+=n_n
        bucket["duplicate_aes_neon_stock_date_pairs"]+=n_b
        bucket["neon_new_stock_date_pairs_not_in_aes"]+=n_n-n_b
        bucket["union_unique_current_stock_date_pairs"]+=n_u
        bucket["minimum_union_current_stocks_per_source_day"]=min(
            bucket["minimum_union_current_stocks_per_source_day"],n_u)
        bucket["maximum_union_current_stocks_per_source_day"]=max(
            bucket["maximum_union_current_stocks_per_source_day"],n_u)
    hist={str(i):0 for i in range(29)}
    for sid in roster:
        hist[str(per_stock[sid])]+=1
    if (total_aes!=EXPECTED_AES_PAIRS or total_neon!=EXPECTED_NEON_ROWS
            or total_union!=total_aes+total_neon-total_overlap
            or sum(hist.values())!=1092
            or sum(int(k)*v for k,v in hist.items())!=total_union
            or sum(b["union_unique_current_stock_date_pairs"]
                   for b in monthly.values())!=total_union
            or sum(b["observed_official_source_days"]
                   for b in monthly.values())!=28):
        raise ValueError("2021 source stock/day AES + Neon union failed exact reconciliation")
    return {
        "schema_version":1,"scope":SCOPE,
        "study_asof":"2026-11-23",
        "study_rolling_five_year_start_inclusive":"2021-11-23",
        "study_rolling_five_year_end_exclusive":"2026-11-23",
        "official_current_twse_survivor_eligible_count":1092,
        "authenticated_2021_aes_source_days":28,
        "valid_neon_2021_source_days":28,
        "aes_current_stock_source_date_pairs":total_aes,
        "neon_current_stock_source_date_pairs":total_neon,
        "duplicated_aes_neon_current_stock_date_pairs":total_overlap,
        "new_neon_current_stock_date_pairs_outside_aes":total_neon-total_overlap,
        "unique_aes_plus_neon_2021_stock_date_pairs":total_union,
        "aes_plus_neon_current_stocks_with_all_28_source_days":sum(
            per_stock[s]==28 for s in roster),
        "aes_plus_neon_current_stocks_with_at_least_26_source_days":sum(
            per_stock[s]>=26 for s in roster),
        "aes_plus_neon_current_stocks_with_zero_2021_source_days":hist["0"],
        "neon_2021_valid_source_tag_counts":dict(sorted(labels.items())),
        "monthly_aes_neon_source_stock_date_union_density":monthly,
        "owner_private_union_stock_2021_observed_source_day_histogram":hist,
        "previous_pr241_receipt_fully_reauthenticated":True,
        "2021_current_cohort_aes_neon_deduplicated_stock_day_union_verified":True,
        "source_key_union_not_price_or_volume_economic_parity":True,
        "historic_asof_listed_universe_and_ipo_eligibility_not_proven":True,
        "2021_zero_source_stocks_not_confirmed_missing_data":True,
        "owner_aes_raw_prices_not_stored_in_neon_by_this_process":True,
        "no_official_halt_auto_classification_or_price_imputation":True,
        "full_five_year_and_corporate_action_total_return_not_verified":True,
        "model_walkforward_holdout_not_verified":True,
        "production_neon_writes":0,"line_messages_sent":0,
        "paid_service_used":False,"model_release":"BLOCKED",
    }


def run_local(*,archive_2021,vault,baseline_path,prior_241_path,
              output,database_url,today=None):
    now=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if (type(now) is not date
            or not date(2026,11,23)<=now<=date(2026,12,7)):
        raise ValueError("2026-11-23 historical five-year receipt expired")
    source=_private_file(baseline_path,should_exist=True)
    prev=_private_file(prior_241_path,should_exist=True)
    out=_private_file(output,should_exist=False)
    if len({source,prev,out})!=3:
        raise ValueError("Source and new owner-private paths must differ")
    baseline=json.loads(source.read_text(encoding="utf-8"))
    accepted=json.loads(prev.read_text(encoding="utf-8"))
    verify_previous_baseline(baseline)
    validate_immutable_241(accepted)
    files=_private_archives(archive_2021)
    if out in files or prev in files or source in files:
        raise ValueError("2021 AES private archive and reports must not overlap")
    hex_key=resolve_archive_key(
        vault_path=Path(vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
    before={p.name:sha256(p.read_bytes()).hexdigest() for p in files}
    proof=authenticated_archive_days(
        files,hex_key=hex_key,start=date(2021,11,23),end=date(2022,1,1))
    if proof.get("full_file_integrity_verified") is not True or (
            proof.get("days")!=frozenset(EXPECTED_DAYS)):
        raise ValueError("Original owner 2021 AES 28-day cryptographic evidence changed")
    roster,neon_rows=capture_neon_2021(database_url)
    allowed=set(roster)
    aes={d:set() for d in EXPECTED_DAYS}
    total_source_rows=0
    for file in files:
        def collect(row):
            nonlocal total_source_rows
            total_source_rows+=1
            d,sid=row["trade_date"],row["stock_id"]
            if total_source_rows>MAX_SOURCE_ROWS or d not in aes:
                raise ValueError("Malformed 2021 AES day or unbounded source row")
            if sid in allowed:
                if sid in aes[d]:
                    raise ValueError("Duplicated owner 2021 AES stock/day source key")
                aes[d].add(sid)
        verified=verify_archive(file,hex_key=hex_key,on_verified_row=collect)
        if verified.get("archive_integrity_verified") is not True:
            raise ValueError("Owner 2021 AES footer cryptographic integrity failed")
    after={p.name:sha256(p.read_bytes()).hexdigest() for p in files}
    if before!=after:
        raise ValueError("Owner 2021 AES bytes mutated during reading")
    reverified=evaluate_2021_aes_current_cohort(
        baseline,eligible=roster,source_days=set(EXPECTED_DAYS),
        per_day_stocks=aes,source_rows=total_source_rows,aes_file_hashes=before)
    report=reconcile_union(
        baseline,accepted,roster=roster,aes_by_day=aes,
        neon_rows=neon_rows,reverified_241=reverified)
    payload=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if len(payload.encode("utf-8"))>MAX_REPORT_BYTES:
        raise ValueError("Owner AES+Neon 2021 source-key union report oversized")
    with out.open("x",encoding="utf-8") as fp:
        fp.write(payload)
    print(json.dumps({
        "status":"TWSE_2021_ALL_28_AES_NEON_DEDUPED_CURRENT_COHORT_STOCK_DATE_UNION_PASS",
        "aes_source_stock_days":report["aes_current_stock_source_date_pairs"],
        "neon_source_stock_days":report["neon_current_stock_source_date_pairs"],
        "overlapping_source_stock_days":report[
            "duplicated_aes_neon_current_stock_date_pairs"],
        "incremental_neon_source_stock_days":report[
            "new_neon_current_stock_date_pairs_outside_aes"],
        "unique_source_stock_days":report[
            "unique_aes_plus_neon_2021_stock_date_pairs"],
        "all_28_source_days_current_stocks":report[
            "aes_plus_neon_current_stocks_with_all_28_source_days"],
        "no_2021_source_stocks":report[
            "aes_plus_neon_current_stocks_with_zero_2021_source_days"],
        "historical_ipo_or_halt_status_proven":False,
        "neon_writes":0,"line_messages_sent":0,"model_release":"BLOCKED",
    },ensure_ascii=False))


def main():
    cli=argparse.ArgumentParser(description=
        "Owner-only 2021 AES+Neon 28 source-day current-stock/date dedup, read only")
    cli.add_argument("--archive-2021",required=True)
    cli.add_argument("--key-vault",required=True)
    cli.add_argument("--five-year-neon-report",required=True)
    cli.add_argument("--prior-241-aes-report",required=True)
    cli.add_argument("--out",required=True)
    a=cli.parse_args()
    try:
        run_local(
            archive_2021=a.archive_2021,vault=a.key_vault,
            baseline_path=a.five_year_neon_report,
            prior_241_path=a.prior_241_aes_report,
            output=a.out,database_url=os.environ.get("DATABASE_URL",""))
    except Exception:
        raise SystemExit("Private 2021 AES+Neon source/date union FAILED; "
                         "no price, Neon URI, vault password or LINE output") from None


if __name__=="__main__":
    main()
