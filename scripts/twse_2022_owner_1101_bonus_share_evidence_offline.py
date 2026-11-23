"""Owner-private TCC/1101 2022 bonus-share *candidate* arithmetic audit.

Requires the original owner 14-month / 28 TWSE historical source-response
receipt, but NEVER re-fetches public sources, queries Neon, reads owner AES,
reads stock prices, generates trading adjustment factors, or sends LINE.

The contemporaneous-looking MOPS text and issuance terms are available in
THIRD-PARTY republished disclosures; original MOPS bytes and first-published
timestamps remain UNAUTHENTICATED. A matching arithmetic ratio cannot
authenticate final share distribution, adjusted OHLCV, or economic return.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
import os

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2021_22_owner_remaining_action_months_readonly import (
    SCOPE as PRIOR_SCOPE, COMPLETE_MONTHS, FIRST_MONTHS,
    MISSING_MONTHS, EXPECTED_EX_DATE_PAIRS, SOURCES, STOCKS,
    _check_month_receipt, _check_event, month_bounds,
)
from scripts.twse_2021_22_owner_issuer_dividend_economics_offline import (
    ISSUER_TCC,
)

SCOPE = "OWNER_1101_2022_STOCK_BONUS_ECONOMICS_REPRINT_CANDIDATE_BLOCKED"
RESEARCH_DATE = "2026-11-23"
SOURCE_TCC = ISSUER_TCC
SOURCE_REPRINT_ADJUSTMENT = (
    "https://goodinfo.tw/tw/StockAnnounceDetail.asp?"
    "CLAIM_TIME=2022%2F07%2F06+18%3A49%3A23&STOCK_ID=1101"
)
SOURCE_REPRINT_ISSUANCE = (
    "https://m.moneydj.com/f1a.aspx?"
    "a=be14d588-be68-4e19-9bb7-d5255eb7633e"
)
STAGES = frozenset({
    "PRIVATE_RECEIPT", "PRIOR_14_MONTH_GUARD",
    "BONUS_RATIO_ECONOMICS_GUARD", "PRIVATE_REPORT_WRITE",
    "UNCLASSIFIED",
})
MAX_REPORT_BYTES = 12500

# Independent report values are deliberately strings to preserve
# exact *decimal transcription*, not binary floating point.
# This is a manual public research manifest, NOT original issuer MOPS.
CANDIDATE = {
    "stock_id": "1101",
    "ex_right_dividend_date": "2022-07-21",
    "cash_dividend_ntd_per_old_share_on_current_issuer_page": "0.99928258",
    "stock_dividend_nominal_ntd_per_old_share_on_current_issuer_page":
        "0.99928258",
    "new_shares_in_reported_reprint": "611617340",
    "new_common_share_par_ntd_in_reported_reprint": "10",
    "bonus_capitalization_total_ntd_in_reported_reprint": "6116173400",
    "bonus_new_shares_per_1000_old_shares_in_reprint": "99.928258",
    "announced_cash_total_ntd_in_reprint": "6116173402",
    "treasury_shares_not_reissued_in_revision_reprint": "4669600",
    "amendment_claimed_date_and_time_third_party_only":
        "2022-07-06 18:49:23",
}
INVARIANTS = {
    "all_source_interval_month_response_receipts_captured": True,
    "original_mops_publication_byte_archive_authenticated": False,
    "original_mops_first_publication_timestamp_authenticated": False,
    "capital_increase_final_registry_authenticated": False,
    "investor_received_exact_entitlement_and_fractional_share_rule_verified":
        False,
    "per_old_share_bonus_factor_approved_for_price_adjustment": False,
    "cash_dividend_actual_entitlement_and_payment_verified": False,
    "corporate_actions_exhaustive_for_all_sources_and_all_years": False,
    "strict_historical_point_in_time_availability_verified": False,
    "forward_adjusted_total_return_labels_approved": False,
    "production_neon_backfill_approved": False,
    "model_release": "BLOCKED",
    "neon_writes": 0,
    "line_messages_sent": 0,
    "paid_services_used": False,
}


class BonusEvidenceError(ValueError):
    def __init__(self, stage):
        self.stage = stage if stage in STAGES else "UNCLASSIFIED"
        super().__init__(self.stage)


def _phase(stage, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BonusEvidenceError:
        raise
    except Exception:
        raise BonusEvidenceError(stage) from None


def safe_error(stage):
    if stage not in STAGES:
        stage = "UNCLASSIFIED"
    return (
        "Owner 1101 bonus share evidence FAILED safely; diagnostic_stage="
        + stage + "; no private report, stock prices, key or Neon URI disclosed"
    )


def validate_prior(prior):
    """Pin the real PR262 14-month 28-response owner evidence shape."""
    if not isinstance(prior, dict):
        raise ValueError("Prior owner PR262 proof required")
    mandatory = {
        "schema_version": 1, "scope": PRIOR_SCOPE,
        "full_requested_calendar_start": "2021-11-23",
        "full_requested_calendar_end": "2022-12-30",
        "full_calendar_months_with_response_receipts": list(COMPLETE_MONTHS),
        "prior_6_months_and_12_official_requests_accepted": True,
        "new_calendar_months_queried": list(MISSING_MONTHS),
        "new_official_twse_http_requests": 16,
        "all_official_twse_http_response_receipts_count": 28,
        "prior_six_issuer_date_matches_preserved": True,
        "original_six_known_issuer_ex_dividend_pairs": 6,
        "additional_issuer_ex_right_dates_observed_in_new_eight_months": [],
        "additional_issuer_reduction_dates_observed_in_new_eight_months": [],
        "new_months_without_observed_issuer_ex_right_rows_does_not_prove_no_events": True,
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
        "paid_services_used": False, "model_release": "BLOCKED",
    }
    for key, expected in mandatory.items():
        got = prior.get(key)
        if type(got) is not type(expected) or got != expected:
            raise ValueError("Owner previous 28-response report field changed")
    for field in ("new_official_capture_at_utc", "prior_official_capture_at_utc"):
        stamp = prior.get(field)
        if type(stamp) is not str or len(stamp) > 60:
            raise ValueError("Missing prior capture date")
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None:
            raise ValueError("Unqualified prior source capture timestamp")
    receipts = prior.get("all_official_response_receipts")
    if not isinstance(receipts, list) or len(receipts) != 28:
        raise ValueError("28 exact TWSE monthly response receipts required")
    seen = set()
    for record in receipts:
        if not isinstance(record, dict):
            raise ValueError("Invalid prior source record")
        key = (record.get("month"), record.get("kind"))
        if key in seen or key[0] not in COMPLETE_MONTHS or key[1] not in SOURCES:
            raise ValueError("Unknown or duplicated prior source month-kind")
        seen.add(key)
        _check_month_receipt(record, month=key[0], kind=key[1])
        if (record.get("no_match_does_not_certify_zero_events") is not True):
            raise ValueError("No-event false proof rejected")
    if seen != {(month, kind) for month in COMPLETE_MONTHS for kind in SOURCES}:
        raise ValueError("Incomplete prior response month+kind keys")
    rows = prior.get("all_official_target_issuer_event_rows")
    if not isinstance(rows, list) or len(rows) != 6:
        raise ValueError("Expected six exact owner-confirmed exchange event rows")
    seen_events, per_month = set(), {}
    for event in rows:
        if not isinstance(event, dict) or type(event.get("event_date")) is not str:
            raise ValueError("Missing historical event date")
        month = event["event_date"][:7]
        start, end = month_bounds(month)
        key = _check_event(event, start=start, end=end)
        if key in seen_events or key[2] == "CAPITAL_REDUCTION":
            raise ValueError("Unexpected target source event")
        seen_events.add(key)
        pair = (month, "ex")
        per_month[pair] = per_month.get(pair, 0) + 1
    if {(sid, day) for sid, day, _ in seen_events} != set(EXPECTED_EX_DATE_PAIRS):
        raise ValueError("Prior six ex-right days not precisely corroborated")
    for rec in receipts:
        count = per_month.get((rec["month"], rec["kind"]), 0)
        if rec.get("two_current_issuer_event_rows") != count:
            raise ValueError("Actual source event rows mismatch prior monthly inventory")
    return True


def _positive_exact_decimal(value, expected):
    if type(value) is not str or value != expected:
        raise ValueError("Publisher-reported number has changed")
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("Invalid public candidate decimal")
    return parsed


def verify_candidate(candidate=CANDIDATE):
    if not isinstance(candidate, dict) or set(candidate) != set(CANDIDATE):
        raise ValueError("Unapproved public evidence manifest")
    for k, original in CANDIDATE.items():
        if type(candidate.get(k)) is not str or candidate[k] != original:
            raise ValueError("Noncanonical source-backed historical claim")
    cash_per_old = _positive_exact_decimal(
        candidate["cash_dividend_ntd_per_old_share_on_current_issuer_page"],
        "0.99928258",
    )
    nominal_bonus_ntd = _positive_exact_decimal(
        candidate["stock_dividend_nominal_ntd_per_old_share_on_current_issuer_page"],
        "0.99928258",
    )
    new_shares = _positive_exact_decimal(
        candidate["new_shares_in_reported_reprint"], "611617340")
    common_par = _positive_exact_decimal(
        candidate["new_common_share_par_ntd_in_reported_reprint"], "10")
    capital_ntd = _positive_exact_decimal(
        candidate["bonus_capitalization_total_ntd_in_reported_reprint"],
        "6116173400")
    per_thousand = _positive_exact_decimal(
        candidate["bonus_new_shares_per_1000_old_shares_in_reprint"],
        "99.928258")
    _positive_exact_decimal(
        candidate["announced_cash_total_ntd_in_reprint"], "6116173402")
    _positive_exact_decimal(
        candidate["treasury_shares_not_reissued_in_revision_reprint"], "4669600")
    if (new_shares * common_par != capital_ntd
            or nominal_bonus_ntd / common_par * Decimal(1000) != per_thousand
            or cash_per_old != nominal_bonus_ntd):
        raise ValueError("Republished cash/capital/par/ratio inconsistent")
    return {
        "candidate_new_shares_per_old_share": str(per_thousand / Decimal(1000)),
        "candidate_new_shares_per_1000_old_shares": str(per_thousand),
        "candidate_capital_ntd_reconstruction": str(capital_ntd),
        "candidate_nominal_share_dividend_ntd_per_old_share": str(nominal_bonus_ntd),
        "candidate_cash_dividend_ntd_per_old_share": str(cash_per_old),
        "historical_arithmetic_between_separately_republished_sources_matches": True,
        "historical_original_mops_economics_fully_authenticated": False,
    }


def evaluate(prior, *, candidate=CANDIDATE):
    validate_prior(prior)
    facts = verify_candidate(candidate)
    report = {
        "schema_version": 1, "scope": SCOPE,
        "source_research_date": RESEARCH_DATE,
        "source_first_party_retrospective_issuer": SOURCE_TCC,
        "source_third_party_mops_amendment_reprint":
            SOURCE_REPRINT_ADJUSTMENT,
        "source_third_party_mops_issuance_reprint":
            SOURCE_REPRINT_ISSUANCE,
        "all_three_sources_requeried_live_at_runtime": False,
        "first_party_current_retrospective_and_third_party_reprints_kept_distinct": True,
        "issuer_stock_id": "1101",
        "retrospective_ex_right_date": "2022-07-21",
        "third_party_claimed_amendment_publication": CANDIDATE[
            "amendment_claimed_date_and_time_third_party_only"],
        "third_party_claimed_issuance_new_common_shares": CANDIDATE[
            "new_shares_in_reported_reprint"],
        "third_party_claimed_treasury_stock_in_revision": CANDIDATE[
            "treasury_shares_not_reissued_in_revision_reprint"],
        "original_twse_14_month_28_response_receipts_guard_passed": True,
        "owner_AES_archives_reauthenticated_in_this_run": False,
        "neon_requeried_in_this_run": False,
        **facts, **INVARIANTS,
    }
    return report


def run_owner(*, prior, out):
    p = _phase("PRIVATE_RECEIPT", _private_file, prior, should_exist=True)
    target = _phase("PRIVATE_RECEIPT", _private_file, out, should_exist=False)
    if p == target:
        raise BonusEvidenceError("PRIVATE_RECEIPT")
    first = _phase(
        "PRIOR_14_MONTH_GUARD",
        lambda: json.loads(p.read_text(encoding="utf-8")))
    _phase("PRIOR_14_MONTH_GUARD", validate_prior, first)
    report = _phase("BONUS_RATIO_ECONOMICS_GUARD", evaluate, first)
    content = _phase("PRIVATE_REPORT_WRITE", lambda:
                     json.dumps(report, ensure_ascii=False, indent=2,
                                allow_nan=False) + "\n")
    if len(content.encode("utf-8")) > MAX_REPORT_BYTES:
        raise BonusEvidenceError("PRIVATE_REPORT_WRITE")
    def store():
        with target.open("x", encoding="utf-8") as fd:
            fd.write(content)
    _phase("PRIVATE_REPORT_WRITE", store)
    print(json.dumps({
        "status": "OWNER_1101_2022_BONUS_RATIO_REPRINT_ARITHMETIC_RESEARCH_PASS",
        "reviewed_stock_id": "1101",
        "candidate_new_shares_per_thousand_old": report[
            "candidate_new_shares_per_1000_old_shares"],
        "arithmetic_source_consistent": True,
        "original_mops_publication_verified": False,
        "trading_adjusted_total_return_approved": False,
        "model_release": "BLOCKED", "neon_writes": 0, "line_messages_sent": 0,
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prior-14-month-source", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit(safe_error("UNCLASSIFIED"))
    try:
        run_owner(prior=args.prior_14_month_source, out=args.out)
    except BonusEvidenceError as exc:
        raise SystemExit(safe_error(exc.stage)) from None
    except Exception:
        raise SystemExit(safe_error("UNCLASSIFIED")) from None


if __name__ == "__main__":
    main()
