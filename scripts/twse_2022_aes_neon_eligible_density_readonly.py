"""Owner-local 2022 TWSE AES + Neon *per-stock-date* source-density audit.

Reauthenticates the owner-only AES 2022 records and checks existing Neon
source stock/date keys in a single server-enforced READ ONLY snapshot.
Tracks current-official-listed (not historical PIT) only, excluding 1589.
Rejects incomplete 2022 or changed owner reports; no price in output.

This DOES NOT assert that absence of a price means a true missing trading
session: historic IPOs, halts, eligibility, and corporate actions matter.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT/"src") not in sys.path:
    sys.path.insert(0, str(ROOT/"src"))

from current_official_listing import CURRENT_OFFICIAL_LISTED_CTE
from scripts.twse_2022_aes_factor_readiness import audit as audit_aes
from scripts.twse_2022_aes_neon_readonly_240_panel import _authenticated_rows
from scripts.twse_2021_22_traded_240_warmup_readonly import _private_archives, _private_file
from scripts.twse_2022_aes_neon_five_year_overlay_offline import (
    SCOPE as OVERLAY_SCOPE, reconcile_offline,
)
from scripts.twse_archive_key_vault import resolve_archive_key

SCOPE = "OWNER_2022_TWSE_AES_NEON_CURRENT_OFFICIAL_STOCK_DATE_DENSITY_RESEARCH"
BULK = "TWSE_MI_INDEX_ALLBUT0999"
SECONDARY = "TWSE_STOCK_DAY"
YEAR_START, YEAR_END = date(2022, 1, 1), date(2023, 1, 1)
MAX_REPORT_BYTES = 28000
MAX_NEON_ROWS = 180000
MAX_AES_ROWS = 600000

ELIGIBLE_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT o.stock_id FROM official_current_listed o
WHERE o.market='twse' AND o.stock_id <> '1589'
 AND NOT EXISTS (
 SELECT 1 FROM public.model_stock_exclusions x
 WHERE x.market=o.market AND x.stock_id=o.stock_id
 ) ORDER BY o.stock_id
"""
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
 AND p.trade_date >= DATE '2022-01-01'
 AND p.trade_date < DATE '2023-01-01'
 AND p.source IN ('TWSE_MI_INDEX_ALLBUT0999','TWSE_STOCK_DAY')
 AND p.close > 0 AND p.volume >= 0
ORDER BY p.trade_date,p.stock_id
"""
BULK_DATES_SQL = """
SELECT DISTINCT trade_date FROM public.daily_prices
WHERE market='twse' AND source='TWSE_MI_INDEX_ALLBUT0999'
 AND trade_date >= DATE '2022-01-01'
 AND trade_date < DATE '2023-01-01'
ORDER BY trade_date
"""

# Only a first OBSERVED valid stored stock/source date, never official IPO day.
# This adds no raw OHLCV export or source-price output. 2023+ read remains
# under the same current-official-list snapshot and READ ONLY transaction.
POST2022_FIRST_SEEN_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible AS (
 SELECT o.stock_id FROM official_current_listed o
 WHERE o.market='twse' AND o.stock_id <> '1589'
 AND NOT EXISTS (
 SELECT 1 FROM public.model_stock_exclusions x
 WHERE x.market=o.market AND x.stock_id=o.stock_id
 ))
SELECT e.stock_id,MIN(p.trade_date) AS first_observed_source_date
FROM eligible e
LEFT JOIN public.daily_prices p ON
 p.market='twse' AND p.stock_id=e.stock_id
 AND p.trade_date >= DATE '2023-01-01' AND p.trade_date < %s
 AND p.source IN ('TWSE_MI_INDEX_ALLBUT0999','TWSE_STOCK_DAY')
 AND p.close > 0 AND p.volume >= 0
GROUP BY e.stock_id ORDER BY e.stock_id
"""


