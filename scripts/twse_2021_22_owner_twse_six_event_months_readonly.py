"""Owner-only public TWSE historical six dividend MONTHS response inventory.

Requires owner-private PR260 historical issuer evidence PASS receipt.
Uses official TWSE TWT49U ex-right/ex-dividend and TWTAUU capital
reduction/resumption public historical feeds only, 12 HTTP GETs MAX.
No Neon, AES, original stock prices, LINE, trading or paid services.

A query response downloaded in 2026 is not the original 2021/22 MOPS
publication vintage. A "NO DATA" response never proves no action.
The capture can PASS while known events are missing; always disclose both.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
import re

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2021_22_frozen2_official_action_monthly_audit import (
    AUDITED_ALTERNATE_TARGETS, MAX_ROWS_PER_RESPONSE, SOURCES,
    fetch_month_kind, months_and_bounds,
)
from scripts.twse_2021_22_owner_issuer_dividend_economics_offline import (
    SCOPE as PRIOR_SCOPE, REVIEW_DATE, check_issuer_economics,
)

SCOPE = "OWNER_1101_2330_TWSE_SIX_HISTORIC_DIVIDEND_MONTH_RESPONSES_BLOCKED"
STOCKS = frozenset(("1101", "2330"))
MONTHS = ("2021-12", "2022-03", "2022-06", "2022-07", "2022-09", "2022-12")
MAX_REQUESTS = 12
MAX_OUTPUT_BYTES = 30000
EXPECTED_EX_DATE_PAIRS = frozenset((
    (row["stock_id"], row["ex_date"]) for row in check_issuer_economics()
))
STAGES = frozenset({
    "PRIVATE_RECEIPT", "PRIOR_ISSUER_RECEIPT_GUARD",
    "TWSE_OFFICIAL_MONTH_RESPONSES", "TWSE_SOURCE_RECONCILIATION",
    "PRIVATE_REPORT_WRITE", "UNCLASSIFIED",
})


class OwnerOfficialStageError(ValueError):
    def __init__(self, code):
        self.code = code if code in STAGES else "UNCLASSIFIED"
        super().__init__(self.code)


def _phase(stage, func, *args, **kwargs):
    if stage not in STAGES:
        raise OwnerOfficialStageError("UNCLASSIFIED")
    try:
        return func(*args, **kwargs)
    except OwnerOfficialStageError:
        raise
    except Exception:
        raise OwnerOfficialStageError(stage) from None


def safe_error(stage):
    if stage not in STAGES:
        stage = "UNCLASSIFIED"
    return ("Owner 1101/2330 public TWSE monthly evidence FAILED safely; "
            "diagnostic_stage=" + stage
            + "; no private file path, Neon URI, AES key or raw price disclosed")


def validate_private_prior(report):
    if not isinstance(report, dict):
        raise ValueError("Missing accepted owner issuer report")
    expected = {
        "schema_version": 1, "scope": PRIOR_SCOPE,
        "issuer_evidence_review_date": REVIEW_DATE,
        "reviewed_issuer_retrospective_event_rows": 6,
        "original_neon_action_gaps_in_previous_owner_snapshot": 6,
        "source_proof_is_offline_manual_issuer_page_transcription": True,
        "source_issuer_urls_checked_at_runtime": False,
        "owner_original_AES_ciphertexts_reauthenticated_in_this_run": False,
        "new_neon_snapshot_performed_in_this_run": False,
        "mops_original_first_publication_timestamp_proven": False,
        "tcc_stock_dividend_new_shares_factor_verified": False,
        "corporate_action_universe_complete": False,
        "publication_vintage_and_asof_eligibility_verified": False,
        "raw_price_adjustment_factors_verified": False,
        "real_forward_total_return_labels_approved": False,
        "production_backfill_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0, "line_messages_sent": 0,
        "paid_services_requested": False,
    }
    for field, val in expected.items():
        value = report.get(field)
        if type(value) is not type(val) or value != val:
            raise ValueError("Prior offline issuer proof contract altered")
    if report.get("research_evidence_events") != check_issuer_economics():
        raise ValueError("Issuer retrospective six event economics changed")
    revisions = report.get("tcc_mops_mirror_claimed_revisions")
    if (not isinstance(revisions, list) or len(revisions) != 2
            or any(not isinstance(x, dict)
                   or x.get("claim_provenance") !=
                   "THIRD_PARTY_MOPS_REPRINT_NOT_ORIGINAL" for x in revisions)):
        raise ValueError("Previously unverified MOPS mirror wrongly promoted")
    return True


def exact_months():
    if len(MONTHS) != 6 or sorted(set(MONTHS)) != list(MONTHS):
        raise ValueError("Six exact bounded historical months required")
    ranges = []
    for month in MONTHS:
        one = months_and_bounds(month, month)
        if len(one) != 1 or one[0][0] != month:
            raise ValueError("Bad public source month range")
        ranges.append(one[0])
    return ranges


def _valid_hash(digest):
    return type(digest) is str and bool(re.fullmatch(r"[0-9a-f]{64}", digest))


def reconcile(prior, *, fetcher, captured_at_utc=None):
    """Record verified response shapes with explicit missing six candidate keys.

    fetcher(kind, start_date, end_date) returns the already-parsed source
    receipt with exact source URI, status, response/body hash and event rows.
    """
    validate_private_prior(prior)
    if AUDITED_ALTERNATE_TARGETS != STOCKS:
        raise ValueError("Target issuer allowlist changed")
    if captured_at_utc is None:
        captured_at_utc = datetime.now(timezone.utc)
    if not isinstance(captured_at_utc, datetime) or captured_at_utc.tzinfo is None:
        raise ValueError("Actual observation instant required")
    rows, history, observed = [], [], []
    keys = set()
    for month, begin, end in exact_months():
        for kind in ("ex", "reduction"):
            if len(history) >= MAX_REQUESTS:
                raise ValueError("Official historical request cap exceeded")
            result = fetcher(kind, begin, end)
            if not isinstance(result, dict):
                raise ValueError("Missing official historical feed response")
            events = result.get("events")
            status = result.get("source_status")
            received = result.get("received_rows")
            if (result.get("source_url") != SOURCES[kind]
                    or result.get("requested_start") != begin.isoformat()
                    or result.get("requested_end") != end.isoformat()
                    or not _valid_hash(result.get("response_sha256"))
                    or status not in (
                        "OK_WITH_ROWS", "OK_EMPTY_NOT_ZERO_PROOF",
                        "NO_MATCH_NOT_EVIDENCE_OF_ZERO_ACTIONS")
                    or type(received) is not int
                    or not 0 <= received <= MAX_ROWS_PER_RESPONSE
                    or not isinstance(events, list)
                    or len(events) > received):
                raise ValueError("Untrusted exchange response provenance")
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("Malformed exchange issuer event")
                sid = event.get("stock_id")
                day = event.get("event_date")
                typ = event.get("reported_event_category")
                if type(day) is not str:
                    raise ValueError("Missing full event date")
                event_day = date.fromisoformat(day)
                if (sid not in STOCKS or not begin <= event_day <= end
                        or typ not in (
                            "CASH_DIVIDEND", "STOCK_DIVIDEND",
                            "COMBINED_OR_UNCLASSIFIED", "CAPITAL_REDUCTION")
                        or (kind == "reduction") != (typ == "CAPITAL_REDUCTION")
                        or not _valid_hash(event.get("original_official_row_sha256"))
                        or event.get("original_issuer_announcement_timestamp_available") is not False
                        or event.get("historical_cash_entitlement_or_share_factor_certified") is not False):
                    raise ValueError("Out-of-scope historical source event")
                key = (sid, day, typ)
                if key in keys:
                    raise ValueError("Official source duplicate event key")
                keys.add(key)
                observed.append(dict(event))
            history.append({
                "month": month, "kind": kind,
                "endpoint": SOURCES[kind],
                "requested_start": begin.isoformat(),
                "requested_end": end.isoformat(),
                "response_sha256_captured_now": result["response_sha256"],
                "status": status, "public_rows_in_feed": received,
                "two_current_issuer_event_rows": len(events),
                "no_match_does_not_certify_zero_events": True,
            })
    if len(history) != MAX_REQUESTS:
        raise ValueError("Not all 12 bounded TWSE historical feeds requested")
    # Source row presence = exchange historic response corroboration only.
    # TWSE ratio/reference prices are not cash/share entitlement or PIT.
    found_by_date = {
        (r["stock_id"], r["event_date"]) for r in observed
        if r["reported_event_category"] != "CAPITAL_REDUCTION"
    }
    missing = sorted(EXPECTED_EX_DATE_PAIRS - found_by_date)
    extra = sorted(found_by_date - EXPECTED_EX_DATE_PAIRS)
    for sid, date_text in sorted(EXPECTED_EX_DATE_PAIRS):
        classifications = sorted({
            r["reported_event_category"] for r in observed
            if (r["stock_id"], r["event_date"]) == (sid, date_text)
            and r["reported_event_category"] != "CAPITAL_REDUCTION"
        })
        rows.append({
            "stock_id": sid, "issuer_retrospective_ex_date": date_text,
            "official_twse_twt49u_matching_date_observed": bool(classifications),
            "twse_reported_categories": classifications,
            "twse_ex_right_classification_is_conclusive_for_cash_and_stock": False,
            "original_issuer_publication_timestamp_proven": False,
            "official_event_economics_cash_share_amount_verified": False,
            "full_adjusted_total_return_approved": False,
        })
    return {
        "schema_version": 1, "scope": SCOPE,
        "captured_at_utc": captured_at_utc.astimezone(timezone.utc).isoformat(),
        "source_months_queried": list(MONTHS),
        "official_twse_http_requests": len(history),
        "official_response_receipts": history,
        "official_target_issuer_event_rows": sorted(
            observed, key=lambda r: (r["event_date"], r["stock_id"],
                                     r["reported_event_category"])),
        "expected_issuer_retrospective_event_date_count": 6,
        "expected_events_found_in_official_twse_ex_feed": 6 - len(missing),
        "expected_event_date_pairs_not_observed": [
            {"stock_id": s, "ex_date": d} for s, d in missing],
        "additional_twse_ex_date_pairs_in_same_six_months": [
            {"stock_id": s, "ex_date": d} for s, d in extra],
        "retrospective_event_date_witnesses": rows,
        "all_six_known_dividend_dates_observed_in_twse_ex_feed": not missing,
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


def run_owner(*, prior, out):
    old = _phase("PRIVATE_RECEIPT", _private_file, prior, should_exist=True)
    new = _phase("PRIVATE_RECEIPT", _private_file, out, should_exist=False)
    if old == new:
        raise OwnerOfficialStageError("PRIVATE_RECEIPT")
    receipt = _phase("PRIOR_ISSUER_RECEIPT_GUARD",
                     lambda: json.loads(old.read_text(encoding="utf-8")))
    _phase("PRIOR_ISSUER_RECEIPT_GUARD", validate_private_prior, receipt)
    # This is the only network step, bounded to 12 official free TWSE GETs.
    def request(kind, start, end):
        return fetch_month_kind(kind, start, end, targets=STOCKS)
    report = _phase("TWSE_OFFICIAL_MONTH_RESPONSES", reconcile,
                    receipt, fetcher=request)
    data = _phase("PRIVATE_REPORT_WRITE",
                  lambda: json.dumps(report, ensure_ascii=False, indent=2,
                                     allow_nan=False) + "\n")
    if len(data.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise OwnerOfficialStageError("PRIVATE_REPORT_WRITE")
    def write():
        with new.open("x", encoding="utf-8") as fp:
            fp.write(data)
    _phase("PRIVATE_REPORT_WRITE", write)
    print(json.dumps({
        "status": "OWNER_1101_2330_TWSE_HISTORICAL_OFFICIAL_RESPONSE_CAPTURE_PASS",
        "official_twse_calls": report["official_twse_http_requests"],
        "six_issuer_dates_observed_at_twse": report[
            "expected_events_found_in_official_twse_ex_feed"],
        "six_issuer_dates_missing_twse": len(
            report["expected_event_date_pairs_not_observed"]),
        "original_announcement_pit_verified": False,
        "adjusted_total_return_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prior-issuer-research", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit(safe_error("UNCLASSIFIED"))
    try:
        run_owner(prior=args.prior_issuer_research, out=args.out)
    except OwnerOfficialStageError as e:
        raise SystemExit(safe_error(e.code)) from None
    except Exception:
        raise SystemExit(safe_error("UNCLASSIFIED")) from None


if __name__ == "__main__":
    main()
