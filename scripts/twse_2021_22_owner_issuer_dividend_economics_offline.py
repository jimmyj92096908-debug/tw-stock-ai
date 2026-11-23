"""Owner-only offline issuer dividend retrospective evidence, NOT total returns.

The input is the already-passed PRIVATE read-only 1101/2330 action gap receipt.
No new AES authentication, Neon access, live issuer website scrape, prices,
secrets, paid services, LINE calls, or DB writes. The compact static official
issuer dividend schedule was human-reviewed on 2026-11-23; publication
vintage, complete corporate-action universe and PIT-adjusted returns remain
unverified and BLOCKED.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import os

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2021_22_owner_two_stock_action_gap_readonly import (
    SCOPE as GAP_SCOPE, CANDIDATES,
)

SCOPE = "OWNER_2021_22_1101_2330_ISSUER_RETROSPECTIVE_DIVIDEND_ECONOMICS_BLOCKED"
REVIEW_DATE = "2026-11-23"
ISSUER_TCC = "https://www.tccgroupholdings.com/dividend"
ISSUER_TSMC = "https://investor.tsmc.com/chinese/dividends"
MAX_PRIVATE_BYTES = 15000

# Issuer-provided *retrospective* shareholder dividend tables, checked by
# human research 2026-11-23. TCC's stock dividend is its *NTD nominal*
# dividend/share, NOT an independently verified number of new shares.
# Tuple: issuer, ex-date, cash NTD/share, stock nominal NTD/share,
#        issuer record date if table explicitly states it, cash pay date,
#        official issuer source URL.
ISSUER_ECONOMICS = (
    ("1101", "2022-07-21", "0.99928258", "0.99928258", None,
     "2022-08-22", ISSUER_TCC),
    ("2330", "2021-12-16", "2.75", "0", "2021-12-22",
     "2022-01-13", ISSUER_TSMC),
    ("2330", "2022-03-16", "2.75", "0", "2022-03-22",
     "2022-04-14", ISSUER_TSMC),
    ("2330", "2022-06-16", "2.75", "0", "2022-06-22",
     "2022-07-14", ISSUER_TSMC),
    ("2330", "2022-09-15", "2.75", "0", "2022-09-21",
     "2022-10-13", ISSUER_TSMC),
    ("2330", "2022-12-15", "2.75", "0", "2022-12-21",
     "2023-01-12", ISSUER_TSMC),
)

# A 2022-06-23 19:53:53 initial notice and a 2022-07-06 18:49:23
# revision were reproduced on third-party sites from MOPS announcements.
# These are NOT authenticated original issuer/MOPS publication timestamps.
TCC_MOPS_MIRROR = (
    ("2022-06-23", "19:53:53", "INITIAL_CASH_AND_STOCK_RECORD"),
    ("2022-07-06", "18:49:23", "PER_SHARE_CASH_AND_STOCK_REVISION"),
)

STAGES = frozenset({
    "PRIVATE_RECEIPT", "PRIOR_ACTION_GAP_GUARD",
    "RETROSPECTIVE_ISSUER_LEDGER_GUARD", "PRIVATE_REPORT_WRITE",
    "UNCLASSIFIED",
})


class IssuerEvidenceError(ValueError):
    def __init__(self, code):
        self.code = code if code in STAGES else "UNCLASSIFIED"
        super().__init__(self.code)


def _phase(stage, fn, *args, **kwargs):
    if stage not in STAGES:
        raise IssuerEvidenceError("UNCLASSIFIED")
    try:
        return fn(*args, **kwargs)
    except IssuerEvidenceError:
        raise
    except Exception:
        raise IssuerEvidenceError(stage) from None


def _safe_error(code):
    if code not in STAGES:
        code = "UNCLASSIFIED"
    return ("Owner issuer dividend evidence FAILED safely; diagnostic_stage="
            + code + "; no private receipt, price, key, path or URI disclosed")


def verify_action_gap_receipt(receipt):
    """Accept the exact owner-pass missing-six status, not fabricated success."""
    if not isinstance(receipt, dict):
        raise ValueError("Invalid prior receipt type")
    guards = {
        "schema_version": 1,
        "scope": GAP_SCOPE,
        "window_start": "2021-11-23",
        "window_end": "2022-12-30",
        "current_eligible_stocks": ["1101", "2330"],
        "private_prior_2330_and_1101_raw_source_receipts_guard_passed": True,
        "prior_receipts_are_cryptographically_reauthenticated_here": False,
        "neon_issuer_raw_source_days": {"1101": 274, "2330": 274},
        "stored_action_rows_in_entire_two_stock_window": 0,
        "stored_action_rows_by_stock": {"1101": 0, "2330": 0},
        "historical_candidate_event_dates": 6,
        "candidate_dates_without_stored_action": 6,
        "retrospective_event_date_is_original_publication_vintage": False,
        "known_event_candidates_prove_complete_action_universe": False,
        "stock_dividend_adjustments_verified": False,
        "cash_dividend_entitlement_and_payment_verified": False,
        "capital_reduction_and_split_universe_verified": False,
        "tax_fee_reinvestment_and_total_return_verified": False,
        "adjusted_prices_or_raw_sma240_promoted_to_trading_signal": False,
        "real_future_return_labels_approved": False,
        "production_backfill_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_requested": False,
    }
    for key, expected in guards.items():
        val = receipt.get(key)
        if type(val) is not type(expected) or val != expected:
            raise ValueError("Prior action gap report failed a restricted field")
    items = receipt.get("candidate_date_witnesses")
    if not isinstance(items, list) or len(items) != 6:
        raise ValueError("Exactly six historical candidate witnesses required")
    original = {(sid, day.isoformat()): (category, strength)
                for sid, day, category, strength, _ in CANDIDATES}
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid dated witness")
        key = (item.get("stock_id"), item.get("candidate_ex_date"))
        if key not in original or key in seen:
            raise ValueError("Missing or duplicate historical witness")
        seen.add(key)
        category, strength = original[key]
        expected = {
            "retrospective_event_category": category,
            "retrospective_evidence_tier": strength,
            "official_raw_stock_day_exists": True,
            "same_date_stored_action_rows": 0,
            "same_date_stored_verified_action_rows": 0,
            "status": "NO_ACTION_RECORD_ON_CANDIDATE_DATE",
            "complete_event_amount_or_share_economics_verified": False,
            "original_issuer_announcement_publication_timestamp_verified": False,
            "historical_total_return_label_approved": False,
        }
        for field, val in expected.items():
            actual = item.get(field)
            if type(actual) is not type(val) or actual != val:
                raise ValueError("Prior dated witness changed or was promoted")
    if seen != set(original):
        raise ValueError("Incomplete historical event list")
    return True


def _safe_decimal(s):
    if type(s) is not str or len(s) > 20:
        raise ValueError("Noncanonical issuer amount")
    try:
        x = Decimal(s)
    except (InvalidOperation, ValueError, TypeError) as e:
        raise ValueError("Invalid issuer amount") from e
    if not x.is_finite() or x < 0 or str(x) != s:
        raise ValueError("Non-finite, negative or ambiguous issuer amount")
    return x


def check_issuer_economics(ledger=ISSUER_ECONOMICS):
    """Research ledger must exactly correspond to the six *dated* gaps."""
    if type(ledger) not in (list, tuple) or len(ledger) != 6:
        raise ValueError("Six exact issuer retrospective rows required")
    expected = {(s, d.isoformat()) for s, d, *_ in CANDIDATES}
    seen = set()
    results = []
    for sid, ex, cash, stock, record, payment, uri in ledger:
        key = (sid, ex)
        if key not in expected or key in seen:
            raise ValueError("Unexpected issuer/date or duplicate issuer event")
        seen.add(key)
        event_day = date.fromisoformat(ex)
        if event_day.isoformat() != ex or not date(2021, 11, 23) <= event_day <= date(2022, 12, 30):
            raise ValueError("Issuer event outside validated source window")
        if uri != (ISSUER_TCC if sid == "1101" else ISSUER_TSMC):
            raise ValueError("Only original issuer dividend pages may be research evidence")
        if (sid == "2330" and (cash != "2.75" or stock != "0")
                or sid == "1101" and (cash != "0.99928258"
                                      or stock != "0.99928258")):
            raise ValueError("Issuer amount deviated from reviewed source")
        _safe_decimal(cash)
        _safe_decimal(stock)
        if sid == "2330":
            if record is None:
                raise ValueError("TSMC issuer record date must be present")
        elif record is not None:
            raise ValueError("Do not infer TCC record date from missing issuer column")
        for name, value in (("record_date", record), ("cash_payment_date", payment)):
            if value is not None:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value or parsed < event_day:
                    raise ValueError(name + " chronology invalid")
        results.append({
            "stock_id": sid,
            "ex_date": ex,
            "issuer_retrospective_cash_ntd_per_common_share": cash,
            "issuer_retrospective_stock_dividend_nominal_ntd_per_share": stock,
            "issuer_published_record_date_if_present": record,
            "issuer_published_cash_payment_date": payment,
            "issuer_source": uri,
            "issuer_retrospective_schedule_reviewed": True,
            "original_mops_announcement_bytes_or_timestamp_authenticated": False,
            "stock_dividend_new_shares_per_old_share_verified": False,
            "investor_cash_entitlement_withholding_verified": False,
            "point_in_time_usable_in_trading_model": False,
            "economic_total_return_adjustment_approved": False,
        })
    if seen != expected:
        raise ValueError("Missing event from issuer retrospective ledger")
    return results


def evaluate(receipt, *, ledger=ISSUER_ECONOMICS):
    verify_action_gap_receipt(receipt)
    checked = check_issuer_economics(ledger)
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "issuer_evidence_review_date": REVIEW_DATE,
        "research_evidence_events": checked,
        "reviewed_issuer_retrospective_event_rows": 6,
        "original_neon_action_gaps_in_previous_owner_snapshot": 6,
        "source_proof_is_offline_manual_issuer_page_transcription": True,
        "source_issuer_urls_checked_at_runtime": False,
        "owner_original_AES_ciphertexts_reauthenticated_in_this_run": False,
        "new_neon_snapshot_performed_in_this_run": False,
        "mops_original_first_publication_timestamp_proven": False,
        "tcc_mops_mirror_claimed_revisions": [
            {"claimed_date": d, "claimed_time": t, "type": kind,
             "claim_provenance": "THIRD_PARTY_MOPS_REPRINT_NOT_ORIGINAL"}
            for d, t, kind in TCC_MOPS_MIRROR
        ],
        "tcc_stock_dividend_new_shares_factor_verified": False,
        "corporate_action_universe_complete": False,
        "publication_vintage_and_asof_eligibility_verified": False,
        "raw_price_adjustment_factors_verified": False,
        "real_forward_total_return_labels_approved": False,
        "production_backfill_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_requested": False,
    }


def run_owner(*, prior_action_gap, out):
    old = _phase("PRIVATE_RECEIPT", _private_file, prior_action_gap,
                 should_exist=True)
    target = _phase("PRIVATE_RECEIPT", _private_file, out, should_exist=False)
    if old == target:
        raise IssuerEvidenceError("PRIVATE_RECEIPT")
    prior = _phase("PRIOR_ACTION_GAP_GUARD",
                   lambda: json.loads(old.read_text(encoding="utf-8")))
    _phase("PRIOR_ACTION_GAP_GUARD", verify_action_gap_receipt, prior)
    report = _phase("RETROSPECTIVE_ISSUER_LEDGER_GUARD", evaluate, prior)
    data = _phase("PRIVATE_REPORT_WRITE",
                  lambda: json.dumps(report, ensure_ascii=False, indent=2,
                                     allow_nan=False) + "\n")
    if len(data.encode("utf-8")) > MAX_PRIVATE_BYTES:
        raise IssuerEvidenceError("PRIVATE_REPORT_WRITE")
    def store():
        with target.open("x", encoding="utf-8") as stream:
            stream.write(data)
    _phase("PRIVATE_REPORT_WRITE", store)
    print(json.dumps({
        "status": "OWNER_1101_2330_ISSUER_RETROSPECTIVE_ECONOMICS_RESEARCH_PASS",
        "issuer_retrospective_event_count": 6,
        "previous_owner_snapshot_missing_action_count": 6,
        "source_urls_checked_live": False,
        "original_publication_time_verified": False,
        "adjusted_total_return_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0, "line_messages_sent": 0,
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prior-action-gap", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit(_safe_error("UNCLASSIFIED"))
    try:
        run_owner(prior_action_gap=args.prior_action_gap, out=args.out)
    except IssuerEvidenceError as exc:
        raise SystemExit(_safe_error(exc.code)) from None
    except Exception:
        raise SystemExit(_safe_error("UNCLASSIFIED")) from None


if __name__ == "__main__":
    main()
