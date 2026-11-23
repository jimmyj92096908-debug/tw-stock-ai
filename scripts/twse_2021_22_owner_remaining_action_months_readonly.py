"""Owner-private 1101/2330 missing eight historic TWSE calendar months; NO DB.

Requires actual owner-private six-event-month PR261 receipt PASS. Only the
remaining 2021-11-23..2022-12-30 uncovered months are requested (8*2=16
bounded official free TWSE GETs). Full source-period response coverage does
not certify company-event exhaustive feed, original MOPS first-publication
vintage or investor stock-bonus economics. Never promote total returns.
"""
from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import date, datetime, timezone
import json
import os
import re

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2021_22_owner_twse_six_event_months_readonly import (
    SCOPE as PRIOR_SCOPE, MONTHS as FIRST_MONTHS,
    EXPECTED_EX_DATE_PAIRS, STOCKS, SOURCES, _valid_hash,
)
from scripts.twse_2021_22_frozen2_official_action_monthly_audit import (
    fetch_month_kind, AUDITED_ALTERNATE_TARGETS, MAX_ROWS_PER_RESPONSE,
)

SCOPE = "OWNER_1101_2330_TWSE_REMAINING_EIGHT_HISTORIC_MONTH_RESPONSES_BLOCKED"
MISSING_MONTHS = (
    "2021-11", "2022-01", "2022-02", "2022-04",
    "2022-05", "2022-08", "2022-10", "2022-11",
)
COMPLETE_MONTHS = ("2021-11", "2021-12") + tuple(
    f"2022-{month:02d}" for month in range(1, 13))
MAX_NEW_CALLS = 16
MAX_REPORT_BYTES = 52000
STAGES = frozenset({
    "PRIVATE_RECEIPT", "PRIOR_SIX_MONTH_SOURCE_GUARD",
    "REMAINING_EIGHT_MONTH_OFFICIAL_HTTP", "FULL_INTERVAL_SOURCE_RECONCILIATION",
    "PRIVATE_REPORT_WRITE", "UNCLASSIFIED",
})


class HistoricalStageError(ValueError):
    def __init__(self, code):
        self.code = code if code in STAGES else "UNCLASSIFIED"
        super().__init__(self.code)


