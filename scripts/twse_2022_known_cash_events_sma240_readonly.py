"""Owner-only 2022 *two known cash events* price-scale SMA240 (READ ONLY).

Must not be confused with full corporate-action adjustment or investible
total-return. Includes the dated 2022 cash dividend and later cash capital
reduction, on 240 *real per-stock* sessions through 2022-12-30. The
transformation is event-order-aware but omits other dividends and splits.

Reauthenticates both owners' AES 2021+2022 and READ ONLY Neon; independently
rederives previously accepted private evidence. No synthetic halt stock bars,
Neon writes, LINE calls, model release, raw price or SMA output.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from scripts.twse_2021_22_traded_240_warmup_readonly import (
    EXPECTED_2021, STOCKS, _private_archives, _private_file, _replay_2021,
)
from scripts.twse_2022_reduction_only_240_sma_readonly import (
    SMA_SCOPE, calculate_event_only_sma240,
)
from scripts.twse_2022_dividend_exref_readonly import (
    EVENTS as DIV_EVENTS, SCOPE as DIV_SCOPE, verify_precise_cash_reference,
)
from scripts.twse_2022_cash_reduction_reference_readonly import EVENTS as RED_EVENTS
from scripts.twse_2022_aes_factor_readiness import audit as audit_2022
from scripts.twse_2022_aes_neon_readonly_240_panel import (
    _authenticated_rows, _read_neon_2022_frozen_panel, reconcile,
)
from scripts.twse_2022_corporate_halt_audit import EXPECTED_HALT_SESSIONS
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_local_encrypted_archive import verify_archive

SCOPE = "OWNER_2022_TWSE_TWO_KNOWN_CASH_EVENTS_REAL_TRADED_SMA240_RESEARCH"


def two_known_event_price_scale(
    original_close: Decimal, traded_day: date,
    cash_dividend: Decimal, dividend_ex_date: date,
    cash_reduction: Decimal, reduction_last_old_date: date,
    reduction_resume_date: date, new_shares_per_old: Decimal,
) -> Decimal:
    """Map two known 2022 events only to end-2022 new-share cash-ex scale.

    For a genuinely traded bar:
      before dividend ex-date: (old close - dividend - refund) / share ratio
      after dividend, before cash reduction: (old close - refund) / ratio
      on/after reduction resumption: raw new-share close

    Not a true total-return index, tax-adjusted equity return, complete
    corporate-action-adjusted close or executable historical signal.
    """
    vals = (original_close, cash_dividend, cash_reduction, new_shares_per_old)
    if (type(traded_day) is not date
            or any(type(v) is not Decimal or not v.is_finite() for v in vals)
            or original_close <= 0 or cash_dividend <= 0 or cash_reduction < 0
            or not Decimal(0) < new_shares_per_old < Decimal(1)
            or not dividend_ex_date < reduction_last_old_date < reduction_resume_date):
        raise ValueError("Invalid ordered published 2022 cash-event terms")
    if reduction_last_old_date < traded_day < reduction_resume_date:
        raise ValueError("No genuine traded stock day inside capital reduction halt")
    if traded_day >= reduction_resume_date:
        return original_close
    cash_adjusted = original_close - cash_reduction
    if traded_day < dividend_ex_date:
        cash_adjusted -= cash_dividend
    scaled = cash_adjusted / new_shares_per_old
    if not scaled.is_finite() or scaled <= 0:
        raise ValueError("Nonpositive or invalid known-event price scale")
    return scaled


def calculate_two_known_cash_events(
    original, reconciled, warmup, reduction_reference, reduction_sma,
    dividend_gap, dividend_reference, market2021, market2022,
    bars2021, bars2022,
):
    """Pure fail-closed proof. Prior report parity and 2022 source precede SMA."""
    existing_reduction = calculate_event_only_sma240(
        original, reconciled, warmup, reduction_reference,
        market2021, market2022, bars2021, bars2022)
    if (not isinstance(reduction_sma, dict)
            or reduction_sma != existing_reduction
            or reduction_sma.get("scope") != SMA_SCOPE
            or reduction_sma.get("live_model_release_decision") != "BLOCKED"):
        raise ValueError("Previously verified reduction-only SMA report drifted")

    dividend_witness = {
        (sid, d): bars2022[sid][d]
        for sid, event in DIV_EVENTS.items()
        for d in (event["pre_ex_trade"], event["ex_trade"])
        if d in bars2022[sid]
    }
    refreshed_dividend = verify_precise_cash_reference(
        original, reconciled, dividend_gap, market2022, dividend_witness)
    if (not isinstance(dividend_reference, dict)
            or dividend_reference != refreshed_dividend
            or dividend_reference.get("scope") != DIV_SCOPE
            or dividend_reference.get("live_model_release_decision") != "BLOCKED"):
        raise ValueError("Previously verified precise dividend ex-reference report drifted")

    cutoff = max(market2022)
    if (cutoff != date(2022, 12, 30)
            or original.get("last_combined_session") != cutoff.isoformat()):
        raise ValueError("Only bounded 2022 year-end research cutoff permitted")
    details = []
    for sid in STOCKS:
        dividend, reduction = DIV_EVENTS[sid], RED_EVENTS[sid]
        divdate, cash = dividend["ex_trade"], dividend["declared_cash_per_old_share"]
        reduction_old, reduction_new = (
            reduction["last_old_trade"], reduction["first_new_trade"]
        )
        if (not dividend["issuer_announcement_date"] < divdate
                or not divdate < dividend["payout_scheduled"] < reduction_old
                or not reduction["announcement_date"] < reduction_new
                or not reduction_new < reduction["cash_refund_payment"] <= cutoff
                or dividend["payout_scheduled"] > cutoff):
            raise ValueError("Cash event publication, entitlement or settlement order invalid")
        if (not isinstance(bars2021[sid], dict)
                or not isinstance(bars2022[sid], dict)):
            raise ValueError("Missing bounded individual stock close evidence")
        raw = {**bars2021[sid], **bars2022[sid]}
        if (len(raw) != 267
                or len(bars2021[sid]) != 28
                or len(bars2022[sid]) != 239
                or set(bars2021[sid]) & set(bars2022[sid])):
            raise ValueError("Authentic 2021+2022 two-stock source dates have changed")
        dates = sorted(raw)[-240:]
        halts = {date.fromisoformat(d) for d in EXPECTED_HALT_SESSIONS[sid]}
        if (len(dates) != 240 or len(set(dates)) != 240
                or dates[0] != date(2021, 12, 30) or dates[-1] != cutoff
                or set(dates) & halts
                or not all(d in dates for d in (
                    dividend["pre_ex_trade"], divdate, reduction_old, reduction_new))
                or any(reduction_old < d < reduction_new for d in raw)):
            raise ValueError("Genuine 240 trading dates / known event dates inconsistent")
        baseline_reduced = []
        combined_adjusted = []
        n_before_div = n_between = n_after = 0
        for d in dates:
            close = raw[d]
            if type(close) is not Decimal or not close.is_finite() or close <= 0:
                raise ValueError("Unverified actual close")
            reduced_only = close if d >= reduction_new else (
                (close - reduction["cash_per_old_share"]) /
                reduction["new_shares_per_old"])
            combined = two_known_event_price_scale(
                close, d, cash, divdate,
                reduction["cash_per_old_share"],
                reduction_old, reduction_new, reduction["new_shares_per_old"],
            )
            if d < divdate:
                n_before_div += 1
            elif d <= reduction_old:
                n_between += 1
            else:
                n_after += 1
            baseline_reduced.append(reduced_only)
            combined_adjusted.append(combined)
        if (not n_before_div or not n_between or not n_after
                or n_before_div + n_between + n_after != 240):
            raise ValueError("Both chronologically ordered events must cross full 240 window")
        reduction_mean = sum(baseline_reduced, Decimal(0)) / Decimal(240)
        combined_mean = sum(combined_adjusted, Decimal(0)) / Decimal(240)
        exact_known_difference = (
            Decimal(n_before_div) * cash /
            reduction["new_shares_per_old"] / Decimal(240))
        if (not reduction_mean.is_finite() or not combined_mean.is_finite()
                or combined_mean <= 0 or combined_mean >= reduction_mean
                or abs((reduction_mean - combined_mean) - exact_known_difference)
                   > Decimal("0.00000000000000000001")):
            raise ValueError("2022 known dividend cross-event normalization identity failed")
        details.append({
            "stock_id": sid,
            "asof_date": cutoff.isoformat(),
            "last240_first_stock_trade": dates[0].isoformat(),
            "last240_last_stock_trade": dates[-1].isoformat(),
            "genuine_source_stock_trading_days": len(dates),
            "pre_ex_dividend_old_share_stock_days_transformed": n_before_div,
            "between_dividend_and_capital_reduction_stock_days_transformed": n_between,
            "after_capital_reduction_stock_days_untouched": n_after,
            "capital_reduction_halt_market_days_never_imputed": len(halts),
            "only_two_previously_verified_cash_events_applied": True,
            "exact_decimal_sma240_in_ram": True,
            "known_dividend_amount_lowers_cash_ex_price_scale_sma": True,
            "full_dividend_split_action_ledger_proven": False,
            "historical_pit_signal_asof_proven": False,
            "total_return_reinvested_cash_portfolio_proven": False,
            "price_or_sma_persisted": False,
            "full_model_release_approved": False,
        })
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "research_asof_session": cutoff.isoformat(),
        "two_known_cash_events_sma240_stock_count": len(details),
        "dated_dividend_events_included": 2,
        "dated_capital_reduction_events_included": 2,
        "genuine_halt_market_days_no_fake_bars": 14,
        "prior_frozen20_market_day_sma240_readiness_unchanged": 18,
        "per_stock_two_known_event_research_proofs": details,
        "corporate_actions_master_complete": False,
        "adjustment_covers_all_historical_dividends": False,
        "historical_listing_membership_or_capture_vintage_certified": False,
        "total_return_cash_payment_or_reinvestment_certified": False,
        "five_year_full_source_history_certified": False,
        "walkforward_forward_alpha_or_trading_approved": False,
        "no_private_numeric_sma_or_raw_price_emitted": True,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_service_required": False,
        "live_model_release_decision": "BLOCKED",
    }


def run_local(*, archive_2021, archive_2022, key_vault,
              source_report, warmup_report, reduction_reference_report,
              reduction_sma_report, dividend_gap_report,
              dividend_reference_report, output):
    a2021, a2022 = (
        _private_archives(archive_2021), _private_archives(archive_2022))
    if set(a2021) & set(a2022):
        raise ValueError("Owner encrypted archive directories overlap")
    inputs = [
        _private_file(name, should_exist=True)
        for name in (
            source_report, warmup_report, reduction_reference_report,
            reduction_sma_report, dividend_gap_report, dividend_reference_report,
        )
    ]
    out = _private_file(output, should_exist=False)
    if len(set(inputs + [out])) != 7:
        raise ValueError("Private evidence source/output paths must be different")
    source, warmup, reduction_ref, reduction_sma, div_gap, div_ref = (
        json.loads(p.read_text(encoding="utf-8")) for p in inputs)
    if (not isinstance(source, dict) or source.get("live_model_release_decision") != "BLOCKED"
            or not isinstance(reduction_sma, dict)
            or reduction_sma.get("live_model_release_decision") != "BLOCKED"
            or not isinstance(div_ref, dict)
            or div_ref.get("live_model_release_decision") != "BLOCKED"):
        raise ValueError("Owner private preceding source reports must remain blocked")
    key = resolve_archive_key(
        vault_path=Path(key_vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""))
    market2021, observed2021 = _replay_2021(a2021, hex_key=key)
    before = {p: sha256(p.read_bytes()).hexdigest() for p in a2021}
    bars2021 = {sid: {} for sid in STOCKS}
    for path in a2021:
        def accept(row):
            sid, d = row["stock_id"], row["trade_date"]
            if sid in bars2021:
                if d not in EXPECTED_2021 or d in bars2021[sid]:
                    raise ValueError("Wrong-year or duplicate original 2021 stock bar")
                bars2021[sid][d] = row["close"]
        audit = verify_archive(path, hex_key=key, on_verified_row=accept)
        if audit.get("archive_integrity_verified") is not True:
            raise ValueError("Private 2021 AES reauthentication failed")
    if ({p: sha256(p.read_bytes()).hexdigest() for p in a2021} != before
            or any(set(bars2021[sid]) != observed2021[sid] for sid in STOCKS)):
        raise ValueError("2021 AES changed during repeated replay")

    proof = audit_2022(a2022, hex_key=key, spotchecks=0)
    stream, hashes = _authenticated_rows(
        a2022, hex_key=key,
        expected_bundle_digest=proof["authenticated_file_digest_bundle_sha256"])
    bars2022 = {sid: {} for sid in STOCKS}
    market2022 = set()

    def replay_local():
        for row in stream:
            d, sid = row["trade_date"], row["stock_id"]
            market2022.add(d)
            if sid in bars2022:
                if d in bars2022[sid]:
                    raise ValueError("Duplicated authenticated 2022 AES stock-day")
                bars2022[sid][d] = row["close"]
            yield row

    neon_days, neon_rows = _read_neon_2022_frozen_panel()
    reconciled = reconcile(
        replay_local(), neon_rows, neon_days, local_audit=proof)
    if sha256(json.dumps(hashes, separators=(",", ":")).encode()).hexdigest() != (
            proof["authenticated_file_digest_bundle_sha256"]):
        raise ValueError("2022 private AES bundle has changed")
    market2022.update(neon_days)
    for row in neon_rows:
        sid, d = row["stock_id"], row["trade_date"]
        if sid in bars2022:
            prior = bars2022[sid].get(d)
            if prior is not None and prior != row["close"]:
                raise ValueError("Neon vs AES same stock-day close conflict")
            bars2022[sid][d] = row["close"]
    result = calculate_two_known_cash_events(
        source, reconciled, warmup, reduction_ref, reduction_sma,
        div_gap, div_ref, market2021, market2022, bars2021, bars2022)
    with out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": "TWO_KNOWN_2022_CASH_EVENTS_240_SMA_RESEARCH_PASS",
        "two_stock_exact_decimal_research_count":
            result["two_known_cash_events_sma240_stock_count"],
        "historical_company_action_history_complete": False,
        "real_total_return_approved": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(
        description="2022 research-only 2327/2603 240 actual-trading-day two cash events")
    p.add_argument("--archive-2021", required=True)
    p.add_argument("--archive-2022", required=True)
    p.add_argument("--key-vault", required=True)
    p.add_argument("--source-report", required=True)
    p.add_argument("--warmup-report", required=True)
    p.add_argument("--reduction-reference-report", required=True)
    p.add_argument("--reduction-sma-report", required=True)
    p.add_argument("--dividend-gap-report", required=True)
    p.add_argument("--dividend-reference-report", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        run_local(
            archive_2021=args.archive_2021,
            archive_2022=args.archive_2022,
            key_vault=args.key_vault,
            source_report=args.source_report,
            warmup_report=args.warmup_report,
            reduction_reference_report=args.reduction_reference_report,
            reduction_sma_report=args.reduction_sma_report,
            dividend_gap_report=args.dividend_gap_report,
            dividend_reference_report=args.dividend_reference_report,
            output=args.out,
        )
    except Exception:
        raise SystemExit(
            "Private two-known-cash-event SMA240 proof FAILED; "
            "no Neon writes, LINE messages or raw prices printed"
        ) from None


if __name__ == "__main__":
    main()