def validate_owner_receipts(panel, five_year, overlay):
    expected = reconcile_offline(panel, five_year)
    if (not isinstance(overlay, dict)
            or overlay != expected
            or overlay.get("scope") != OVERLAY_SCOPE
            or overlay.get("model_release") != "BLOCKED"
            or overlay.get("complete_five_year_price_bars_verified") is not False
            or overlay.get("production_neon_writes") != 0
            or overlay.get("line_messages_sent") != 0):
        raise ValueError("Two owner receipts and 2022 source overlay have drifted")
    return expected


def capture_neon(url, *, post2022_end=None):
    """Bounded stock *identifiers* only; no raw price rows leave the DB.

    Optional post-2022 first observation uses identical read-only snapshot.
    """
    if not url or not url.startswith(("postgres://", "postgresql://")):
        raise ValueError("Protected owner Neon URL required")
    import psycopg
    with psycopg.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='90000ms'")
            cur.execute(ELIGIBLE_SQL)
            roster = [r[0] for r in cur.fetchall()]
            cur.execute(BULK_DATES_SQL)
            bulk_days = [r[0] for r in cur.fetchall()]
            cur.execute(STOCK_DATE_SQL)
            rows = []
            while True:
                batch = cur.fetchmany(5000)
                if not batch:
                    break
                rows.extend(batch)
                if len(rows) > MAX_NEON_ROWS:
                    raise ValueError("Unbounded 2022 Neon source stock/day keys")
            post2022 = None
            if post2022_end is not None:
                if (type(post2022_end) is not date
                        or not date(2023,1,2) <= post2022_end <= date(2027,1,1)):
                    raise ValueError("Bounded owner report 2023+ horizon required")
                cur.execute(POST2022_FIRST_SEEN_SQL,(post2022_end,))
                post2022 = cur.fetchall()
                if len(post2022) > 1500:
                    raise ValueError("Unbounded future first-observed source proof")
        conn.rollback()
    if post2022_end is not None:
        return roster, bulk_days, rows, post2022
    return roster, bulk_days, rows


