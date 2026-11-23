"""Pure owner-local 2022 TWSE observed-source-date internal absence triage.

Never use the recorded 246 observed source days as a certification of the
independent historical exchange trade calendar. These gaps are unobserved
stock/source-date pairs between the first and last valid source observation,
not proved missing trade obligations: halts, corporate actions, issuer
eligibility, and original listing/board-vintage still require official proof.

No database access, AES/plain price, trading, network or model actions here.
All stock IDs, specific example intervals, and source day month summaries are
only attached to an opt-in owner-private JSON report by the parent auditor.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import re

SCOPE = "OWNER_TWSE_2022_116_CURRENT_LISTED_INTERNAL_SOURCE_ABSENCE_TRIAGE"
MONTHS = tuple(f"2022-{n:02d}" for n in range(1, 13))


def triage_internal_source_absences(
        roster, source_dates, observed_by_day, *,
        expected_signature=None,
        enforce_owner_receipt=False):
    """Classify absent source-date observations inside first/last valid days.

    Source input must contain actual valid AES union Neon stock/source days,
    never fictional or imputed prices. All detailed stock IDs should remain
    in the owner-protected TwStockPrivate report.
    """
    if (not isinstance(roster,(tuple,list)) or not roster
            or len(set(roster))!=len(roster)
            or any(not isinstance(s,str) or not re.fullmatch(r"\d{4}",s)
                   or s=="1589" for s in roster)):
        raise ValueError("Invalid eligible current official TWSE cohort")
    allowed=set(roster)
    if (not isinstance(source_dates,(tuple,list))
            or not 2<=len(source_dates)<=260
            or any(type(d) is not date or d.year!=2022 or d.weekday()>=5
                   for d in source_dates)
            or tuple(sorted(source_dates))!=tuple(source_dates)
            or len(set(source_dates))!=len(source_dates)
            or not isinstance(observed_by_day,dict)
            or set(observed_by_day)!=set(source_dates)):
        raise ValueError("Only unchanged ordered 2022 observed official source days permitted")
    positions=defaultdict(list)
    for index,day in enumerate(source_dates):
        issuers=observed_by_day[day]
        if (not isinstance(issuers,set) or not issuers<=allowed):
            raise ValueError("Unlisted/noneligible issuer source date cannot enter 2022 study")
        for sid in issuers:
            positions[sid].append(index)

    counts={
        "internal_absent_source_date_stock_count":0,
        "internal_only_stock_count":0,
        "internal_and_outer_stock_count":0,
        "internal_absent_stock_source_date_pairs":0,
        "disjoint_absence_run_count":0,
        "one_day_run_count":0,
        "two_to_five_day_run_count":0,
        "six_or_more_day_run_count":0,
    }
    affected_by_month={m:set() for m in MONTHS}
    missing_pairs_by_month=dict.fromkeys(MONTHS,0)
    rows=[]
    for sid in sorted(allowed):
        indices=positions.get(sid,[])
        if not indices:
            continue
        first,last=indices[0],indices[-1]
        if len(indices)>last-first+1 or len(indices)!=len(set(indices)):
            raise ValueError("Invalid repeated internal observation day/stock key")
        valid_index=set(indices)
        missing=[i for i in range(first,last+1) if i not in valid_index]
        if not missing:
            continue

        trailing_runs=[]
        start=end=missing[0]
        for index in missing[1:]:
            if index==end+1:
                end=index
            else:
                trailing_runs.append((start,end))
                start=end=index
        trailing_runs.append((start,end))
        inner_only=first==0 and last==len(source_dates)-1
        counts["internal_absent_source_date_stock_count"]+=1
        counts["internal_only_stock_count" if inner_only else
               "internal_and_outer_stock_count"]+=1
        counts["internal_absent_stock_source_date_pairs"]+=len(missing)
        counts["disjoint_absence_run_count"]+=len(trailing_runs)
        for start,end in trailing_runs:
            length=end-start+1
            kind=("one_day_run_count" if length==1 else
                  "two_to_five_day_run_count" if length<=5 else
                  "six_or_more_day_run_count")
            counts[kind]+=1
        for index in missing:
            m=source_dates[index].strftime("%Y-%m")
            missing_pairs_by_month[m]+=1
            affected_by_month[m].add(sid)
        samples=[
            {
                "first_unobserved_source_day":source_dates[start].isoformat(),
                "last_unobserved_source_day":source_dates[end].isoformat(),
                "unobserved_source_days_in_run":end-start+1,
            }
            for start,end in sorted(
                trailing_runs,key=lambda t:(-(t[1]-t[0]+1),t[0]))[:2]
        ]
        rows.append({
            "stock_id":sid,
            "observation_signature":(
                "INTERNAL_ONLY" if inner_only else "INTERNAL_AND_OUTER"),
            "first_observed_2022_source_day":source_dates[first].isoformat(),
            "last_observed_2022_source_day":source_dates[last].isoformat(),
            "internal_unobserved_source_day_count":len(missing),
            "disjoint_internal_unobserved_runs":len(trailing_runs),
            "longest_internal_absence_run_source_days":max(
                hi-lo+1 for lo,hi in trailing_runs),
            "sample_two_longest_internal_absence_runs":samples,
        })
    rows.sort(key=lambda r:(
        -r["internal_unobserved_source_day_count"],
        -r["longest_internal_absence_run_source_days"],r["stock_id"]))
    if (counts["one_day_run_count"]
            +counts["two_to_five_day_run_count"]
            +counts["six_or_more_day_run_count"]
            !=counts["disjoint_absence_run_count"]
            or sum(missing_pairs_by_month.values())!=counts[
                "internal_absent_stock_source_date_pairs"]
            or len(rows)!=counts["internal_absent_source_date_stock_count"]):
        raise ValueError("Owner internal gap source-day counters do not reconcile")

    if expected_signature is not None:
        if not isinstance(expected_signature,dict):
            raise ValueError("Prior owner observation signatures invalid")
        prev=expected_signature.get("observation_signature_stock_count")
        if (not isinstance(prev,dict)
                or counts["internal_only_stock_count"]!=prev.get(
                    "internal_absent_days_only")
                or counts["internal_and_outer_stock_count"]!=prev.get(
                    "internal_and_outer_absent_days")
                or counts["internal_absent_stock_source_date_pairs"]!=
                   expected_signature.get(
                       "nominal_absent_stock_source_date_pairs_inside_first_last")):
            raise ValueError("Prior 2022 authenticated internal absence ledger drifted")
    if enforce_owner_receipt and (
            len(roster)!=1092 or len(source_dates)!=246
            or counts["internal_absent_source_date_stock_count"]!=116
            or counts["internal_only_stock_count"]!=104
            or counts["internal_and_outer_stock_count"]!=12):
        raise ValueError("Owner-verified 104+12 true source absence group changed")

    return {
        "schema_version":1,
        "scope":SCOPE,
        "source_year":2022,
        "official_current_eligible_stocks":len(roster),
        "authenticated_aes_neon_observed_source_days":len(source_dates),
        "source_observation_gap_count_signatures":counts,
        "monthly_internal_unobserved_eligible_stock_source_pairs":[
            {
                "month":m,
                "unobserved_stock_source_date_pairs":missing_pairs_by_month[m],
                "affected_current_listed_stock_count":len(affected_by_month[m]),
            }
            for m in MONTHS
        ],
        "private_2022_current_stock_internal_absence_research_rows":rows,
        "only_two_longest_gap_example_runs_per_stock":True,
        "observed_source_days_are_not_independent_historic_exchange_calendar":True,
        "stock_trading_halt_or_listing_eligibility_not_proven":True,
        "unobserved_source_day_is_not_approved_backfill_or_imputation":True,
        "issuer_historical_pit_membership_not_verified":True,
        "historic_delisted_survivorship_unbiased":False,
        "model_release":"BLOCKED",
        "production_neon_writes":0,
        "line_messages_sent":0,
        "paid_provider_or_upgrades":False,
    }



def full_six_plus_source_gap_queue(
        roster, source_dates, observed_by_day, *,
        previous_authenticated_116_report, expected_long_run_count=30):
    """Recover *all*, not just two samples, 2022 internal gaps >=6 source days.

    Requires byte-equivalent JSON structure of a prior owner real 116 report
    (recomputed from reauthenticated AES + read-only Neon stock/date sources).
    Does not infer missing real trades or classify pauses. Only saves dates
    and ticker identifiers to a distinct owner-private JSON.
    """
    original=triage_internal_source_absences(
        roster,source_dates,observed_by_day,
        enforce_owner_receipt=True,
    )
    if (not isinstance(previous_authenticated_116_report,dict)
            or original!=previous_authenticated_116_report
            or type(expected_long_run_count) is not int
            or not 0<=expected_long_run_count<=35):
        raise ValueError("Immutable owner 116 source absence proof changed")
    allowed=set(roster)
    if len(allowed)!=1092 or len(source_dates)!=246:
        raise ValueError("Expected authenticated owner 2022 official current-stock cohort")
    positions={sid:[] for sid in roster}
    for i,d in enumerate(source_dates):
        for sid in observed_by_day[d]:
            positions[sid].append(i)
    long_rows=[]
    for sid in sorted(allowed):
        actual=positions[sid]
        if len(actual)<2:
            continue
        first,last=actual[0],actual[-1]
        have=set(actual)
        absent=[i for i in range(first+1,last) if i not in have]
        if not absent:
            continue
        begin=end=absent[0]
        run_intervals=[]
        for i in absent[1:]:
            if i==end+1:
                end=i
            else:
                run_intervals.append((begin,end))
                begin=end=i
        run_intervals.append((begin,end))
        group=("INTERNAL_ONLY" if first==0 and
               last==len(source_dates)-1 else
               "INTERNAL_AND_OUTER")
        for lo,hi in run_intervals:
            size=hi-lo+1
            if size<6:
                continue
            long_rows.append({
                "stock_id":sid,
                "observation_signature":group,
                "first_unobserved_source_day":source_dates[lo].isoformat(),
                "last_unobserved_source_day":source_dates[hi].isoformat(),
                "unobserved_consecutive_source_days":size,
                "confirmed_official_halt_for_these_dates":False,
                "confirmed_missing_price_repair_obligation":False,
            })
    long_rows.sort(key=lambda item:(
        -item["unobserved_consecutive_source_days"],
        item["first_unobserved_source_day"],item["stock_id"]))
    audited_counts=original["source_observation_gap_count_signatures"]
    if (len(long_rows)!=expected_long_run_count or len(long_rows)!=
            audited_counts["six_or_more_day_run_count"]
            or sum(item["unobserved_consecutive_source_days"] for item
                   in long_rows)>audited_counts[
                       "internal_absent_stock_source_date_pairs"]):
        raise ValueError("Previously authenticated 30 long 2022 gaps not reproduced")
    return {
        "schema_version":1,
        "scope":"OWNER_2022_TWSE_ALL_LONG_SOURCE_ABSENCE_OFFICIAL_CHECK_QUEUE",
        "underlying_116_source_absence_stocks":audited_counts[
            "internal_absent_source_date_stock_count"],
        "underlying_all_absent_stock_source_day_pairs":audited_counts[
            "internal_absent_stock_source_date_pairs"],
        "underlying_all_absent_source_day_runs":audited_counts[
            "disjoint_absence_run_count"],
        "at_least_six_unobserved_source_day_run_count":len(long_rows),
        "all_30_long_source_absence_runs_recovered_from_source":True,
        "owner_private_long_run_official_halt_check_queue":long_rows,
        "twse_official_historic_suspension_query_url":
            "https://www.twse.com.tw/zh/trading/historical/twtawu.html",
        "official_halt_or_resumption_not_checked_by_this_offline_step":True,
        "source_day_absence_not_proof_of_exchange_trading_obligation":True,
        "zero_stock_price_imputation":True,
        "model_release":"BLOCKED",
        "production_neon_writes":0,
        "line_messages_sent":0,
        "paid_service_used":False,
    }
