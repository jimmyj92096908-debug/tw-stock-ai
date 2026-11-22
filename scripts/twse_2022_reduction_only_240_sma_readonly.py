"""Owner-local, research-only 2022 cash-reduction-event SMA240 proof.

Authenticates all existing 2021 and 2022 AES, reconciles the frozen 2022
Neon panel in a server-enforced READ ONLY transaction, then calculates a
single-event *cash-reduction-only* price-scale SMA240 in RAM for 2327/2603.

This is NOT dividend-adjusted, total-return, as-of-universe-correct,
complete five-year history, a general historical backtest, or live approval.
Never creates phantom stock trades over the 14 issuer halt dates.
No raw close/adjusted-price/SMA data is persisted or printed.
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
    EXPECTED_2021, SOURCE_KEYS, STOCKS,
    _private_archives, _private_file, _replay_2021,
    summarize_real_traded_warmup,
)
from scripts.twse_2022_cash_reduction_reference_readonly import (
    EVENTS, prove_cash_reduction_references,
    pure_reference_cash_reduction, economic_one_old_share_value,
)
from scripts.twse_2022_aes_factor_readiness import audit as audit_2022
from scripts.twse_2022_aes_neon_readonly_240_panel import (
    _authenticated_rows, _read_neon_2022_frozen_panel, reconcile,
)
from scripts.twse_2022_corporate_halt_audit import EXPECTED_HALT_SESSIONS
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_local_encrypted_archive import verify_archive


WARMUP_SCOPE = "OWNER_ONLY_2021_22_TWSE_TWO_STOCK_REAL_TRADED_240_WARMUP"
EVENT_SCOPE = "OWNER_ONLY_2022_TWSE_CASH_REDUCTION_OFFICIAL_REFERENCE_PARITY"
SMA_SCOPE = "OWNER_LOCAL_2022_REDUCTION_ONLY_REAL_TRADED_SMA240_TWO_STOCK_RESEARCH"


def calculate_event_only_sma240(
    original, recomputed, warmup, reference, market2021, market2022,
    bars2021, bars2022,
):
    """Pure fail-closed exact Decimal calculation; only aggregate booleans leave.

    Uses the known-in-2022 capital-reduction ratio/cash on observations BEFORE
    the event: (old close - cash per old share) / new shares per old share.
    This is a post-event *single-event-adjusted price scale*, not a full
    dividend-adjusted/total-return index. Only as-of after refund settlement.
    """
    if (not isinstance(original, dict) or not isinstance(recomputed, dict)
            or any(original.get(k) != recomputed.get(k) for k in SOURCE_KEYS)
            or original.get("neon_transaction_mode") != "READ_ONLY"
            or original.get("neon_write_operations") != 0
            or original.get("line_messages_sent") != 0
            or recomputed.get("live_model_release_decision") != "BLOCKED"):
        raise ValueError("Original versus recomputed 2022 evidence drifted")
    if (not isinstance(bars2021, dict) or not isinstance(bars2022, dict)
            or set(bars2021) != set(STOCKS)
            or set(bars2022) != set(STOCKS)):
        raise ValueError("Unexpected research stock cohort")
    for sid in STOCKS:
        if not isinstance(bars2021[sid], dict) or not isinstance(bars2022[sid], dict):
            raise ValueError("Invalid per-stock authenticated close ledger")
        for d, close in (*bars2021[sid].items(), *bars2022[sid].items()):
            if (type(d) is not date or type(close) is not Decimal
                    or not close.is_finite() or close <= 0):
                raise ValueError("Unverified original stock/day/close")

    expected_warmup = summarize_real_traded_warmup(
        original, recomputed, market2022, market2021,
        {sid: set(bars2021[sid]) for sid in STOCKS},
        {sid: set(bars2022[sid]) for sid in STOCKS},
    )
    if warmup != expected_warmup or warmup.get("scope") != WARMUP_SCOPE:
        raise ValueError("2021/22 240 authentic traded-bar private warmup proof drifted")

    close_witness = {
        (sid, d): bars2022[sid][d]
        for sid, ev in EVENTS.items()
        for d in (ev["last_old_trade"], ev["first_new_trade"])
        if d in bars2022[sid]
    }
    expected_reference = prove_cash_reduction_references(
        original, recomputed, market2022, close_witness)
    if reference != expected_reference or reference.get("scope") != EVENT_SCOPE:
        raise ValueError("Previously accepted 2022 cash reference evidence drifted")

    cutoff = max(market2022)
    if (type(cutoff) is not date or cutoff.year != 2022
            or cutoff.isoformat() != original.get("last_combined_session")
            or any(cutoff < EVENTS[sid]["cash_refund_payment"] for sid in STOCKS)):
        raise ValueError("Only post-event 2022 as-of cutoff may be adjusted")
    details = []
    for sid in STOCKS:
        ev = EVENTS[sid]
        merged = {**bars2021[sid], **bars2022[sid]}
        if len(merged) != 267 or len(bars2021[sid]) != 28 or len(bars2022[sid]) != 239:
            raise ValueError("Not exactly 267 genuine stock-day closes")
        if set(bars2021[sid]) & set(bars2022[sid]):
            raise ValueError("Overlapping 2021/2022 stock trading dates")
        dates = sorted(merged)
        last240 = dates[-240:]
        old = ev["last_old_trade"]
        new = ev["first_new_trade"]
        halts = {date.fromisoformat(v) for v in EXPECTED_HALT_SESSIONS[sid]}
        if (len(last240) != 240 or len(set(last240)) != 240
                or set(last240) & halts
                or last240[-1] != cutoff
                or last240[0].year != 2021
                or old not in last240 or new not in last240
                or any(old < d < new for d in merged)
                or not ev["announcement_date"] < new <= ev["cash_refund_payment"]
                    <= cutoff):
            raise ValueError("Event or last-240 authentic stock date cutoff invalid")
        adjusted = []
        pre_count = 0
        for d in last240:
            close = merged[d]
            if d <= old:
                close = (close - ev["cash_per_old_share"]) / ev["new_shares_per_old"]
                pre_count += 1
            if not close.is_finite() or close <= 0:
                raise ValueError("Cash-reduction-only normalized historic price invalid")
            adjusted.append(close)
        if (pre_count == 0 or pre_count >= 240
                or pre_count + len([d for d in last240 if d >= new]) != 240
                or abs(
                    (merged[old] - ev["cash_per_old_share"]) / ev["new_shares_per_old"]
                    - ev["published_theoretical_reference"]
                ) >= Decimal(".01")):
            raise ValueError("Cash ex-date boundary or reference-price parity failed")
        sma = sum(adjusted, Decimal(0)) / Decimal(240)
        raw_sma = sum((merged[d] for d in last240), Decimal(0)) / Decimal(240)
        if (not sma.is_finite() or sma <= 0 or sma == raw_sma
                or pure_reference_cash_reduction(
                    merged[old], ev["cash_per_old_share"],
                    ev["new_shares_per_old"]) <= 0
                or economic_one_old_share_value(
                    merged[new], ev["cash_per_old_share"],
                    ev["new_shares_per_old"]) <= 0):
            raise ValueError("Invalid event-only exact SMA or entitlement formula")
        # Numeric raw/adjusted prices and SMA stay in RAM; do not claim a
        # production-adjusted series, total return, or predictive model signal.
        details.append({
            "stock_id": sid,
            "asof_market_session": cutoff.isoformat(),
            "last240_first_real_stock_session": last240[0].isoformat(),
            "last240_final_real_stock_session": last240[-1].isoformat(),
            "source_traded_days_2021": len(bars2021[sid]),
            "source_traded_days_2022": len(bars2022[sid]),
            "last240_real_traded_days": len(last240),
            "event_only_pre_reduction_stock_bars_rebased": pre_count,
            "post_reduction_real_traded_stock_bars":
                len(last240) - pre_count,
            "capital_reduction_halt_market_days_not_synthesized": len(halts),
            "2022_cash_reduction_only_decimal_sma240_computed_in_ram": True,
            "published_theoretical_resumption_reference_price_parity": True,
            "all_other_dividends_and_splits_adjusted": False,
            "asof_historical_stock_membership_proven": False,
            "tradable_equity_total_return_or_cash_settlement_proven": False,
            "sma_value_or_adjusted_daily_prices_written_to_disk": False,
            "fully_adjusted_sma240_release_approved": False,
        })
    return {
        "schema_version": 1,
        "scope": SMA_SCOPE,
        "source_2022_frozen20_market_session_sma240_unchanged": 18,
        "owner_authenticated_2021_market_days": len(set(market2021)),
        "owner_authenticated_2022_observed_market_days": len(set(market2022)),
        "event_only_240_sma_stock_count": len(details),
        "real_2022_capital_reduction_halt_days_left_without_price": 14,
        "stock_capital_reduction_only_research_witnesses": details,
        "no_new_2021_2022_download": True,
        "no_new_2022_source_rows_inserted": True,
        "complete_all_corporate_actions_adjusted": False,
        "all_dividend_corporate_action_observation_times_reconstructed": False,
        "full_five_year_history_proven": False,
        "point_in_time_historical_listed_roster_proven": False,
        "walkforward_total_return_alpha_or_deployment_proven": False,
        "private_raw_or_adjusted_sma_values_emitted": False,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_requested": False,
        "live_model_release_decision": "BLOCKED",
    }


def run_local(*, archive_2021, archive_2022, key_vault,
              source_report, warmup_report, reference_report, output):
    files2021 = _private_archives(archive_2021)
    files2022 = _private_archives(archive_2022)
    if set(files2021) & set(files2022):
        raise ValueError("2021 and 2022 private archive directories overlap")
    sources = [
        _private_file(p, should_exist=True)
        for p in (source_report, warmup_report, reference_report)
    ]
    out = _private_file(output, should_exist=False)
    if len(set(sources + [out])) != 4:
        raise ValueError("All private evidence reports must be distinct")
    original, warmup, reference = (
        json.loads(p.read_text(encoding="utf-8")) for p in sources
    )
    if (not isinstance(original, dict)
            or original.get("live_model_release_decision") != "BLOCKED"
            or not isinstance(warmup, dict) or warmup.get("scope") != WARMUP_SCOPE
            or not isinstance(reference, dict) or reference.get("scope") != EVENT_SCOPE):
        raise ValueError("Original private source reports not eligible")
    hex_key = resolve_archive_key(
        vault_path=Path(key_vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
    )
    market2021, verified_dates2021 = _replay_2021(files2021, hex_key=hex_key)
    # Reauthenticate a third time to extract only two bounded original
    # close series. Ensure files do not change between passes.
    before = {p: sha256(p.read_bytes()).hexdigest() for p in files2021}
    bars2021 = {sid: {} for sid in STOCKS}
    for file in files2021:
        def collect(row):
            sid, d = row["stock_id"], row["trade_date"]
            if sid in bars2021:
                if d not in EXPECTED_2021 or d in bars2021[sid]:
                    raise ValueError("Duplicate / wrong-year 2021 bar")
                bars2021[sid][d] = row["close"]
        proof = verify_archive(file, hex_key=hex_key, on_verified_row=collect)
        if proof["archive_integrity_verified"] is not True:
            raise ValueError("2021 source replay validation failed")
    after = {p: sha256(p.read_bytes()).hexdigest() for p in files2021}
    if (before != after
            or any(set(bars2021[sid]) != verified_dates2021[sid]
                   for sid in STOCKS)):
        raise ValueError("2021 authenticated close source changed between passes")

    aes_audit = audit_2022(files2022, hex_key=hex_key, spotchecks=0)
    stream, hashes = _authenticated_rows(
        files2022, hex_key=hex_key,
        expected_bundle_digest=aes_audit["authenticated_file_digest_bundle_sha256"],
    )
    bars2022 = {sid: {} for sid in STOCKS}
    market2022 = set()

    def collect_local():
        for row in stream:
            market2022.add(row["trade_date"])
            sid, d = row["stock_id"], row["trade_date"]
            if sid in bars2022:
                if d in bars2022[sid]:
                    raise ValueError("Duplicated TWSE AES stock-day")
                bars2022[sid][d] = row["close"]
            yield row

    neon_days, neon_rows = _read_neon_2022_frozen_panel()
    recomputed = reconcile(
        collect_local(), neon_rows, neon_days, local_audit=aes_audit)
    if sha256(json.dumps(hashes, separators=(",", ":")).encode()).hexdigest() != (
            aes_audit["authenticated_file_digest_bundle_sha256"]):
        raise ValueError("2022 encrypted source bundle changed during replay")
    market2022.update(neon_days)
    for row in neon_rows:
        sid, d = row["stock_id"], row["trade_date"]
        if sid in bars2022:
            prior = bars2022[sid].get(d)
            if prior is not None and prior != row["close"]:
                raise ValueError("Neon and local AES close conflict")
            bars2022[sid][d] = row["close"]
    proof = calculate_event_only_sma240(
        original, recomputed, warmup, reference,
        market2021, market2022, bars2021, bars2022)
    with out.open("x", encoding="utf-8") as f:
        json.dump(proof, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    print(json.dumps({
        "status": "CASH_REDUCTION_ONLY_2022_REAL_TRADED_240_SMA_RESEARCH_PASS",
        "two_stock_adjusted_one_event_sma_count":
            proof["event_only_240_sma_stock_count"],
        "all_dividend_split_adjustments_done": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


def main():
    cli = argparse.ArgumentParser(
        description="Owner-local 2022 cash-reduction-only SMA240 exact Decimal, blocked")
    cli.add_argument("--archive-2021", required=True)
    cli.add_argument("--archive-2022", required=True)
    cli.add_argument("--key-vault", required=True)
    cli.add_argument("--source-report", required=True)
    cli.add_argument("--warmup-report", required=True)
    cli.add_argument("--reference-report", required=True)
    cli.add_argument("--out", required=True)
    args = cli.parse_args()
    try:
        run_local(
            archive_2021=args.archive_2021,
            archive_2022=args.archive_2022,
            key_vault=args.key_vault,
            source_report=args.source_report,
            warmup_report=args.warmup_report,
            reference_report=args.reference_report,
            output=args.out,
        )
    except Exception:
        raise SystemExit(
            "Private 2022 cash-reduction-only 240-SMA research FAILED; "
            "no Neon writes, LINE notifications or private prices printed"
        ) from None


if __name__ == "__main__":
    main()
