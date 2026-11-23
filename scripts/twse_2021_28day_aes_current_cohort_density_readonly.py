"""Owner 2021 AES 28-session current-stock source-key coverage, no write.

The frozen rolling five-year baseline starts 2021-11-23 and ends 2026-11-23
(exclusive). Original 2021 current-survivor Neon-only has just 552 valid
stock-days on 28 dates, but owner AES privately holds 28 official whole-market
source sessions. Reauthenticate AES and one READ ONLY current-TWSE roster;
never call an external provider or export price values or issuer identities.

Source observation is not historical listing eligibility, proof of complete
issuer-level five-year panel or approval to adjust price/corporate actions.
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

from scripts.twse_2021_owner_local_fast_archive import ALL_2021_DAYS
from scripts.twse_2021_22_traded_240_warmup_readonly import (
    _private_archives,_private_file,
)
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_tpex_five_year_neon_only_cohort_readonly import (
    SCOPE as FIVE_YEAR_SCOPE,
)
from scripts.twse_2022_aes_neon_eligible_density_readonly import ELIGIBLE_SQL

SCOPE="OWNER_TWSE_2021_28_REAL_AES_SOURCE_DATE_CURRENT_COHORT_DENSITY_READONLY"
EXPECTED_DAYS=tuple(ALL_2021_DAYS)
MAX_SOURCE_ROWS=45_000
MAX_OUTPUT_BYTES=13000
KNOWN_NEON_2021_SOURCE_STOCK_DAYS=552
KNOWN_NEON_2021_OBSERVED_DAYS=28


def verify_previous_baseline(previous):
    if (not isinstance(previous,dict)
            or previous.get("schema_version")!=1
            or previous.get("scope")!=FIVE_YEAR_SCOPE
            or previous.get("window_start_inclusive")!="2021-11-23"
            or previous.get("window_end_exclusive")!="2026-11-23"
            or previous.get("current_listed_issuers_only_not_historical_pit_membership") is not True
            or previous.get("owner_aes_2021_2022_source_not_included") is not True
            or previous.get("model_release")!="BLOCKED"
            or previous.get("production_neon_writes")!=0
            or previous.get("line_messages_sent")!=0):
        raise ValueError("2026-11-23 original Neon-only five-year baseline drifted")
    twse=previous.get("market",{}).get("twse")
    if (not isinstance(twse,dict)
            or twse.get("official_current_listed_stocks_excluding_1589")!=1092
            or not isinstance(twse.get("yearly_neon_source_observations"),list)):
        raise ValueError("Original 2021 official TWSE current-survivor cohort mismatch")
    year=[x for x in twse["yearly_neon_source_observations"]
          if isinstance(x,dict) and x.get("year")==2021]
    if (len(year)!=1 or
            year[0].get("days_with_any_neon_eligible_source_bars")!=28
            or year[0].get("days_with_at_least_500_eligible_source_bars")!=0
            or year[0].get("neon_stored_valid_source_stock_bars")!=552):
        raise ValueError("Prior immutable 2021 Neon source baseline changed")
    return True


def evaluate_2021_aes_current_cohort(
        prior,*,eligible, source_days, per_day_stocks,
        source_rows, aes_file_hashes):
    verify_previous_baseline(prior)
    if (not isinstance(eligible,(list,tuple)) or len(eligible)!=1092
            or len(set(eligible))!=len(eligible)
            or any(not isinstance(s,str) or not re.fullmatch(r"\d{4}",s)
                   or s=="1589" for s in eligible)
            or not isinstance(source_days,(set,frozenset))
            or source_days!=set(EXPECTED_DAYS)
            or not isinstance(per_day_stocks,dict)
            or set(per_day_stocks)!=source_days
            or type(source_rows) is not int
            or not 28*500<=source_rows<=MAX_SOURCE_ROWS
            or not isinstance(aes_file_hashes,dict)
            or not 1<=len(aes_file_hashes)<=72
            or any(not isinstance(v,str) or not re.fullmatch(r"[a-f0-9]{64}",v)
                   for v in aes_file_hashes.values())):
        raise ValueError("Unverified 2021 owner AES 28-day cohort or source integrity")
    cohort=set(eligible)
    full_days=len(source_days)
    count=Counter()
    month={}
    for day in sorted(source_days):
        securities=per_day_stocks[day]
        if not isinstance(securities,set) or not securities<=cohort:
            raise ValueError("Original 2021 AES contains foreign issuer / invalid date")
        if not 500<=len(securities)<=len(cohort):
            raise ValueError("Insufficient current-listed original AES stock coverage")
        count.update(securities)
        item=month.setdefault(day.strftime("%Y-%m"),{
            "authenticated_source_days":0,
            "minimum_current_stock_valid_source_rows":len(cohort),
            "maximum_current_stock_valid_source_rows":0,
            "current_stock_day_presence_pairs":0,
        })
        item["authenticated_source_days"]+=1
        item["minimum_current_stock_valid_source_rows"]=min(
            item["minimum_current_stock_valid_source_rows"],len(securities))
        item["maximum_current_stock_valid_source_rows"]=max(
            item["maximum_current_stock_valid_source_rows"],len(securities))
        item["current_stock_day_presence_pairs"]+=len(securities)
    hist={str(i):0 for i in range(29)}
    for stock in cohort:
        hist[str(count[stock])]+=1
    stocks_full=sum(count[s]==28 for s in cohort)
    stocks_26plus=sum(count[s]>=26 for s in cohort)
    pairs=sum(count.values())
    if (sum(hist.values())!=1092 or
            sum(int(days)*v for days,v in hist.items())!=pairs
            or sum(x["current_stock_day_presence_pairs"] for x in month.values())!=pairs
            or sum(x["authenticated_source_days"] for x in month.values())!=28
            or stocks_full>stocks_26plus):
        raise ValueError("Reconciled original 2021 current-stock source panel changed")
    return {
        "schema_version":1,"scope":SCOPE,
        "rolling_baseline_asof":"2026-11-23",
        "five_year_baseline_window_start":"2021-11-23",
        "five_year_baseline_window_end_exclusive":"2026-11-23",
        "2021_window_first_authenticated_source_day":min(source_days).isoformat(),
        "2021_window_last_authenticated_source_day":max(source_days).isoformat(),
        "authenticated_2021_owner_aes_source_days":28,
        "2021_owner_aes_valid_source_rows_all_current_at_capture":source_rows,
        "2021_aes_current_2026_twse_survivor_eligible_count":1092,
        "2021_aes_current_2026_twse_stock_date_presence_pairs":pairs,
        "2021_2026_current_stocks_with_all_28_observed_source_days":stocks_full,
        "2021_2026_current_stocks_with_at_least_26_of_28_days":stocks_26plus,
        "2021_2026_current_stocks_with_no_2021_source_day":hist["0"],
        "2021_current_cohort_per_stock_source_days_histogram":hist,
        "monthly_authenticated_2021_current_cohort_source_density":month,
        "number_authenticated_2021_local_aes_files":len(aes_file_hashes),
        "authenticated_local_aes_bundle_hash_sha256":sha256(
            json.dumps(sorted(aes_file_hashes.values()),
                       separators=(",",":")).encode()).hexdigest(),
        "neon_only_source_stock_date_count_in_2021_prior":552,
        "neon_only_not_equal_aes_plus_neon":True,
        "2021_current_cohort_aes_neon_deduplicated_stock_day_union_verified":False,
        "source_days_do_not_prove_all_issuer_ipo_or_tradability":True,
        "source_days_are_not_standalone_independent_historical_market_calendar":True,
        "historic_2021_unlisted_and_delisted_issuers_out_of_scope":True,
        "individual_ohlcv_and_total_returns_adjusted":False,
        "2022_2026_full_panel_model_validation_complete":False,
        "production_neon_writes":0,"line_messages_sent":0,
        "paid_services_used":False,"model_release":"BLOCKED",
    }


def _capture_current_roster_readonly(database_url):
    if not isinstance(database_url,str) or not database_url.startswith(
            ("postgres://","postgresql://")):
        raise ValueError("Private owner Neon URI required for official current cohort")
    import psycopg
    with psycopg.connect(database_url,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='30000ms'")
            cur.execute(ELIGIBLE_SQL)
            names=[r[0] for r in cur.fetchall()]
        conn.rollback()
    return names


def run_owner(*,dir_2021,key_vault,prior_report,output,database_url,
              today=None):
    now=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if (type(now) is not date or
            not date(2026,11,23)<=now<=date(2026,12,7)):
        raise ValueError("Frozen 2026-11-23 study receipt is too old")
    files=_private_archives(dir_2021)
    src=_private_file(prior_report,should_exist=True)
    out=_private_file(output,should_exist=False)
    if any(p==out or p==src for p in files) or src==out:
        raise ValueError("Private AES/receipt/output paths must differ")
    previous=json.loads(src.read_text(encoding="utf-8"))
    verify_previous_baseline(previous)
    key=resolve_archive_key(vault_path=Path(key_vault),
                            env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
    hashes={p.name:sha256(p.read_bytes()).hexdigest() for p in files}
    proof=authenticated_archive_days(
        files,hex_key=key,
        start=date(2021,11,23),end=date(2022,1,1))
    if (proof["full_file_integrity_verified"] is not True
            or proof["days"]!=frozenset(EXPECTED_DAYS)):
        raise ValueError("Original owner 2021 28 source-day AES proof drifted")
    roster=_capture_current_roster_readonly(database_url)
    allowed=set(roster)
    data={d:set() for d in EXPECTED_DAYS}
    counter=0
    for file in files:
        def accept(row):
            nonlocal counter
            counter+=1
            day=row["trade_date"]
            sid=row["stock_id"]
            if day not in data or counter>MAX_SOURCE_ROWS:
                raise ValueError("Original 2021 date/stock keys outside accepted source")
            if sid in allowed:
                if sid in data[day]:
                    raise ValueError("Duplicate 2021 original stock/day source row")
                data[day].add(sid)
        result=verify_archive(file,hex_key=key,on_verified_row=accept)
        if result.get("archive_integrity_verified") is not True:
            raise ValueError("Original 2021 encrypted archive failed footer authentication")
    if {p.name:sha256(p.read_bytes()).hexdigest() for p in files}!=hashes:
        raise ValueError("2021 AES source bytes changed during study")
    report=evaluate_2021_aes_current_cohort(
        previous,eligible=roster,source_days=set(EXPECTED_DAYS),
        per_day_stocks=data,source_rows=counter,aes_file_hashes=hashes)
    payload=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if len(payload.encode("utf-8"))>MAX_OUTPUT_BYTES:
        raise ValueError("2021 owner-private panel density report too large")
    with out.open("x",encoding="utf-8") as f:
        f.write(payload)
    print(json.dumps({
        "status":"TWSE_2021_ALL_28_AES_CURRENT_COHORT_DENSITY_READONLY_PASS",
        "2021_aes_source_days":28,
        "2021_current_cohort_stock_date_presence_pairs":report[
            "2021_aes_current_2026_twse_stock_date_presence_pairs"],
        "2021_current_stocks_present_on_all_28_days":report[
            "2021_2026_current_stocks_with_all_28_observed_source_days"],
        "2021_neon_only_source_stock_days":552,
        "2021_aes_neon_dedup_union_verified":False,
        "neon_writes":0,"line_messages_sent":0,
        "model_release":"BLOCKED",
    },ensure_ascii=False))


def main():
    cli=argparse.ArgumentParser(
        description="Owner-only 2021 Nov23-Dec30 28 AES date current-listed TWSE stock coverage, production Neon READ ONLY roster")
    cli.add_argument("--archive-2021",required=True)
    cli.add_argument("--key-vault",required=True)
    cli.add_argument("--five-year-neon-report",required=True)
    cli.add_argument("--out",required=True)
    args=cli.parse_args()
    try:
        run_owner(
            dir_2021=args.archive_2021,key_vault=args.key_vault,
            prior_report=args.five_year_neon_report,output=args.out,
            database_url=os.environ.get("DATABASE_URL",""),
        )
    except Exception:
        raise SystemExit(
            "Owner 2021 whole-market AES per-stock coverage FAILED; "
            "no price, password, Neon URI, LINE or target-stock IDs leaked"
        ) from None


if __name__=="__main__":
    main()