def evaluate(panel, five_year, overlay, *, roster, aes_by_day,
             neon_bulk_days, neon_rows, source_audit, post2022_first_seen=None):
    """Pure exact stock/day union, rejecting wrong type/date/source/receipt."""
    prior = validate_owner_receipts(panel, five_year, overlay)
    if (not isinstance(roster,(list,tuple)) or len(roster)!=1092
            or len(set(roster))!=len(roster)
            or any(not isinstance(s,str) or not re.fullmatch(r"\d{4}",s)
                   or s=="1589" for s in roster)):
        raise ValueError("Current officially listed 2022 research roster changed")
    allowed = set(roster)
    if (not isinstance(source_audit,dict)
            or source_audit.get("authenticated_source_rows") !=
               panel.get("local_authenticated_source_rows")
            or source_audit.get("authentic_distinct_2022_source_sessions") != 162
            or source_audit.get("neon_connections") != 0
            or source_audit.get("neon_rows_written") != 0
            or source_audit.get("live_model_release_decision") != "BLOCKED"):
        raise ValueError("Reauthenticated AES count or source block changed")

    if not isinstance(aes_by_day,dict) or len(aes_by_day)!=162:
        raise ValueError("2022 owner private AES source dates missing")
    local_days = set()
    for day, stocks in aes_by_day.items():
        if (type(day) is not date or not YEAR_START<=day<YEAR_END
                or day.weekday() >= 5 or day in local_days
                or not isinstance(stocks,set) or not stocks<=allowed):
            raise ValueError("Invalid local AES source-date/official-listing set")
        local_days.add(day)

    if (not isinstance(neon_bulk_days,(list,tuple))
            or len(neon_bulk_days)!=84
            or len(set(neon_bulk_days))!=84
            or any(type(d) is not date or not YEAR_START<=d<YEAR_END
                   or d.weekday()>=5 for d in neon_bulk_days)):
        raise ValueError("Previous 84 official Neon bulk source dates not recovered")
    bulk = set(neon_bulk_days)
    if local_days & bulk or len(local_days|bulk)!=246:
        raise ValueError("Owner 162 AES / 84 bulk dates conflict or overlap")
    if min(local_days|bulk)!=date(2022,1,3) or max(local_days|bulk)!=date(2022,12,30):
        raise ValueError("Authenticated source-year boundary was altered")

    neon_by_day = {}
    neon_bulk_current = set()
    count = 0
    seen = set()
    for item in neon_rows:
        if not isinstance(item,(tuple,list)) or len(item)!=3:
            raise ValueError("Neon stock/date identifier shape invalid")
        day,sid,source = item
        if (type(day) is not date or not YEAR_START<=day<YEAR_END
                or day.weekday()>=5 or sid not in allowed
                or source not in (BULK, SECONDARY) or (day,sid) in seen):
            raise ValueError("Duplicate/foreign/unverified Neon source stock/date")
        seen.add((day,sid))
        neon_by_day.setdefault(day,set()).add(sid)
        if source==BULK:
            neon_bulk_current.add(day)
        count += 1
        if count>MAX_NEON_ROWS:
            raise ValueError("Neon source exceeds bounded row budget")

    neon_2022 = {y["year"]:y for y in five_year["market"]["twse"][
        "yearly_neon_source_observations"]}
    expected = neon_2022[2022]
    observed_days = expected["days_with_any_neon_eligible_source_bars"]
    expected_dense = expected["days_with_at_least_500_eligible_source_bars"]
    expected_rows = expected["neon_stored_valid_source_stock_bars"]
    dense_neon = {
        d for d,s in neon_by_day.items() if len(s)>=500
    }
    if (len(neon_by_day)!=observed_days or
            len(dense_neon)!=expected_dense or count!=expected_rows or
            observed_days!=246 or expected_dense!=84 or expected_rows!=83294):
        raise ValueError("Five-year 2022 Neon snapshot/source keys changed")
    if not neon_bulk_current <= bulk:
        raise ValueError("Official bulk source day outside original Neon bulk receipt")
    # All currently eligible 2022 Neon stock-days are present, but there are
    # historical IPOs and true stock halts. Do not pretend absent sid/day
    # is always a missing fetch, or that 246 equals the exchange calendar.
    union_days = local_days|bulk
    if set(neon_by_day)!=union_days:
        raise ValueError("Source calendar from previous 246-day Neon read changed")

    monthly = {}
    per_stock = Counter()
    first_seen_index = {}
    last_seen_index = {}
    all_by_day = {}
    for source_index, d in enumerate(sorted(union_days)):
        combined = aes_by_day.get(d,set()) | neon_by_day.get(d,set())
        if not combined <= allowed or len(combined)>len(roster):
            raise ValueError("Impossible merged today-listed stock/date coverage")
        all_by_day[d] = len(combined)
        for sid in combined:
            per_stock[sid] += 1
            first_seen_index.setdefault(sid,source_index)
            last_seen_index[sid] = source_index
        key = d.strftime("%Y-%m")
        bucket = monthly.setdefault(key,{
            "source_dates":0,
            "dates_with_at_least_500_eligible_stock_bars":0,
            "minimum_current_eligible_stock_bars":len(roster),
            "maximum_current_eligible_stock_bars":0,
        })
        bucket["source_dates"] += 1
        bucket["dates_with_at_least_500_eligible_stock_bars"] += (
            len(combined)>=500)
        bucket["minimum_current_eligible_stock_bars"] = min(
            bucket["minimum_current_eligible_stock_bars"],len(combined))
        bucket["maximum_current_eligible_stock_bars"] = max(
            bucket["maximum_current_eligible_stock_bars"],len(combined))

    aes_count = {d:len(aes_by_day[d]) for d in local_days}
    aes_dense = sum(v>=500 for v in aes_count.values())
    dense_all = sum(v>=500 for v in all_by_day.values())
    unchanged_neon_date_set = dense_neon==bulk
    only_bulk_not_dense = sorted(d.isoformat() for d in bulk-dense_neon)
    only_dense_not_bulk = sorted(d.isoformat() for d in dense_neon-bulk)
    current_stock_240 = sum(n>=240 for n in per_stock.values())
    current_stock_2022_full_source_days = sum(
        n==len(union_days) for n in per_stock.values())
    signatures = classify_current_stock_source_absences(
        roster,per_stock,first_seen_index,last_seen_index,
        source_day_count=len(union_days))
    if (signatures["eligible_stocks_not_observed_on_all_source_days"]!=
            len(roster)-current_stock_2022_full_source_days or
            signatures["currently_eligible_stocks_observed_240_to_245_source_days"]!=
            current_stock_240-current_stock_2022_full_source_days or
            signatures["currently_eligible_stocks_observed_fewer_than_240_source_days"]!=
            len(roster)-current_stock_240):
        raise ValueError("Per-stock 2022 count and observed absence signatures drifted")

    post2022_observed_zero_2022 = None
    if post2022_first_seen is not None:
        if (not isinstance(post2022_first_seen,(list,tuple))
                or len(post2022_first_seen)!=len(roster)):
            raise ValueError("Post-2022 first observation must cover same official cohort")
        firsts = {}
        try:
            end = date.fromisoformat(five_year["window_end_exclusive"])
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError("Invalid previously accepted five-year window") from exc
        for rec in post2022_first_seen:
            if not isinstance(rec,(tuple,list)) or len(rec)!=2:
                raise ValueError("Invalid post-2022 first observation row")
            sid,day = rec
            if (sid not in allowed or sid in firsts
                    or (day is not None and (
                        type(day) is not date or not date(2023,1,1)<=day<end))):
                raise ValueError("Tampered current eligible future source provenance")
            firsts[sid] = day
        if set(firsts)!=allowed:
            raise ValueError("First-observed proof does not match current listed roster")
        never_seen = allowed-set(per_stock)
        if len(never_seen)!=129 or signatures[
                "observation_signature_stock_count"]["no_observed_source_day"]!=129:
            raise ValueError("2022 129 no-source owner witness changed")
        years = {str(y):0 for y in range(2023,2027)}
        years["no_valid_stored_source_observation_in_2023_to_2026_window"]=0
        for sid in never_seen:
            day = firsts[sid]
            key = str(day.year) if day is not None else (
                "no_valid_stored_source_observation_in_2023_to_2026_window")
            if key not in years:
                raise ValueError("First stored post-2022 market date outside supported year")
            years[key] += 1
        if sum(years.values())!=129:
            raise ValueError("Post-2022 first-observed year bucket total mismatch")
        post2022_observed_zero_2022 = {
            "owner_2022_no_record_129_issuer_first_post2022_neon_observation_years":years,
            "first_stored_observation_is_not_official_first_listing_or_ipo_date":True,
            "2022_absence_does_not_prove_security_was_not_listed_in_2022":True,
            "2022_absence_or_ipo_reason_remains_unresolved":True,
            "post2022_neon_days_scanned_through_exclusive":end.isoformat(),
        }
    result = {
        "schema_version": 1,
        "scope": SCOPE,
        "year": 2022,
        "official_current_listed_eligible_twse_issuers":len(roster),
        "aes_reauthenticated_original_source_rows":source_audit[
            "authenticated_source_rows"],
        "aes_prior_2022_source_calendar_dates":len(local_days),
        "aes_dates_with_at_least_500_current_eligible_stock_bars":aes_dense,
        "aes_dates_below_500_current_eligible_stock_bars":len(local_days)-aes_dense,
        "aes_min_current_eligible_stock_bars":min(aes_count.values()),
        "aes_max_current_eligible_stock_bars":max(aes_count.values()),
        "neon_rechecked_stock_date_source_rows":count,
        "neon_2022_stock_dates_with_any_current_eligible_source_bars":len(neon_by_day),
        "neon_2022_dates_with_at_least_500_current_eligible_stock_bars":len(dense_neon),
        "neon_original_bulk_source_calendar_dates":len(bulk),
        "neon_bulk_date_set_matches_500_stock_density_date_set":unchanged_neon_date_set,
        "neon_bulk_days_below_500":only_bulk_not_dense,
        "neon_high_density_days_outside_original_bulk":only_dense_not_bulk,
        "aes_source_days_overlap_neon_bulk_source_days":len(local_days&bulk),
        "aes_plus_neon_unique_observed_source_dates":len(union_days),
        "aes_neon_merged_days_with_at_least_500_current_eligible_stock_bars":dense_all,
        "aes_neon_merged_min_current_eligible_stock_bars":min(all_by_day.values()),
        "aes_neon_merged_max_current_eligible_stock_bars":max(all_by_day.values()),
        "aes_neon_current_listed_stocks_with_at_least_240_of_246_source_dates":current_stock_240,
        "aes_neon_current_listed_stocks_with_all_246_source_dates":current_stock_2022_full_source_days,
        "current_listed_source_date_observation_absence_signatures":signatures,
        "aes_neon_2022_monthly_source_date_density": [
            {"month":m,**v} for m,v in sorted(monthly.items())],
        "source_day_presence_and_240_count_not_adjusted_total_return_or_historical_pit":True,
        "lack_of_stock_bar_may_be_ipo_halt_or_true_data_gap":True,
        "full_market_all_stock_daily_bar_completeness_certified":False,
        "historical_delisted_survivorship_bias_eliminated":False,
        "historical_original_issuer_publication_vintage_verified":False,
        "all_dividend_and_split_events_verified":False,
        "historical_adjusted_total_returns_approved":False,
        "five_year_all_stock_source_depth_certified":False,
        "model_release":"BLOCKED",
        "production_neon_writes":0,
        "line_messages_sent":0,
        "paid_upgrade_requested":False,
    }
    if post2022_observed_zero_2022 is not None:
        result["no_2022_stock_source_post2022_first_observation_triage"] = (
            post2022_observed_zero_2022)
    return result


