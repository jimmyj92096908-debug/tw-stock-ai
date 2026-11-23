"""Offline, fail-closed admission evidence for free-tier historical backfill.

No database connections, writes, LINE calls, trades, source price synthesis or
permission to run a production import. Numbers must come from separate verified
read-only Neon observations and immutable owner-private research receipts.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

STOP_BYTES = 800_000_000
RESERVE_BYTES = 50_000_000
REWRITE_MULTIPLIER = 3
SCOPE = "NEON_FREE_OWNER_2021_HISTORY_BACKFILL_CAPACITY_PREFLIGHT_OFFLINE"
LISTING_BUCKETS = (
    "current_listing_on_or_before_first_2021_source_day",
    "current_listing_between_first_and_last_2021_source_days",
    "current_listing_after_last_2021_source_day_in_2021",
    "current_listing_in_2022",
    "current_listing_in_2023",
    "current_listing_in_2024",
    "current_listing_in_2025",
    "current_listing_in_2026",
    "current_listing_date_missing_or_invalid",
)


def _integer(value, name, *, positive=True):
    if type(value) is not int or (value <= 0 if positive else value < 0):
        raise ValueError("Invalid nonnegative numeric evidence: " + name)
    return value


def _validate_receipts(union, listing):
    if not isinstance(union, dict) or not isinstance(listing, dict):
        raise ValueError("Both immutable owner-private receipts required")
    keys = (
        "prior_2021_aes_source_stock_date_pairs",
        "prior_2021_neon_source_stock_date_pairs",
        "aes_neon_overlapping_source_stock_date_pairs",
        "aes_exclusive_source_stock_date_pairs",
        "neon_exclusive_source_stock_date_pairs",
        "actual_deduplicated_aes_neon_stock_date_pairs",
        "current_stocks_with_no_source_day_in_2021",
    )
    c = {k: _integer(union.get(k), k, positive=False) for k in keys}
    if (union.get("scope") != "OWNER_2021_TWSE_AES_NEON_CURRENT_LISTED_28DAY_STOCK_DATE_UNION_READONLY" or
        listing.get("scope") != "OWNER_2021_TWSE_153_ZERO_SOURCE_CURRENT_OFFICIAL_LISTING_DATE_TRIAGE" or
        c["prior_2021_aes_source_stock_date_pairs"] != 26120 or
        c["prior_2021_neon_source_stock_date_pairs"] != 552 or
        c["aes_neon_overlapping_source_stock_date_pairs"] != 552 or
        c["aes_exclusive_source_stock_date_pairs"] != 25568 or
        c["neon_exclusive_source_stock_date_pairs"] != 0 or
        c["actual_deduplicated_aes_neon_stock_date_pairs"] != 26120 or
        c["current_stocks_with_no_source_day_in_2021"] != 153 or
        union.get("model_release") != "BLOCKED" or
        union.get("production_neon_writes") != 0 or
        union.get("line_messages_sent") != 0 or
        union.get("authenticated_owner_2021_source_dates") != 28):
        raise ValueError("Owner 2021 AES-Neon union receipt does not match validated source")
    if (listing.get("no_2021_aes_or_neon_source_issuer_count") != 153 or
        listing.get("prior_revalidated_2021_aes_neon_deduplicated_stock_date_pairs") != 26120 or
        listing.get("zero_source_2021_prioritize_manual_historical_listing_research") != 0 or
        listing.get("model_release") != "BLOCKED" or
        listing.get("production_neon_writes") != 0 or
        listing.get("line_messages_sent") != 0):
        raise ValueError("2021 official current listing receipt not accepted")
    buckets = listing.get("current_listing_year_and_period_bucket_counts")
    if not isinstance(buckets, dict) or any(
        _integer(buckets.get(k), k, positive=False) < 0 for k in LISTING_BUCKETS
    ) or sum(buckets[k] for k in LISTING_BUCKETS) != 153 or any(
        buckets[k] != 0 for k in LISTING_BUCKETS[:3]
    ) or [buckets[k] for k in LISTING_BUCKETS[3:8]] != [24, 27, 37, 35, 30] or buckets[LISTING_BUCKETS[8]] != 0:
        raise ValueError("2021 official listing buckets conflict with actual owner acceptance")
    return c


def evaluate(snapshot, owner_union, owner_listing):
    """Return only advisory, descriptive capacities; never authorize writes."""
    if not isinstance(snapshot, dict):
        raise ValueError("Authenticated read-only capacity snapshot required")
    size = _integer(snapshot.get("pg_database_bytes"), "pg_database_bytes")
    logical = _integer(snapshot.get("neon_branch_logical_bytes"), "neon_branch_logical_bytes")
    branch_limit = _integer(snapshot.get("neon_branch_limit_bytes"), "neon_branch_limit_bytes")
    relation = _integer(snapshot.get("daily_prices_relation_bytes"), "daily_prices_relation_bytes")
    rows = _integer(snapshot.get("daily_prices_rows"), "daily_prices_rows")
    if not (size >= relation and branch_limit >= logical and size >= rows and
            rows >= 1000 and logical >= relation):
        raise ValueError("Neon capacity measurements are inconsistent")
    c = _validate_receipts(owner_union, owner_listing)
    # A historical-source date key is NOT an approved price row. This is only
    # indicative and excludes WAL, MVCC churn, other years and Neon accounting.
    aes_unique_keys = c["aes_exclusive_source_stock_date_pairs"]
    avg_physical_price_bytes = relation / rows
    indicative_2021_relation_footprint_bytes = math.ceil(aes_unique_keys * avg_physical_price_bytes)
    indicative_2021_rewrite_allowance_bytes = math.ceil(
        aes_unique_keys * avg_physical_price_bytes * REWRITE_MULTIPLIER)
    effective_guard_bytes = STOP_BYTES - RESERVE_BYTES
    guard_headroom = effective_guard_bytes - size
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "pg_database_bytes": size,
        "neon_branch_logical_bytes": logical,
        "neon_branch_limit_bytes": branch_limit,
        "remaining_logical_branch_bytes_before_limit": branch_limit - logical,
        "internal_stop_bytes": STOP_BYTES,
        "write_maintenance_reserve_bytes": RESERVE_BYTES,
        "existing_guard_max_database_before_growth_bytes": effective_guard_bytes,
        "existing_guard_headroom_before_any_growth_bytes": guard_headroom,
        "existing_guard_blocks_even_zero_estimated_growth": guard_headroom <= 0,
        "daily_prices_relation_bytes": relation,
        "daily_prices_rows": rows,
        "estimated_average_physical_bytes_per_stored_price_row": round(avg_physical_price_bytes, 2),
        "authenticated_2021_union_source_stockdate_keys": 26120,
        "source_keys_already_overlap_with_neon_2021": 552,
        "2021_aes_exclusive_source_stockdate_keys_not_in_neon_receipt": aes_unique_keys,
        "2021_zero_source_153_current_listing_2022plus": True,
        "2021_missing_source_issuer_not_equivalent_to_missing_2021_price": True,
        "indicative_2021_candidate_relation_bytes_not_a_backfill_estimate": indicative_2021_relation_footprint_bytes,
        "indicative_2021_candidate_rewrite_allowance_bytes_not_a_quota_guarantee": indicative_2021_rewrite_allowance_bytes,
        "owner_private_aes_rows_imported_by_this_preflight": 0,
        "full_2022_aes_neon_per_key_reconciliation_completed_here": False,
        "all_five_year_prices_or_corporate_actions_validated": False,
        "source_keys_not_approved_ohlcv_rows": True,
        "historical_listing_point_in_time_validated": False,
        "future_independent_holdout_passed": False,
        "safe_to_run_production_backfill": False,
        "requires_independent_restore_test_and_fresh_capacity_check": True,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_used": False,
    }


def _private_out(path):
    out = Path(path).expanduser()
    if out.is_symlink() or not out.parent.is_dir():
        raise ValueError("Report parent must exist, output cannot be a symlink")
    if any((p / ".git").exists() for p in (out.parent.resolve(), *out.parent.resolve().parents)):
        raise ValueError("Do not put private reports inside a Git working tree")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capacity-snapshot", required=True)
    parser.add_argument("--owner-2021-union", required=True)
    parser.add_argument("--owner-153-listing", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        def read(path):
            p = Path(path).expanduser()
            if not p.is_file() or p.is_symlink() or p.stat().st_size > 100_000:
                raise ValueError("Private JSON evidence missing or invalid")
            return json.loads(p.read_text(encoding="utf-8"))
        report = evaluate(
            read(args.capacity_snapshot),
            read(args.owner_2021_union),
            read(args.owner_153_listing),
        )
        out = _private_out(args.out)
        payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if len(payload.encode("utf-8")) > 16_000:
            raise ValueError("Result exceeds anonymous output budget")
        with out.open("x", encoding="utf-8") as fp:
            fp.write(payload)
        print(json.dumps({
            "status": "NEON_FREE_2021_HISTORY_ADMISSION_EVIDENCE_PASS",
            "existing_guard_blocks_even_zero_estimated_growth": report["existing_guard_blocks_even_zero_estimated_growth"],
            "existing_guard_headroom_bytes": report["existing_guard_headroom_before_any_growth_bytes"],
            "private_2021_aes_exclusive_keys": report["2021_aes_exclusive_source_stockdate_keys_not_in_neon_receipt"],
            "safe_to_run_production_backfill": False,
            "model_release": "BLOCKED", "neon_writes": 0, "line_messages_sent": 0,
        }, ensure_ascii=False))
    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError, OverflowError):
        raise SystemExit("Neon Free history capacity preflight FAILED safely; no database writes or credentials disclosed") from None


if __name__ == "__main__":
    main()
