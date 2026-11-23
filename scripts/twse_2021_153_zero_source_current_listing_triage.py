"""Owner-only 153 current TWSE stocks absent from authenticated 2021 source days.

Triage current official TWSE listing dates for the 2021 Nov23-Dec30
28-day AES+Neon **zero-source** cohort. Official *current* listing date
does not equal original IPO, initial tradability, historic PIT or proof of
missing stock OHLCV. Do not impute prices, modify Neon or send LINE.
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
    EXPECTED_DAYS, MAX_SOURCE_ROWS, evaluate_2021_aes_current_cohort,
)
from scripts.twse_2021_28day_aes_neon_stockdate_union_readonly import (
    BEGIN, END, SCOPE as PRIOR_UNION_SCOPE, capture_neon_current_2021_readonly,
    evaluate_2021_union,
)
from scripts.twse_2022_official_current_listing_date_triage import (
    URL as LISTING_URL, MIN_OFFICIAL_RECORDS, MAX_OFFICIAL_RECORDS,
    _listing_day, _roc_snapshot_day, fetch_official_company_basics,
)
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key

SCOPE="OWNER_2021_TWSE_153_ZERO_SOURCE_CURRENT_OFFICIAL_LISTING_DATE_TRIAGE"
MAX_OUTPUT_BYTES=68_000
MAX_AGE_DAYS=14
EXPECTED_2021_AES_DAYS=28
EXPECTED_NO_SOURCE_STOCKS=153

def classify_2021_current_listing_dates(
        *, previous_union, current_roster, aes_by_day, neon_rows,
        official_basics, current_day):
    """Pure aggregate/bounded-private result for 153 absent 2021 source stocks."""
    if (not isinstance(previous_union,dict)
            or previous_union.get("schema_version")!=1
            or previous_union.get("scope")!=PRIOR_UNION_SCOPE
            or previous_union.get("actual_deduplicated_aes_neon_stock_date_pairs")!=26120
            or previous_union.get("aes_neon_overlapping_source_stock_date_pairs")!=552
            or previous_union.get("neon_exclusive_source_stock_date_pairs")!=0
            or previous_union.get("current_stocks_with_all_28_original_source_dates")!=900
            or previous_union.get("current_stocks_with_at_least_26_of_28_source_dates")!=916
            or previous_union.get("current_stocks_with_no_source_day_in_2021")!=153
            or previous_union.get("model_release")!="BLOCKED"
            or previous_union.get("production_neon_writes")!=0
            or previous_union.get("line_messages_sent")!=0):
        raise ValueError("Frozen owner 2021 AES/Neon union receipt not accepted")
    if (not isinstance(current_roster,(tuple,list))
            or len(current_roster)!=1092
            or len(set(current_roster))!=1092
            or any(not isinstance(s,str) or not re.fullmatch(r"\d{4}",s)
                   or s=="1589" for s in current_roster)
            or not isinstance(aes_by_day,dict)
            or set(aes_by_day)!=set(EXPECTED_DAYS)
            or not isinstance(neon_rows,(tuple,list))
            or len(neon_rows)!=552):
        raise ValueError("Actual owner original 2021 source-key cohort changed")
    valid=set(current_roster)
    source_seen=set()
    for d, stocks in aes_by_day.items():
        if type(d) is not date or not isinstance(stocks,set) or not stocks<=valid:
            raise ValueError("Forged 2021 source day or ineligible ticker")
        source_seen.update(stocks)
    neon_seen=set()
    for entry in neon_rows:
        if not isinstance(entry,(tuple,list)) or len(entry)!=3:
            raise ValueError("Malformed Neon 2021 stock-date source evidence")
        d,sid,tag=entry
        if (type(d) is not date or d not in aes_by_day or
                sid not in valid or tag not in (
                    "TWSE_STOCK_DAY","TWSE_MI_INDEX_ALLBUT0999")):
            raise ValueError("Invalid Neon 2021 accepted-source observation")
        neon_seen.add(sid)
    without=valid-source_seen-neon_seen
    if len(without)!=EXPECTED_NO_SOURCE_STOCKS:
        raise ValueError("Owner original 153 absent 2021 TWSE issuers changed")

    if (type(current_day) is not date
            or not date(2026,11,23)<=current_day<=date(2026,12,7)
            or not isinstance(official_basics,dict)
            or official_basics.get("endpoint")!=LISTING_URL
            or not re.fullmatch(r"[a-f0-9]{64}",
                                str(official_basics.get("response_sha256","")))
            or not isinstance(official_basics.get("rows"),list)
            or not MIN_OFFICIAL_RECORDS<=len(official_basics["rows"])<=MAX_OFFICIAL_RECORDS):
        raise ValueError("Current official TWSE company metadata proof invalid")
    listings={}
    publication=None
    for obj in official_basics["rows"]:
        if not isinstance(obj,dict):
            raise ValueError("Invalid TWSE current company basic row")
        sid=obj.get("公司代號")
        if not isinstance(sid,str) or not re.fullmatch(r"\d{4}",sid):
            continue
        if sid in listings:
            raise ValueError("Duplicated official current TWSE company stock code")
        observed=_roc_snapshot_day(obj.get("出表日期"))
        if publication is None:
            publication=observed
        elif publication!=observed:
            raise ValueError("Mixed publication dates in official current listing")
        listings[sid]=_listing_day(obj.get("上市日期"))
    if (publication is None or not 0<=(current_day-publication).days<=MAX_AGE_DAYS
            or len(listings)<MIN_OFFICIAL_RECORDS):
        raise ValueError("Stale official current-listed company listing metadata")
    boundaries={
        "current_listing_on_or_before_first_2021_source_day":0,
        "current_listing_between_first_and_last_2021_source_days":0,
        "current_listing_after_last_2021_source_day_in_2021":0,
        "current_listing_in_2022":0,
        "current_listing_in_2023":0,
        "current_listing_in_2024":0,
        "current_listing_in_2025":0,
        "current_listing_in_2026":0,
        "current_listing_date_missing_or_invalid":0,
    }
    rows=[]
    for sid in sorted(without):
        day=listings.get(sid)
        if day is None:
            category="current_listing_date_missing_or_invalid"
        elif day>current_day:
            raise ValueError("Future current listing date cannot certify historical source")
        elif day<=min(EXPECTED_DAYS):
            category="current_listing_on_or_before_first_2021_source_day"
        elif day<=max(EXPECTED_DAYS):
            category="current_listing_between_first_and_last_2021_source_days"
        elif day.year==2021:
            category="current_listing_after_last_2021_source_day_in_2021"
        elif 2022<=day.year<=2026:
            category=f"current_listing_in_{day.year}"
        else:
            raise ValueError("Unsupported official issuer listing date bucket")
        boundaries[category]+=1
        rows.append({
            "stock_id":sid,
            "current_twse_official_listing_date":day.isoformat() if day else None,
            "current_listing_date_category":category,
            "no_valid_2021_source_day_observed":True,
            "historical_2021_listing_or_trading_obligation_proven":False,
            "price_repair_or_deletion_authorized":False,
        })
    if len(rows)!=153 or sum(boundaries.values())!=153:
        raise ValueError("2021 no-source current listing categories do not reconcile")
    concern=(boundaries["current_listing_on_or_before_first_2021_source_day"]
             +boundaries["current_listing_between_first_and_last_2021_source_days"]
             +boundaries["current_listing_date_missing_or_invalid"])
    return {
        "schema_version":1,
        "scope":SCOPE,
        "original_five_year_window_start":"2021-11-23",
        "original_five_year_window_end_exclusive":"2026-11-23",
        "authenticated_2021_source_days":28,
        "prior_revalidated_2021_aes_neon_deduplicated_stock_date_pairs":26120,
        "currently_eligible_twse_stocks_excluding_1589":1092,
        "no_2021_aes_or_neon_source_issuer_count":153,
        "official_current_listing_company_endpoint":LISTING_URL,
        "official_company_data_response_sha256":official_basics[
            "response_sha256"],
        "official_company_data_observed_at":publication.isoformat(),
        "official_listed_company_rows":len(listings),
        "current_listing_year_and_period_bucket_counts":boundaries,
        "zero_source_2021_prioritize_manual_historical_listing_research":concern,
        "owner_private_153_zero_source_current_stock_listing_date_rows":rows,
        "current_official_listing_date_is_not_first_ipo_or_historic_pit":True,
        "otc_transfer_relisting_board_conversion_possible":True,
        "source_absence_not_necessarily_an_ohlcv_data_gap":True,
        "historic_delisted_membership_not_included_in_current_cohort":True,
        "official_historic_listing_or_trading_obligation_verified":False,
        "zero_price_imputation_or_deleted_source_bars":True,
        "production_neon_writes":0,
        "line_messages_sent":0,
        "paid_services_used":False,
        "model_release":"BLOCKED",
    }


def run_owner(*, archive_2021, key_vault, prior_241_report,
              prior_5y_report, prior_243_report, out, db_url,
              today=None):
    current_day=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    source=_private_file(prior_241_report,should_exist=True)
    five=_private_file(prior_5y_report,should_exist=True)
    union=_private_file(prior_243_report,should_exist=True)
    output=_private_file(out,should_exist=False)
    archives=_private_archives(archive_2021)
    if (len({source,five,union,output})!=4
            or any(p in (source,five,union,output) for p in archives)):
        raise ValueError("Private immutable AES, prior and output paths must differ")
    old_241=json.loads(source.read_text(encoding="utf-8"))
    old_5y=json.loads(five.read_text(encoding="utf-8"))
    old_243=json.loads(union.read_text(encoding="utf-8"))
    key=resolve_archive_key(
        vault_path=Path(key_vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""))
    aes_hashes={p.name:sha256(p.read_bytes()).hexdigest() for p in archives}
    source_days=authenticated_archive_days(
        archives,hex_key=key,start=BEGIN,end=END)
    if (source_days.get("full_file_integrity_verified") is not True
            or source_days["days"]!=frozenset(EXPECTED_DAYS)):
        raise ValueError("Official 28 source-day 2021 AES authentication drifted")
    roster, neon=capture_neon_current_2021_readonly(db_url)
    valid=set(roster)
    aes={d:set() for d in EXPECTED_DAYS}
    counter=0
    for archive in archives:
        def on_row(row):
            nonlocal counter
            counter+=1
            d,sid=row["trade_date"],row["stock_id"]
            if d not in aes or counter>MAX_SOURCE_ROWS:
                raise ValueError("Authenticated 2021 local source-year rows invalid")
            if sid in valid:
                if sid in aes[d]:
                    raise ValueError("Duplicate authenticated 2021 AES stock-date source key")
                aes[d].add(sid)
        proof=verify_archive(archive,hex_key=key,on_verified_row=on_row)
        if proof.get("archive_integrity_verified") is not True:
            raise ValueError("Original encrypted 2021 source footer failed")
    if {p.name:sha256(p.read_bytes()).hexdigest() for p in archives}!=aes_hashes:
        raise ValueError("Original encrypted source bytes changed during authentication")
    check_241=evaluate_2021_aes_current_cohort(
        old_5y,eligible=roster,source_days=set(EXPECTED_DAYS),
        per_day_stocks=aes,source_rows=counter,aes_file_hashes=aes_hashes)
    check_243=evaluate_2021_union(
        prior_aes=old_241,prior_neon=old_5y,
        recomputed_aes=check_241,roster=roster,
        aes_by_day=aes,neon_rows=neon)
    if check_241!=old_241 or check_243!=old_243:
        raise ValueError("Owner PR241 / PR243 source receipts not reproduced exactly")
    basics=fetch_official_company_basics()
    output_report=classify_2021_current_listing_dates(
        previous_union=old_243,current_roster=roster,
        aes_by_day=aes,neon_rows=neon,
        official_basics=basics,current_day=current_day)
    payload=json.dumps(output_report,ensure_ascii=False,indent=2,
                       allow_nan=False)+"\n"
    if len(payload.encode("utf-8"))>MAX_OUTPUT_BYTES:
        raise ValueError("Owner private 153-source listing research report too large")
    with output.open("x",encoding="utf-8") as fp:
        fp.write(payload)
    print(json.dumps({
        "status":"TWSE_2021_153_ZERO_SOURCE_CURRENT_OFFICIAL_LISTING_TRIAGE_PASS",
        "revalidated_aes_neon_union_stock_date_pairs":26120,
        "no_2021_source_stock_count":153,
        "current_listing_category_counts":output_report[
            "current_listing_year_and_period_bucket_counts"],
        "requires_manual_historical_listing_research":output_report[
            "zero_source_2021_prioritize_manual_historical_listing_research"],
        "proven_historical_ipo_halt_or_price_data_gap":False,
        "neon_writes":0,"line_messages_sent":0,
        "model_release":"BLOCKED",
    },ensure_ascii=False))


def main():
    ap=argparse.ArgumentParser(
        description="Owner-only zero-2021-source 153 stock current TWSE listing dates; 2021 AES+Neon replay and read-only proof")
    ap.add_argument("--archive-2021",required=True)
    ap.add_argument("--key-vault",required=True)
    ap.add_argument("--prior-241-aes-report",required=True)
    ap.add_argument("--prior-five-year-neon-report",required=True)
    ap.add_argument("--prior-243-union-report",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    try:
        run_owner(
            archive_2021=args.archive_2021,
            key_vault=args.key_vault,
            prior_241_report=args.prior_241_aes_report,
            prior_5y_report=args.prior_five_year_neon_report,
            prior_243_report=args.prior_243_union_report,
            out=args.out,db_url=os.environ.get("DATABASE_URL",""))
    except Exception:
        raise SystemExit(
            "Owner 2021 153 current-listing-date zero-source triage FAILED; "
            "no Neon/LINE changes, no AES key or database URI disclosed"
        ) from None


if __name__=="__main__":
    main()