def classify_current_stock_source_absences(
        roster, per_stock, first_index, last_index, *,
        source_day_count):
    """Aggregate source-presence signatures; NEVER impute IPO/halt or a missing bar.

    Partition current-listed stock identifiers into mutually exclusive groups.
    A stock-day without stored source records is an *observation absence*,
    not a confirmed exchange trading obligation or a backfill authorization.
    No stock IDs, raw prices or source dates leave the process.
    """
    if (not isinstance(roster, (tuple,list)) or not roster
            or len(set(roster))!=len(roster)
            or type(source_day_count) is not int or
            not 1<=source_day_count<=366
            or not isinstance(per_stock,Counter)
            or not isinstance(first_index,dict)
            or not isinstance(last_index,dict)
            or (set(per_stock)|set(first_index)|set(last_index))-set(roster)
            or set(first_index)!=set(per_stock)
            or set(last_index)!=set(per_stock)):
        raise ValueError("Observation signature requires original distinct cohort")
    groups={key:0 for key in (
        "all_observed_source_days",
        "no_observed_source_day",
        "absence_only_before_first_observed_day",
        "absence_only_after_last_observed_day",
        "absence_at_both_outer_boundaries_only",
        "internal_absent_days_only",
        "internal_and_outer_absent_days",
    )}
    lead_total=tail_total=inside_total=zero_total=0
    partial_240_to_245=below_240=0
    for sid in roster:
        n=per_stock.get(sid,0)
        if type(n) is not int or n<0 or n>source_day_count:
            raise ValueError("Impossible per-stock source-date observation count")
        if n==0:
            if sid in first_index or sid in last_index:
                raise ValueError("No-date stock cannot have observed date bounds")
            groups["no_observed_source_day"]+=1
            zero_total+=source_day_count
            below_240+=1
            continue
        first,last=first_index[sid],last_index[sid]
        if (type(first) is not int or type(last) is not int
                or not 0<=first<=last<source_day_count or
                n>last-first+1):
            raise ValueError("Impossible first/last authenticated source-day index")
        lead,tail=first,source_day_count-last-1
        inside=last-first+1-n
        lead_total+=lead
        tail_total+=tail
        inside_total+=inside
        if n<240:
            below_240+=1
        elif n<source_day_count:
            partial_240_to_245+=1
        if n==source_day_count:
            groups["all_observed_source_days"]+=1
        elif inside>0:
            if lead or tail:
                groups["internal_and_outer_absent_days"]+=1
            else:
                groups["internal_absent_days_only"]+=1
        elif lead and tail:
            groups["absence_at_both_outer_boundaries_only"]+=1
        elif lead:
            groups["absence_only_before_first_observed_day"]+=1
        elif tail:
            groups["absence_only_after_last_observed_day"]+=1
        else:
            raise RuntimeError("Unclassified non-full 2022 source observation")
    if (sum(groups.values())!=len(roster)
            or (lead_total+tail_total+inside_total+zero_total)!=
               len(roster)*source_day_count-sum(per_stock.values())):
        raise RuntimeError("Observed per-stock absent-source-date totals incoherent")
    return {
        "observation_signature_stock_count":groups,
        "eligible_stocks_not_observed_on_all_source_days":
            len(roster)-groups["all_observed_source_days"],
        "currently_eligible_stocks_observed_240_to_245_source_days":
            partial_240_to_245,
        "currently_eligible_stocks_observed_fewer_than_240_source_days":
            below_240,
        "nominal_absent_stock_source_date_pairs_before_first":lead_total,
        "nominal_absent_stock_source_date_pairs_after_last":tail_total,
        "nominal_absent_stock_source_date_pairs_inside_first_last":inside_total,
        "nominal_absent_stock_source_date_pairs_no_2022_record":zero_total,
        "nominal_absent_stock_source_date_pairs_total":
            lead_total+tail_total+inside_total+zero_total,
        "no_absence_is_a_certified_data_fetch_gap":True,
        "boundary_absence_is_not_verified_as_pre_ipo_or_delisting":True,
        "internal_absence_may_be_authentic_halt_or_unresolved_source_gap":True,
    }


