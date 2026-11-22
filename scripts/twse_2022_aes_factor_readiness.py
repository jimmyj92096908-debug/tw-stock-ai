"""Owner-local historical TWSE AES archive 240-session factor readiness, NO database.

Reads and authenticates each encrypted 2022 official source archive. Computes an
aggregate coverage ledger for all allowed current-survivor stocks; when enough
real stock sessions exist, computes in-memory exact Decimal SMA240 across every
stock with the full last-240-day calendar, and causal raw technical/SMC 12-vector
spotchecks. No source or factor rows leave process memory or are uploaded.
Unadjusted history is NEVER total return, original publication-vintage proof,
survivorship-free historical membership or approved model/trading evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_local_archive_custody_audit import (
    MAX_ARCHIVE_BYTES, _range_header,
)
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_stateless_240_monthly_factor import exact_sma240
from src.raw_factor_feature_bridge import FEATURE_NAMES, build_research_features

YEAR = 2022
MIN_FACTOR_SESSIONS = 240
PREFIX_SESSIONS = 241
MAX_FILES = 72
MAX_ROWS = 600_000
MAX_STOCKS = 1_500
MAX_DAYS = 260
MAX_SPOTCHECKS = 5
SOURCE_TAG = "TWSE_MI_INDEX_ALLBUT0999"


def _bar_ok(row):
    if (row.get("market") != "twse" or row.get("source") != SOURCE_TAG
            or not isinstance(row.get("stock_id"), str)
            or not re.fullmatch(r"[0-9]{4}", row["stock_id"])
            or row["stock_id"] == "1589"
            or type(row.get("trade_date")) is not date
            or row["trade_date"].year != YEAR):
        raise ValueError("Invalid or excluded archived TWSE 2022 issuer/day/source")
    fields = ("open", "high", "low", "close")
    p = [row.get(x) for x in fields]
    if (any(type(v) is not Decimal or not v.is_finite() or v <= 0 for v in p)
            or not p[2] <= min(p[0], p[3]) <= max(p[0], p[3]) <= p[1]
            or type(row.get("volume")) is not int or row["volume"] < 0):
        raise ValueError("Corrupt archived OHLCV or missing official stock session")


def _ordered_paths(paths):
    if (not isinstance(paths, (list, tuple)) or
            not 1 <= len(paths) <= MAX_FILES):
        raise ValueError("Must provide 1..72 local archive files")
    verified = []
    unique = set()
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_symlink() or not path.is_file() or path.suffix != ".twseenc":
            raise ValueError("Only owner-local real encrypted archive files allowed")
        p = path.resolve()
        if (any((parent / ".git").exists() for parent in p.parents)
                or p.stat().st_size > MAX_ARCHIVE_BYTES or p in unique):
            raise ValueError("Public checkout/oversized/duplicate archive refused")
        unique.add(p)
        start, end = _range_header(p)  # Header will be authenticated by verify_archive.
        if (start.year != YEAR or end.year != YEAR or start > end):
            raise ValueError("Expected frozen year-2022 private source archives")
        verified.append((start, end, p))
    verified.sort(key=lambda v: (v[0], v[1]))
    for (start, end, _), (next_start, _, _) in zip(verified, verified[1:]):
        if next_start <= end:
            raise ValueError("Overlapping source archive date ranges")
    return verified


def audit(paths, *, hex_key, spotchecks=MAX_SPOTCHECKS):
    """Verify all AES footers before producing the aggregate research report."""
    if (type(spotchecks) is not int or not 0 <= spotchecks <= MAX_SPOTCHECKS):
        raise ValueError("Bounded 0..5 technical/SMC spotchecks required")
    ordered = _ordered_paths(paths)
    day_counts = Counter()
    stock_counts = Counter()
    seen = set()
    total = 0
    hashes = []
    for _, _, path in ordered:
        count = 0
        def receive(row):
            nonlocal total, count
            _bar_ok(row)
            day = row["trade_date"]
            key = (day, row["stock_id"])
            if key in seen:
                raise ValueError("Duplicate historical stock-date in archive collection")
            seen.add(key)
            total += 1
            count += 1
            if total > MAX_ROWS or len(day_counts) >= MAX_DAYS and day not in day_counts:
                raise ValueError("Private archive cohort exceeds bounded research limits")
            day_counts[day] += 1
            stock_counts[row["stock_id"]] += 1
            if len(stock_counts) > MAX_STOCKS:
                raise ValueError("Unexpected unbounded historical issuer population")
        proof = verify_archive(path, hex_key=hex_key, on_verified_row=receive)
        if proof["sample_rows"] != count or not proof["archive_integrity_verified"]:
            raise ValueError("Incomplete authenticated AES archive source footer")
        hashes.append(proof["canonical_rows_sha256"])
    days = sorted(day_counts)
    if not days or any(a.weekday() >= 5 for a in days):
        raise ValueError("No authentic weekday trading-source calendar")
    available = len(days)
    eligible = []
    sma_count = 0
    spot_count = 0
    prefix_count = 0
    digest = sha256()
    # On a short 2022 pilot (currently fewer than 240 sessions), NEVER create
    # fake technical indicators, invented missing-day prices or padding.
    if available >= MIN_FACTOR_SESSIONS:
        last240 = set(days[-MIN_FACTOR_SESSIONS:])
        eligible = sorted(sid for sid, n in stock_counts.items()
                          if n >= MIN_FACTOR_SESSIONS
                          and all((day, sid) in seen for day in last240))
        if eligible:
            target = set(eligible)
            chosen = eligible[:spotchecks]
            chosen_set = set(chosen)
            last241 = set(days[-PREFIX_SESSIONS:]) if available >= PREFIX_SESSIONS else last240
            sums = defaultdict(lambda: Decimal(0))
            per_stock_bars = defaultdict(list)
            last240_counts = Counter()
            for _, _, path in ordered:
                def consume(row):
                    sid = row["stock_id"]
                    day = row["trade_date"]
                    if sid in target and day in last240:
                        sums[sid] += row["close"]
                        last240_counts[sid] += 1
                    if sid in chosen_set and day in last241:
                        per_stock_bars[sid].append(row)
                # Reauthenticates all files, but only keeps at most 241
                # historical bars for each of 5 sampled stock IDs in RAM.
                proof = verify_archive(path, hex_key=hex_key, on_verified_row=consume)
                if not proof["archive_integrity_verified"]:
                    raise ValueError("Changed or unauthenticated source archive")
            for sid in eligible:
                if last240_counts[sid] != MIN_FACTOR_SESSIONS:
                    raise ValueError("Full 240-session archived calendar incomplete")
                digest.update(f"{sid}|{sums[sid] / Decimal(240)}\n".encode())
                sma_count += 1
            for sid in chosen:
                original = per_stock_bars[sid]
                if not original or original[-1]["trade_date"] != days[-1]:
                    raise ValueError("Archived latest signal not present")
                last = days[-1]
                latest = build_research_features(
                    original, market="twse", stock_id=sid,
                    cutoff=last, signal_dates=[last])
                if (latest["included_signals"] != 1 or
                        len(latest["signals"][0]["feature_vector"]) != len(FEATURE_NAMES)
                        or latest["live_trading_approved"] is not False):
                    raise ValueError("Raw 12-vector incomplete or release gate breached")
                if exact_sma240(original, asof=last) != sums[sid] / Decimal(240):
                    raise ValueError("Offline exact 240-SMA source parity failed")
                digest.update(json.dumps(
                    latest["signals"][0]["feature_vector"],
                    separators=(",", ":"), allow_nan=False).encode())
                spot_count += 1
                if available >= PREFIX_SESSIONS and len(original) >= PREFIX_SESSIONS and (
                        original[-2]["trade_date"] == days[-2]):
                    prior = original[-2]["trade_date"]
                    future = build_research_features(
                        original, market="twse", stock_id=sid,
                        cutoff=last, signal_dates=[prior])
                    causal = build_research_features(
                        original[:-1], market="twse", stock_id=sid,
                        cutoff=prior, signal_dates=[prior])
                    if (future["included_signals"] != 1
                            or causal["included_signals"] != 1
                            or future["signals"][0]["feature_vector"] !=
                            causal["signals"][0]["feature_vector"]):
                        raise ValueError("Future-dependent archived raw feature leakage")
                    prefix_count += 1
    return {
        "schema_version": 1,
        "scope": "OWNER_LOCAL_2022_AES_TWSE_RAW_240_FACTOR_READINESS_RESEARCH_ONLY",
        "authenticated_archive_files": len(ordered),
        "authenticated_source_rows": total,
        "authentic_distinct_2022_source_sessions": available,
        "first_source_session": days[0].isoformat(),
        "last_source_session": days[-1].isoformat(),
        "distinct_surviving_stock_ids_seen": len(stock_counts),
        "max_archived_sessions_for_one_stock": max(stock_counts.values()),
        "additional_real_market_sessions_needed_before_240_session_warmup": max(0, MIN_FACTOR_SESSIONS - available),
        "stocks_with_complete_last_240_source_sessions": len(eligible),
        "exact_decimal_240_sma_computed_in_memory": sma_count,
        "causal_12_technical_smc_vectors_spotchecked": spot_count,
        "previous_signal_12_vector_prefix_parity_checked": prefix_count,
        "authenticated_file_digest_bundle_sha256":
            sha256(json.dumps(hashes, separators=(",", ":")).encode()).hexdigest(),
        "aggregate_factor_fingerprint_sha256": digest.hexdigest() if sma_count else None,
        "source_captured_at_2022_trading_time_verified": False,
        "historical_survivorship_bias_resolved": False,
        "dividend_and_split_adjusted_features_or_labels": False,
        "complete_five_year_trading_days_proven": False,
        "factor_rows_persisted": 0,
        "neon_connections": 0,
        "neon_rows_written": 0,
        "line_messages_sent": 0,
        "production_model_weights_modified": False,
        "live_model_release_decision": "BLOCKED",
        "paid_services_used": False,
    }


def main():
    cli = argparse.ArgumentParser(description="Offline audited 2022 AES history 240-session readiness")
    cli.add_argument("--archive-dir", type=Path, required=True)
    cli.add_argument("--key-vault", type=Path, required=True)
    cli.add_argument("--out", type=Path, required=True)
    args = cli.parse_args()
    archive_dir = args.archive_dir.expanduser().resolve()
    out = args.out.expanduser().resolve()
    if (not archive_dir.is_dir() or any((p / ".git").exists() for p in
                                        (archive_dir, *archive_dir.parents))
            or any((p / ".git").exists() for p in (out.parent, *out.parents))
            or not out.parent.is_dir() or out.exists()):
        raise ValueError("Existing local-only private archive/audit directories required; no overwrite")
    sources = sorted(archive_dir.glob("*.twseenc"))
    hex_key = resolve_archive_key(vault_path=args.key_vault,
                                  env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""))
    result = audit(sources, hex_key=hex_key)
    # No raw prices, per-stock feature vectors, secret keys or file paths.
    with out.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({
        "scope": result["scope"],
        "authenticated_archive_files": result["authenticated_archive_files"],
        "authenticated_source_rows": result["authenticated_source_rows"],
        "actual_source_sessions": result["authentic_distinct_2022_source_sessions"],
        "missing_actual_sessions_to_240":
            result["additional_real_market_sessions_needed_before_240_session_warmup"],
        "full_240_session_stocks": result["stocks_with_complete_last_240_source_sessions"],
        "12_vector_spotchecks": result["causal_12_technical_smc_vectors_spotchecked"],
        "model_release": "BLOCKED", "neon_rows_written": 0,
        "line_messages_sent": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