def _phase(stage, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except HistoricalStageError:
        raise
    except Exception:
        raise HistoricalStageError(stage) from None


def safe_error(code):
    if code not in STAGES:
        code = "UNCLASSIFIED"
    return ("Owner 1101/2330 eight remaining official months FAILED safely; "
            "diagnostic_stage=" + code
            + "; no prices, source records, secret paths, database URI, keys or tokens")


def month_bounds(month):
    if month not in COMPLETE_MONTHS:
        raise ValueError("Only fixed 2021-11 through 2022-12 source months")
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    end = date(year, mon, monthrange(year, mon)[1])
    if month == "2021-11":
        start = date(2021, 11, 23)
    if month == "2022-12":
        end = date(2022, 12, 30)
    return start, end


def _check_event(event, *, start, end):
    if not isinstance(event, dict):
        raise ValueError("Historical official event row not an object")
    sid = event.get("stock_id")
    day = event.get("event_date")
    kind = event.get("reported_event_category")
    if type(day) is not str:
        raise ValueError("Unknown official day text")
    d = date.fromisoformat(day)
    if (d.isoformat() != day or sid not in STOCKS or not start <= d <= end
            or kind not in ("CASH_DIVIDEND", "STOCK_DIVIDEND",
                            "COMBINED_OR_UNCLASSIFIED", "CAPITAL_REDUCTION")
            or not _valid_hash(event.get("original_official_row_sha256"))
            or event.get("original_issuer_announcement_timestamp_available") is not False
            or event.get("historical_cash_entitlement_or_share_factor_certified") is not False):
        raise ValueError("Source event issuer/date/vintage out of contract")
    return (sid, day, kind)


def _check_month_receipt(item, *, month, kind, new=False):
    start, end = month_bounds(month)
    if not isinstance(item, dict):
        raise ValueError("Missing month receipt")
    endpoint = item.get("endpoint") if not new else item.get("source_url")
    digest = (item.get("response_sha256_captured_now")
              if not new else item.get("response_sha256"))
    first = item.get("requested_start")
    last = item.get("requested_end")
    status = item.get("status") if not new else item.get("source_status")
    n = item.get("public_rows_in_feed") if not new else item.get("received_rows")
    own_n = item.get("two_current_issuer_event_rows")
    if (endpoint != SOURCES[kind] or not _valid_hash(digest)
            or first != start.isoformat() or last != end.isoformat()
            or status not in ("OK_WITH_ROWS", "OK_EMPTY_NOT_ZERO_PROOF",
                              "NO_MATCH_NOT_EVIDENCE_OF_ZERO_ACTIONS")
            or type(n) is not int or not 0 <= n <= MAX_ROWS_PER_RESPONSE
            or (not new and (type(own_n) is not int or not 0 <= own_n <= n))):
        raise ValueError("Invalid official historical response provenance")
    return {
        "month": month, "kind": kind, "endpoint": endpoint,
        "requested_start": first, "requested_end": last,
        "response_sha256_captured_now": digest,
        "status": status, "public_rows_in_feed": n,
        "two_current_issuer_event_rows": own_n if not new else None,
        "no_match_does_not_certify_zero_events": True,
    }


def validate_prior_six(prior):
    if not isinstance(prior, dict):
        raise ValueError("No previous owner six-month report")
    scalars = {
        "schema_version": 1,
        "scope": PRIOR_SCOPE,
        "source_months_queried": list(FIRST_MONTHS),
        "official_twse_http_requests": 12,
        "expected_issuer_retrospective_event_date_count": 6,
        "expected_events_found_in_official_twse_ex_feed": 6,
        "all_six_known_dividend_dates_observed_in_twse_ex_feed": True,
        "expected_event_date_pairs_not_observed": [],
        "additional_twse_ex_date_pairs_in_same_six_months": [],
        "official_data_retrieved_as_of_original_2021_22_publication": False,
        "original_mops_issuer_announcement_timestamps_verified": False,
        "full_2021_22_corporate_action_universe_verified": False,
        "cash_stock_entitlement_and_par_factor_verified": False,
        "verified_adjusted_total_return_labels": False,
        "production_neon_backfill_approved": False,
        "neon_writes": 0, "line_messages_sent": 0,
        "paid_services_used": False,
        "model_release": "BLOCKED",
    }
    for key, expected in scalars.items():
        value = prior.get(key)
        if type(value) is not type(expected) or value != expected:
            raise ValueError("Previously accepted 12-response evidence changed")
    timestamp = prior.get("captured_at_utc")
    if not isinstance(timestamp, str) or len(timestamp) > 60:
        raise ValueError("Prior source capture timestamp invalid")
    parsed_at = datetime.fromisoformat(timestamp)
    if parsed_at.tzinfo is None:
        raise ValueError("Missing original 2026 capture timezone")
    parts = prior.get("official_response_receipts")
    if not isinstance(parts, list) or len(parts) != 12:
        raise ValueError("Owner prior 12 exact month/type receipts required")
    keyset = set()
    for rec in parts:
        month, kind = rec.get("month"), rec.get("kind")
        if month not in FIRST_MONTHS or kind not in SOURCES:
            raise ValueError("Prior month or endpoint out of bounds")
        pair = (month, kind)
        if pair in keyset:
            raise ValueError("Duplicate prior source request")
        keyset.add(pair)
        clean = _check_month_receipt(rec, month=month, kind=kind)
        if (rec.get("no_match_does_not_certify_zero_events") is not True
                or rec.get("two_current_issuer_event_rows") !=
                clean["two_current_issuer_event_rows"]):
            raise ValueError("Historical no-match guard changed")
    if keyset != {(m, k) for m in FIRST_MONTHS for k in SOURCES}:
        raise ValueError("Prior six months missing source pairs")
    events = prior.get("official_target_issuer_event_rows")
    if not isinstance(events, list):
        raise ValueError("Missing previous official issuer event rows")
    seen, observed_ex = set(), set()
    per_pair_counts = {}
    for event in events:
        d = date.fromisoformat(event["event_date"])
        month = d.strftime("%Y-%m")
        if month not in FIRST_MONTHS:
            raise ValueError("Prior official event outside six studied months")
        key = _check_event(event, start=month_bounds(month)[0],
                           end=month_bounds(month)[1])
        if key in seen:
            raise ValueError("Prior official row key duplicated")
        seen.add(key)
        category = event["reported_event_category"]
        kind = "reduction" if category == "CAPITAL_REDUCTION" else "ex"
        per_pair_counts[(month, kind)] = per_pair_counts.get((month, kind), 0) + 1
        if kind == "ex":
            observed_ex.add((event["stock_id"], event["event_date"]))
    if observed_ex != set(EXPECTED_EX_DATE_PAIRS):
        raise ValueError("Owner prior 6/6 dates not supported by actual rows")
    for rec in parts:
        pair = (rec["month"], rec["kind"])
        if rec["two_current_issuer_event_rows"] != per_pair_counts.get(pair, 0):
            raise ValueError("Owner prior event row counts mismatch receipts")
    witnesses = prior.get("retrospective_event_date_witnesses")
    if not isinstance(witnesses, list) or len(witnesses) != 6:
        raise ValueError("Six source-date witnesses required")
    witness_seen = set()
    for row in witnesses:
        if not isinstance(row, dict):
            raise ValueError("Unexpected prior witness")
        key = (row.get("stock_id"), row.get("issuer_retrospective_ex_date"))
        if (key not in EXPECTED_EX_DATE_PAIRS or key in witness_seen
                or row.get("official_twse_twt49u_matching_date_observed") is not True
                or row.get("original_issuer_publication_timestamp_proven") is not False
                or row.get("official_event_economics_cash_share_amount_verified") is not False
                or row.get("full_adjusted_total_return_approved") is not False):
            raise ValueError("Prior witnessed date falsely promoted")
        witness_seen.add(key)
    return events, parts


def reconcile(prior, *, fetcher, observed_at=None):
    previous, prior_parts = validate_prior_six(prior)
    if STOCKS != AUDITED_ALTERNATE_TARGETS or len(MISSING_MONTHS) != 8:
        raise ValueError("Allowed historical research cohorts changed")
    if set(MISSING_MONTHS) | set(FIRST_MONTHS) != set(COMPLETE_MONTHS):
        raise ValueError("Full period months not covered")
    if set(MISSING_MONTHS) & set(FIRST_MONTHS):
        raise ValueError("A month queried twice")
    if observed_at is None:
        observed_at = datetime.now(timezone.utc)
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise ValueError("Capture time needs timezone")
    new_parts = []
    new_events = []
    seen = {_check_event(event, start=month_bounds(event["event_date"][:7])[0],
                        end=month_bounds(event["event_date"][:7])[1])
            for event in previous}
    for month in MISSING_MONTHS:
        start, end = month_bounds(month)
        for kind in ("ex", "reduction"):
            if len(new_parts) >= MAX_NEW_CALLS:
                raise ValueError("TWSE new request budget exceeded")
            data = fetcher(kind, start, end)
            clean = _check_month_receipt(data, month=month, kind=kind, new=True)
            rows = data.get("events")
            if (not isinstance(rows, list)
                    or len(rows) > clean["public_rows_in_feed"]):
                raise ValueError("TWSE public source rows missing")
            for event in rows:
                key = _check_event(event, start=start, end=end)
                if (kind == "reduction") != (key[2] == "CAPITAL_REDUCTION"):
                    raise ValueError("Mismatch between TWSE source type and event type")
                if key in seen:
                    raise ValueError("Duplicate issuer event across historic months")
                seen.add(key)
                new_events.append(event)
            clean["two_current_issuer_event_rows"] = len(rows)
            new_parts.append(clean)
    if len(new_parts) != MAX_NEW_CALLS:
        raise ValueError("Not all eight official source months observed")
    all_parts = sorted(
        [_check_month_receipt(p, month=p["month"], kind=p["kind"])
         for p in prior_parts] + new_parts,
        key=lambda x: (x["month"], x["kind"]))
    if (len(all_parts) != 28 or len({(p["month"], p["kind"]) for p in all_parts}) != 28
            or {p["month"] for p in all_parts} != set(COMPLETE_MONTHS)):
        raise ValueError("Incomplete monthly TWSE response range")
    all_events = sorted(previous + new_events,
                        key=lambda e: (e["event_date"], e["stock_id"],
                                       e["reported_event_category"]))
    new_ex = [
        {"stock_id": e["stock_id"], "event_date": e["event_date"],
         "official_category": e["reported_event_category"]}
        for e in new_events
        if e["reported_event_category"] != "CAPITAL_REDUCTION"
    ]
    new_reduction = [
        {"stock_id": e["stock_id"], "event_date": e["event_date"]}
        for e in new_events
        if e["reported_event_category"] == "CAPITAL_REDUCTION"
    ]
    return {
        "schema_version": 1, "scope": SCOPE,
        "new_official_capture_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
        "prior_official_capture_at_utc": prior["captured_at_utc"],
        "full_requested_calendar_start": "2021-11-23",
        "full_requested_calendar_end": "2022-12-30",
        "full_calendar_months_with_response_receipts": list(COMPLETE_MONTHS),
        "prior_6_months_and_12_official_requests_accepted": True,
        "new_calendar_months_queried": list(MISSING_MONTHS),
        "new_official_twse_http_requests": len(new_parts),
        "all_official_twse_http_response_receipts_count": len(all_parts),
        "all_official_response_receipts": all_parts,
        "all_official_target_issuer_event_rows": all_events,
        "prior_six_issuer_date_matches_preserved": True,
        "original_six_known_issuer_ex_dividend_pairs": 6,
        "additional_issuer_ex_right_dates_observed_in_new_eight_months": new_ex,
        "additional_issuer_reduction_dates_observed_in_new_eight_months": new_reduction,
        "new_months_without_observed_issuer_ex_right_rows_does_not_prove_no_events":
            len(new_ex) == 0,
        "all_14_months_public_response_queries_adequately_covered": True,
        "no_data_response_proves_zero_historic_company_actions": False,
        "response_source_historic_action_coverage_independently_proven_exhaustive": False,
        "issuer_original_mops_first_announcement_publication_verified": False,
        "new_share_entitlement_and_cash_distribution_verified": False,
        "historical_pit_listing_universe_verified": False,
        "full_five_year_dividends_or_prices_complete": False,
        "adjusted_total_return_labels_approved": False,
        "production_neon_backfill_approved": False,
        "neon_writes": 0, "line_messages_sent": 0,
        "paid_services_used": False,
        "model_release": "BLOCKED",
    }


def run_owner(*, prior, out):
    old = _phase("PRIVATE_RECEIPT", _private_file, prior, should_exist=True)
    target = _phase("PRIVATE_RECEIPT", _private_file, out, should_exist=False)
    if old == target:
        raise HistoricalStageError("PRIVATE_RECEIPT")
    previous = _phase("PRIOR_SIX_MONTH_SOURCE_GUARD",
                      lambda: json.loads(old.read_text(encoding="utf-8")))
    _phase("PRIOR_SIX_MONTH_SOURCE_GUARD", validate_prior_six, previous)
    report = _phase("REMAINING_EIGHT_MONTH_OFFICIAL_HTTP",
                    reconcile, previous,
                    fetcher=lambda kind,start,end:
                    fetch_month_kind(kind,start,end,targets=STOCKS))
    encoded = _phase("PRIVATE_REPORT_WRITE",
                     lambda: json.dumps(report, ensure_ascii=False, indent=2,
                                        allow_nan=False) + "\n")
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise HistoricalStageError("PRIVATE_REPORT_WRITE")
    def write():
        with target.open("x", encoding="utf-8") as fd:
            fd.write(encoded)
    _phase("PRIVATE_REPORT_WRITE", write)
    print(json.dumps({
        "status": "OWNER_1101_2330_REMAINING_EIGHT_TWSE_MONTH_RESPONSES_CAPTURE_PASS",
        "previous_twse_calls": 12,
        "new_twse_calls": report["new_official_twse_http_requests"],
        "total_months": len(report["full_calendar_months_with_response_receipts"]),
        "new_ex_right_candidate_rows": len(
            report["additional_issuer_ex_right_dates_observed_in_new_eight_months"]),
        "new_capital_reduction_candidate_rows": len(
            report["additional_issuer_reduction_dates_observed_in_new_eight_months"]),
        "issuer_MOPS_original_pit_verified": False,
        "model_release": "BLOCKED", "neon_writes": 0, "line_messages_sent": 0,
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prior-six-month-source", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit(safe_error("UNCLASSIFIED"))
    try:
        run_owner(prior=args.prior_six_month_source, out=args.out)
    except HistoricalStageError as e:
        raise SystemExit(safe_error(e.code)) from None
    except Exception:
        raise SystemExit(safe_error("UNCLASSIFIED")) from None


if __name__ == "__main__":
    main()
