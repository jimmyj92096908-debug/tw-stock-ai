"""Owner-private 2021 AES-only source-row quality audit; no production backfill.

Requires an accepted real 552/552 OHLCV parity receipt, *recomputes it* using
authenticated owner AES archives and a fresh Neon REPEATABLE READ READ ONLY
snapshot, then examines AES-only 25,568 candidate source keys. A candidate
source key is not historical PIT, import authority or free database capacity.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path

from scripts.twse_2021_552_aes_neon_ohlcv_overlap_readonly import (
    SCOPE as PARITY_SCOPE, MAX_SOURCE_ROWS,
    capture_readonly, evaluate as evaluate_overlap,
)
from scripts.twse_2021_28day_aes_neon_stockdate_union_readonly import BEGIN, END
from scripts.twse_2021_28day_aes_current_cohort_density_readonly import EXPECTED_DAYS
from scripts.twse_2021_22_traded_240_warmup_readonly import _private_archives, _private_file
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key

SCOPE = "OWNER_2021_TWSE_AES_EXCLUSIVE_OHLCV_SOURCE_QUALITY_READONLY"
OHLCV = ("open", "high", "low", "close", "volume")
OPTIONAL = ("turnover", "price_change", "transactions")
MAX_REPORT_BYTES = 12_000


def _check_previous(prior, recomputed):
    if (not isinstance(prior, dict)
        or prior.get("schema_version") != 1 or prior.get("scope") != PARITY_SCOPE
        or prior.get("exact_source_key_overlap") != 552
        or prior.get("authenticated_2021_aes_source_stockdate_keys") != 26120
        or prior.get("aes_exclusive_source_keys_never_written_to_neon") != 25568
        or prior.get("critical_ohlcv_field_matches") != 552
        or prior.get("critical_ohlcv_mismatch_or_unverifiable_rows") != 0
        or prior.get("complete_economic_field_matches") != 545
        or prior.get("per_field_different_or_unverifiable_counts") !=
           {"unverifiable_price_change": 7}
        or prior.get("all_552_critical_ohlcv_parity_verified") is not True
        or prior.get("safe_to_write_production_history") is not False
        or prior.get("model_release") != "BLOCKED"
        or prior.get("neon_writes") != 0
        or prior.get("line_messages_sent") != 0):
        raise ValueError("The owner-real 2021 552-key AES-Neon parity receipt has not passed")
    for k in ("exact_source_key_overlap",
              "authenticated_2021_aes_source_stockdate_keys",
              "aes_exclusive_source_keys_never_written_to_neon",
              "critical_ohlcv_field_matches",
              "critical_ohlcv_mismatch_or_unverifiable_rows",
              "complete_economic_field_matches",
              "per_field_different_or_unverifiable_counts",
              "neon_source_tags",
              "private_552_overlap_exceptions_without_prices"):
        if prior.get(k) != recomputed.get(k):
            raise ValueError("Owner real 552-key parity differs from a new read-only snapshot")


def evaluate(*, union_receipt, owner_parity_receipt, roster, aes_rows, neon_rows):
    current = evaluate_overlap(
        receipt=union_receipt, roster=roster, aes_rows=aes_rows, neon_rows=neon_rows
    )
    _check_previous(owner_parity_receipt, current)
    neon_keys = {(r["trade_date"], r["stock_id"]) for r in neon_rows}
    candidate_keys = set(aes_rows) - neon_keys
    if len(neon_keys) != 552 or len(candidate_keys) != 25568:
        raise ValueError("AES-only source key conservation changed")

    per_day, optional_missing = Counter(), Counter()
    observed_stocks = set()
    for key in candidate_keys:
        day, sid = key
        row = aes_rows[key]
        o, h, l, c = (row.get(f) for f in OHLCV[:4])
        volume = row.get("volume")
        if (day not in EXPECTED_DAYS or sid == "1589" or
            any(type(v) is not Decimal or not v.is_finite() or v <= 0
                for v in (o, h, l, c)) or
            not l <= min(o, c) <= max(o, c) <= h or
            type(volume) is not int or volume < 0):
            raise ValueError("An exclusive AES source bar has invalid or missing critical OHLCV")
        for f in OPTIONAL:
            v = row.get(f)
            if v is None:
                optional_missing[f] += 1
            elif f == "transactions":
                if type(v) is not int or v < 0:
                    raise ValueError("Invalid transactions in authenticated exclusive source")
            elif type(v) is not Decimal or not v.is_finite():
                raise ValueError("Invalid economic decimal in authenticated exclusive source")
        per_day[day.isoformat()] += 1
        observed_stocks.add(sid)
    if set(per_day) != {d.isoformat() for d in EXPECTED_DAYS}:
        raise ValueError("The AES-only source day list changed")

    # No per-issuer price or private plaintext leaves this local report.
    month = Counter({m: 0 for m in ("2021-11", "2021-12")})
    for day, count in per_day.items():
        month[day[:7]] += count
    if sum(month.values()) != 25568:
        raise ValueError("Private AES-only source key monthly conservation failed")
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "authentic_original_2021_source_days": 28,
        "owner_current_official_twse_survivor_count_excluding_1589": 1092,
        "verified_original_aes_source_stockdate_keys": 26120,
        "verified_original_neon_overlap_keys": 552,
        "original_552_overlap_critical_ohlcv_parity_revalidated": True,
        "original_552_overlap_extended_economic_match_rows": 545,
        "original_552_neon_missing_price_change_rows": 7,
        "aes_exclusive_stockdate_source_keys": 25568,
        "aes_exclusive_source_keys_with_sane_core_ohlcv": 25568,
        "aes_exclusive_distinct_current_survivor_issuers": len(observed_stocks),
        "aes_exclusive_missing_optional_economic_field_counts": dict(sorted(optional_missing.items())),
        "aes_exclusive_source_keys_per_month": dict(sorted(month.items())),
        "aes_exclusive_source_keys_per_day_aggregate": dict(sorted(per_day.items())),
        "source_key_identity_is_not_historical_pit_membership": True,
        "original_source_key_is_not_a_approved_neon_insert": True,
        "historic_listing_and_trading_pit_eligibility_proven": False,
        "complete_neon_backups_and_restore_test_passed_here": False,
        "corporate_action_adjusted_return_verified": False,
        "estimated_paid_or_free_storage_guaranteed": False,
        "production_backfill_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_used": False,
    }


def run_owner(*, archive_dir, key_vault, union_path, parity_path, out, db_url):
    originals = _private_archives(archive_dir)
    union_file = _private_file(union_path, should_exist=True)
    parity_file = _private_file(parity_path, should_exist=True)
    destination = _private_file(out, should_exist=False)
    if len({union_file, parity_file, destination}) != 3 or any(
        p in originals for p in (union_file, parity_file, destination)
    ):
        raise ValueError("Private source, receipt and output files must be distinct")
    union = json.loads(union_file.read_text(encoding="utf-8"))
    prior = json.loads(parity_file.read_text(encoding="utf-8"))
    # Reject a stale/bad 552-key receipt before unlocking owner AES secrets.
    if prior.get("scope") != PARITY_SCOPE or prior.get("critical_ohlcv_field_matches") != 552:
        raise ValueError("Missing valid previous real-overlap parity receipt")
    key = resolve_archive_key(
        vault_path=Path(key_vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
    )
    original_sha = {str(p): sha256(p.read_bytes()).hexdigest() for p in originals}
    census = authenticated_archive_days(originals, hex_key=key, start=BEGIN, end=END)
    if not census.get("full_file_integrity_verified") or census["days"] != frozenset(EXPECTED_DAYS):
        raise ValueError("Original 2021 AES market source dates changed")
    roster, neon = capture_readonly(db_url)
    allowed = set(roster)
    rows = {}
    visited = 0
    for file in originals:
        def accept(row):
            nonlocal visited
            visited += 1
            if visited > MAX_SOURCE_ROWS or row["trade_date"] not in EXPECTED_DAYS:
                raise ValueError("2021 AES source rows out of permitted bounds")
            if row["stock_id"] in allowed:
                k = row["trade_date"], row["stock_id"]
                if k in rows:
                    raise ValueError("Duplicate 2021 owner AES source key")
                rows[k] = row
        ver = verify_archive(file, hex_key=key, on_verified_row=accept)
        if ver.get("archive_integrity_verified") is not True:
            raise ValueError("Original AES footer authentication failed")
    if {str(p): sha256(p.read_bytes()).hexdigest() for p in originals} != original_sha:
        raise ValueError("Encrypted original source changed during replay")
    r = evaluate(
        union_receipt=union, owner_parity_receipt=prior,
        roster=roster, aes_rows=rows, neon_rows=neon,
    )
    payload = json.dumps(r, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(payload.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("Private aggregate source quality receipt exceeds limit")
    with destination.open("x", encoding="utf-8") as output:
        output.write(payload)
    print(json.dumps({
        "status": "OWNER_2021_AES_ONLY_25568_SOURCE_KEY_OHLCV_QUALITY_PASS",
        "aes_only_source_keys": r["aes_exclusive_stockdate_source_keys"],
        "aes_only_sane_ohlcv_source_keys": r["aes_exclusive_source_keys_with_sane_core_ohlcv"],
        "missing_optional_economic_field_counts": r["aes_exclusive_missing_optional_economic_field_counts"],
        "actual_neon_insert_approved": False, "model_release": "BLOCKED",
        "neon_writes": 0, "line_messages_sent": 0,
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-2021", required=True)
    p.add_argument("--key-vault", required=True)
    p.add_argument("--prior-union", required=True)
    p.add_argument("--prior-552-parity", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit("Real owner AES and Neon may not be accessed from CI")
    try:
        run_owner(
            archive_dir=args.archive_2021, key_vault=args.key_vault,
            union_path=args.prior_union, parity_path=args.prior_552_parity,
            out=args.out, db_url=os.environ.get("DATABASE_URL", ""),
        )
    except Exception:
        raise SystemExit(
            "Owner 2021 AES-only quality audit FAILED safely; no source price,"
            " AES key, database credential, Neon write, or LINE message leaked"
        ) from None


if __name__ == "__main__":
    main()
