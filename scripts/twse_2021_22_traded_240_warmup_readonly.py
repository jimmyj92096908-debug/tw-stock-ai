"""2021 owner AES + 2022 owner AES/Neon: real traded-session warmup proof.

OWNER PC ONLY. Validates existing 2021 Nov/Dec TWSE source AES and prior
2022 frozen20 AES + READ ONLY Neon report; never creates a synthetic stock
bar for a capital-reduction halt. Does not recompute adjusted SMA/returns.
No price, crypto key, connection URI or private file path enters public logs.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from scripts.twse_2021_owner_local_fast_archive import ALL_2021_DAYS
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_archive_custody_audit import MAX_ARCHIVE_BYTES
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_2022_aes_factor_readiness import audit as audit_2022
from scripts.twse_2022_aes_neon_readonly_240_panel import (
    FROZEN_STOCKS, _authenticated_rows, _read_neon_2022_frozen_panel, reconcile,
)
from scripts.twse_2022_corporate_halt_audit import (
    EXPECTED_HALT_SESSIONS, EXPECTED_SCOPE, classify,
)

STOCKS = ("2327", "2603")
EXPECTED_2021 = frozenset(ALL_2021_DAYS)
SOURCE_KEYS = (
    "local_2022_source_sessions", "neon_source_sessions",
    "overlapping_source_sessions", "unique_observed_2022_source_sessions",
    "first_combined_session", "last_combined_session",
    "frozen_stocks_with_complete_last_240_source_sessions",
    "missing_sma240_stock_day_details", "private_result_fingerprint_sha256",
    "neon_write_operations", "line_messages_sent", "live_model_release_decision",
)


def _private_file(path, *, should_exist):
    p = Path(path).expanduser()
    if p.is_symlink() or any((a / ".git").exists() for a in (p.parent, *p.parents)):
        raise ValueError("No symlinks or private files in a Git checkout")
    p = p.resolve()
    if should_exist:
        if not p.is_file() or p.stat().st_size > 256_000:
            raise ValueError("Existing bounded private JSON file required")
    elif not p.parent.is_dir() or p.exists():
        raise ValueError("Existing private output directory and no overwrite required")
    return p


def _private_archives(raw):
    original = Path(raw).expanduser()
    if original.is_symlink() or not original.is_dir():
        raise ValueError("Existing real private AES directory required")
    folder = original.resolve()
    if any((a / ".git").exists() for a in (folder, *folder.parents)):
        raise ValueError("No AES archives under Git checkout")
    archives = sorted(folder.glob("*.twseenc"))
    if (not 1 <= len(archives) <= 72
            or any(p.is_symlink() or not p.is_file()
                   or not 0 < p.stat().st_size <= MAX_ARCHIVE_BYTES
                   for p in archives)):
        raise ValueError("Bounded non-symlink private AES archives required")
    return archives


def summarize_real_traded_warmup(
    original_report, recomputed_report, observed_2022_market_days,
    verified_2021_market_days, stock_2021_dates, stock_2022_dates,
):
    """No prices exported; prove last-240 observed stock trades only.

    This intentionally does not certify a complete TWSE 2022 market calendar,
    historical PIT membership, price adjustment, or a tradable 240 factor.
    """
    expected_halt = classify(original_report)
    if (expected_halt["known_cash_reduction_stock_halt_days"] != 14
            or not expected_halt["all_reported_gap_dates_explained_by_known_halts"]
            or original_report["frozen_stocks_with_complete_last_240_source_sessions"] != 18
            or original_report["unique_observed_2022_source_sessions"] != 246
            or original_report.get("scope") != EXPECTED_SCOPE
            or original_report.get("neon_transaction_mode") != "READ_ONLY"):
        raise ValueError("Original 2022 frozen20 research proof must remain blocked 18/20")
    if (not isinstance(recomputed_report, dict)
            or any(original_report.get(k) != recomputed_report.get(k)
                   for k in SOURCE_KEYS)
            or recomputed_report.get("neon_write_operations") != 0
            or recomputed_report.get("live_model_release_decision") != "BLOCKED"):
        raise ValueError("Live READ ONLY 2022 evidence changed since private report")

    days2021 = set(verified_2021_market_days)
    days2022 = set(observed_2022_market_days)
    if (days2021 != EXPECTED_2021
            or len(days2022) != 246
            or any(type(d) is not date or d.year != 2022 for d in days2022)
            or min(days2022).isoformat() != original_report["first_combined_session"]
            or max(days2022).isoformat() != original_report["last_combined_session"]
            or not isinstance(stock_2021_dates, dict)
            or not isinstance(stock_2022_dates, dict)
            or set(stock_2021_dates) != set(STOCKS)
            or set(stock_2022_dates) != set(STOCKS)):
        raise ValueError("2021/2022 authenticated source date calendar mismatch")

    result = []
    for sid in STOCKS:
        old_days = set(stock_2021_dates[sid])
        new_days = set(stock_2022_dates[sid])
        if (not old_days <= days2021 or not new_days <= days2022
                or any(type(d) is not date for d in old_days | new_days)):
            raise ValueError("Invalid or unverified stock trading date")
        absent2022 = days2022 - new_days
        expected = {date.fromisoformat(v) for v in EXPECTED_HALT_SESSIONS[sid]}
        if absent2022 != expected:
            raise ValueError("Unexpected 2022 stock-day gap beyond known halts")
        if len(old_days) != 28 or max(new_days) != max(days2022):
            raise ValueError("No complete pre-2022 warmup or latest real trading day")
        merged = sorted(old_days | new_days)
        last240 = merged[-240:]
        if (len(last240) != 240 or len(set(last240)) != 240
                or last240[-1] != max(days2022)
                or any(d in absent2022 for d in last240)
                or last240[0].year != 2021):
            raise ValueError("240 distinct authenticated per-stock trading dates not proved")
        result.append({
            "stock_id": sid,
            "authenticated_2021_real_trading_days": len(old_days),
            "authenticated_2022_real_trading_days": len(new_days),
            "verified_2022_no_trade_cash_reduction_market_days": len(absent2022),
            "actual_source_bars_from_2021_and_2022": len(merged),
            "latest_240_real_stock_trading_dates_selectable": True,
            "last240_earliest_real_trading_date": last240[0].isoformat(),
            "last240_latest_real_trading_date": last240[-1].isoformat(),
            "underlying_price_adjusted_for_cash_reduction": False,
            "adjusted_sma240_or_factor_recomputed": False,
        })
    return {
        "scope": "OWNER_ONLY_2021_22_TWSE_TWO_STOCK_REAL_TRADED_240_WARMUP",
        "2021_aes_authenticated_market_source_days": len(days2021),
        "2022_aes_plus_neon_observed_market_source_days": len(days2022),
        "stock_traded_day_research_warmup_proofs": result,
        "verified_halt_days_not_replaced_by_fake_bars": 14,
        "source_2022_market_session_sma240_eligible_unchanged": 18,
        "raw_240_stock_trading_day_selectability_is_not_adjusted_sma240": True,
        "full_official_2022_trading_calendar_independently_verified": False,
        "historical_asof_membership_and_observation_time_verified": False,
        "cash_reduction_or_total_return_price_adjusted": False,
        "model_walkforward_validation_complete": False,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
        "live_model_release_decision": "BLOCKED",
    }


def _replay_2021(files, *, hex_key):
    before = {p: sha256(p.read_bytes()).hexdigest() for p in files}
    proof = authenticated_archive_days(
        files, hex_key=hex_key,
        start=min(ALL_2021_DAYS), end=date(2022, 1, 1),
    )
    if (proof.get("full_file_integrity_verified") is not True
            or proof["days"] != EXPECTED_2021):
        raise ValueError("Owner 2021 AES 28-day market source evidence insufficient")
    stockdays = {s: set() for s in STOCKS}
    for file in files:
        def accept(row):
            sid = row["stock_id"]
            if sid in stockdays:
                if row["trade_date"] not in EXPECTED_2021:
                    raise ValueError("Unexpected 2021 stock-date")
                if row["trade_date"] in stockdays[sid]:
                    raise ValueError("Duplicated 2021 frozen stock-date")
                stockdays[sid].add(row["trade_date"])
        verified = verify_archive(file, hex_key=hex_key, on_verified_row=accept)
        if verified.get("archive_integrity_verified") is not True:
            raise ValueError("2021 private AES replay authentication failed")
    if {p: sha256(p.read_bytes()).hexdigest() for p in files} != before:
        raise ValueError("2021 AES archive content changed between verification passes")
    return proof["days"], stockdays


def run_local(*, dir_2021, dir_2022, vault_path, source_report, output):
    paths2021 = _private_archives(dir_2021)
    paths2022 = _private_archives(dir_2022)
    if set(paths2021) & set(paths2022):
        raise ValueError("2021 / 2022 source folders cannot duplicate an AES file")
    source = _private_file(source_report, should_exist=True)
    out = _private_file(output, should_exist=False)
    original = json.loads(source.read_text(encoding="utf-8"))
    # Reject malformed scope/release before asking for credentials or decrypting.
    classification = classify(original)
    if (classification["known_cash_reduction_stock_halt_days"] != 14
            or classification["unknown_stock_day_count"] != 0):
        raise ValueError("Not an exact known 14-day capital reduction gap report")

    hex_key = resolve_archive_key(
        vault_path=Path(vault_path),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
    )
    days2021, stocks2021 = _replay_2021(paths2021, hex_key=hex_key)

    aes_proof = audit_2022(paths2022, hex_key=hex_key, spotchecks=0)
    local_iter, source_hashes = _authenticated_rows(
        paths2022, hex_key=hex_key,
        expected_bundle_digest=aes_proof["authenticated_file_digest_bundle_sha256"],
    )
    stocks2022 = {s: set() for s in STOCKS}
    observed_market_days = set()

    def tracked_2022():
        for row in local_iter:
            observed_market_days.add(row["trade_date"])
            if row["stock_id"] in stocks2022:
                stocks2022[row["stock_id"]].add(row["trade_date"])
            yield row

    neon_days, neon_rows = _read_neon_2022_frozen_panel()
    recomputed = reconcile(
        tracked_2022(), neon_rows, neon_days,
        local_audit=aes_proof,
    )
    if (sha256(json.dumps(source_hashes, separators=(",", ":")).encode())
            .hexdigest() != aes_proof["authenticated_file_digest_bundle_sha256"]):
        raise ValueError("2022 AES archive changed during authenticated replay")
    observed_market_days.update(neon_days)
    for row in neon_rows:
        if row["stock_id"] in stocks2022:
            stocks2022[row["stock_id"]].add(row["trade_date"])

    result = summarize_real_traded_warmup(
        original, recomputed, observed_market_days, days2021,
        stocks2021, stocks2022,
    )
    with out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": "REAL_TRADED_240_2021_22_WARMUP_EVIDENCE_PASS",
        "studied_stock_count": len(result["stock_traded_day_research_warmup_proofs"]),
        "raw_trade_day_evidence_240_for_both_stocks": all(
            entry["latest_240_real_stock_trading_dates_selectable"]
            for entry in result["stock_traded_day_research_warmup_proofs"]),
        "2022_current_market_session_sma240_remains": 18,
        "capital_action_adjusted_sma240": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(
        description="Owner PC verified AES 2021+2022 real-stock-trading 240 warmup")
    p.add_argument("--archive-2021", required=True)
    p.add_argument("--archive-2022", required=True)
    p.add_argument("--key-vault", required=True)
    p.add_argument("--source-report", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        run_local(
            dir_2021=args.archive_2021,
            dir_2022=args.archive_2022,
            vault_path=args.key_vault,
            source_report=args.source_report,
            output=args.out,
        )
    except Exception:
        raise SystemExit(
            "Private 2021-22 traded-240 warmup verification FAILED; "
            "no Neon changes or LINE messages; no private data printed"
        ) from None


if __name__ == "__main__":
    main()