def run_local(*, archive_2022, key_vault, panel_report,
              five_year_report, overlay_report, output,
              post2022_firstseen=False):
    paths = _private_archives(archive_2022)
    inputs = [
        _private_file(x,should_exist=True) for x in (
            panel_report,five_year_report,overlay_report)
    ]
    out = _private_file(output, should_exist=False)
    if len(set([*inputs,out]))!=4:
        raise ValueError("Private 2022 audit inputs/output must be distinct")
    original, five_year, overlay = (
        json.loads(path.read_text(encoding="utf-8")) for path in inputs)
    validate_owner_receipts(original,five_year,overlay)
    key = resolve_archive_key(
        vault_path=Path(key_vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""),
    )
    source_proof = audit_aes(paths,hex_key=key,spotchecks=0)
    if (source_proof["authentic_distinct_2022_source_sessions"]!=162
            or source_proof["authenticated_source_rows"]!=
               original["local_authenticated_source_rows"]):
        raise ValueError("Original AES source no longer matches prior 2022 report")
    replay,h = _authenticated_rows(
        paths,hex_key=key,
        expected_bundle_digest=source_proof["authenticated_file_digest_bundle_sha256"])
    post2022 = None
    if post2022_firstseen:
        cutoff = date.fromisoformat(five_year["window_end_exclusive"])
        roster, bulk, neon_rows, post2022 = capture_neon(
            os.environ.get("DATABASE_URL",""),post2022_end=cutoff)
    else:
        roster, bulk, neon_rows = capture_neon(os.environ.get("DATABASE_URL",""))
    allowed = set(roster)
    aes = {}
    total = 0
    for row in replay:
        d,sid = row["trade_date"],row["stock_id"]
        if sid in allowed:
            by_day = aes.setdefault(d,set())
            if sid in by_day:
                raise ValueError("Duplicated authenticated local source stock/date")
            by_day.add(sid)
        else:
            aes.setdefault(d,set())
        total += 1
        if total > MAX_AES_ROWS:
            raise ValueError("AES source exceeds prior 2022 verification budget")
    if (total!=source_proof["authenticated_source_rows"]
            or sha256(json.dumps(
                h,separators=(",",":")).encode()).hexdigest()!=
               source_proof["authenticated_file_digest_bundle_sha256"]):
        raise ValueError("AES source changed during replay")
    report = evaluate(
        original,five_year,overlay,roster=roster,aes_by_day=aes,
        neon_bulk_days=bulk,neon_rows=neon_rows,source_audit=source_proof,
        post2022_first_seen=post2022)
    payload = json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if len(payload.encode("utf-8"))>MAX_REPORT_BYTES:
        raise ValueError("Private stock-date density report exceeds safe limit")
    with out.open("x",encoding="utf-8") as fp:
        fp.write(payload)
    print(json.dumps({
        "status":("TWSE_2022_NO_SOURCE_2023PLUS_FIRST_SEEN_READONLY_PASS"
                  if post2022_firstseen else
                  "TWSE_2022_FULL_CURRENT_COHORT_AES_NEON_DENSITY_READONLY_PASS"),
        "authenticated_aes_source_dates":report[
            "aes_prior_2022_source_calendar_dates"],
        "aes_days_with_at_least_500_current_stocks":report[
            "aes_dates_with_at_least_500_current_eligible_stock_bars"],
        "all_246_days_with_at_least_500_current_stocks":report[
            "aes_neon_merged_days_with_at_least_500_current_eligible_stock_bars"],
        "bulk_84_equals_neon_dense_84_by_date":report[
            "neon_bulk_date_set_matches_500_stock_density_date_set"],
        "observed_on_all_246_source_days":report[
            "aes_neon_current_listed_stocks_with_all_246_source_dates"],
        "incomplete_2022_source_day_stock_count":report[
            "current_listed_source_date_observation_absence_signatures"][
                "eligible_stocks_not_observed_on_all_source_days"],
        "unproven_ipo_halt_and_source_gap_reasons":True,
        "no_2022_observation_129_post2022_firstseen_checked":bool(post2022_firstseen),
        "full_historical_pit_or_corporate_actions":False,
        "neon_writes":0,"line_messages_sent":0,"model_release":"BLOCKED",
    },ensure_ascii=False))


def main():
    cli=argparse.ArgumentParser(
        description="Owner-only 2022 AES and Neon current-listed full source stock/date density")
    cli.add_argument("--archive-2022",required=True)
    cli.add_argument("--key-vault",required=True)
    cli.add_argument("--source-panel-report",required=True)
    cli.add_argument("--five-year-neon-report",required=True)
    cli.add_argument("--prior-overlay-report",required=True)
    cli.add_argument("--out",required=True)
    cli.add_argument("--post2022-firstseen",action="store_true",
                     help="Extra owner-readonly first observed 2023+ source year for 2022 zero-record cohort")
    a=cli.parse_args()
    try:
        run_local(archive_2022=a.archive_2022,key_vault=a.key_vault,
            panel_report=a.source_panel_report,
            five_year_report=a.five_year_neon_report,
            overlay_report=a.prior_overlay_report,output=a.out,
            post2022_firstseen=a.post2022_firstseen)
    except Exception:
        raise SystemExit(
            "2022 per-stock current-listed AES/Neon source density audit FAILED; "
            "no Neon writes, LINE messages, credentials or prices printed"
        ) from None


if __name__=="__main__":
    main()
