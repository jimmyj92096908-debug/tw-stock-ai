"""Verify TWO owner-local encrypted TWSE archive copies and date-range custody.

The archive is never decrypted to disk, never uploaded to GitHub, and never
used for production DML. This produces *local* integrity evidence only:
two valid copies may still be physically co-located, incomplete relative
to the exchange, or without an independently recoverable secret key.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import struct

from scripts.twse_local_encrypted_archive import (
    MAGIC, MAX_HEADER_BYTES, _json_bytes, _read_exact, verify_archive,
)

MAX_ARCHIVES = 72
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024


def _file(path):
    original = Path(path).expanduser()
    if not original.is_file() or original.suffix != ".twseenc":
        raise ValueError("Existing encrypted local .twseenc file required")
    if original.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds local safety size")
    return original


def _hash_file(path):
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _range_header(path):
    """The plaintext archive header is NOT treated as proof until AES verifies."""
    with path.open("rb") as f:
        if _read_exact(f, len(MAGIC)) != MAGIC:
            raise ValueError("Wrong private encrypted file format")
        size = struct.unpack(">I", _read_exact(f, 4))[0]
        if not 0 < size <= MAX_HEADER_BYTES:
            raise ValueError("Invalid authenticated archive metadata length")
        raw = _read_exact(f, size)
        doc = json.loads(raw)
        if not isinstance(doc, dict) or _json_bytes(doc) != raw:
            raise ValueError("Noncanonical archive metadata")
        return date.fromisoformat(doc["start"]), date.fromisoformat(doc["end"])


def verify_pair(primary, backup, *, hex_key):
    """Validate distinct files, byte-for-byte SHA and both AES-GCM payloads."""
    original, duplicate = _file(primary), _file(backup)
    if os.path.samefile(original, duplicate):
        raise ValueError("Copy must not be the original file or its hardlink")
    # A symlink or same inode cannot count as a second backup.
    if original.resolve() == duplicate.resolve():
        raise ValueError("Copy points to the original archive")
    a, b = verify_archive(original, hex_key=hex_key), verify_archive(
        duplicate, hex_key=hex_key
    )
    a_hash, b_hash = _hash_file(original), _hash_file(duplicate)
    if (a_hash != b_hash or
        a["sample_rows"] != b["sample_rows"] or
        a["canonical_rows_sha256"] != b["canonical_rows_sha256"]):
        raise ValueError("Backup differs from authenticated original")
    start, end = _range_header(original)
    second_start, second_end = _range_header(duplicate)
    if (start, end) != (second_start, second_end):
        raise ValueError("Archive date ranges differ")
    separate_mount = original.stat().st_dev != duplicate.stat().st_dev
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": a["sample_rows"],
        "encrypted_archive_sha256": a_hash,
        "canonical_rows_sha256": a["canonical_rows_sha256"],
        "both_copies_authentication_passed": True,
        "two_distinct_archive_files_verified": True,
        "different_filesystem_devices_observed": separate_mount,
        # Different st_dev may be virtual mounts; neither that nor same bytes
        # proves a geographically/physically independent recoverable backup.
        "physical_independence_and_retention_proven": False,
        "separate_key_recovery_verified": False,
        "live_restore_into_isolated_database_verified": False,
        "neon_delete_or_migrate_authorized": False,
    }


def review_manifest(manifest: dict, *, hex_key: str) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("Local custody plan object required")
    try:
        start = date.fromisoformat(manifest["start"])
        end = date.fromisoformat(manifest["end"])
        entries = manifest["pairs"]
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("Required bounded local archive date plan missing") from e
    if (not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ARCHIVES
            or end < start or (end - start).days > 5 * 366):
        raise ValueError("Invalid full-range or excessive private archive set")
    previous_end = None
    pair_reports = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"primary", "backup"}:
            raise ValueError("Each period needs exactly two locally named copies")
        proof = verify_pair(entry["primary"], entry["backup"], hex_key=hex_key)
        first, last = date.fromisoformat(proof["start"]), date.fromisoformat(proof["end"])
        if (first < start or last > end or
                previous_end is not None and first <= previous_end):
            raise ValueError("Archive period outside range, duplicate or overlapping")
        previous_end = last
        pair_reports.append(proof)
    contiguous = (pair_reports[0]["start"] == start.isoformat()
                  and pair_reports[-1]["end"] == end.isoformat()
                  and all(
                      (date.fromisoformat(right["start"]) -
                       date.fromisoformat(left["end"])).days == 1
                      for left, right in zip(pair_reports, pair_reports[1:])
                  ))
    return {
        "schema_version": 1,
        "scope": "OWNER_LOCAL_PRIVATE_TWSE_ARCHIVE_COPY_AUDIT_ONLY",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "archive_pairs_verified": len(pair_reports),
        "total_archived_rows": sum(p["rows"] for p in pair_reports),
        "distinct_copies_authenticated_and_equal": True,
        "consecutive_calendar_window_coverage": contiguous,
        "periods_observed_on_distinct_filesystem_devices": sum(
            1 for p in pair_reports if p["different_filesystem_devices_observed"]
        ),
        "physical_independence_verified": False,
        "separately_recoverable_encryption_key_proven": False,
        "real_source_row_count_and_day_ledger_reconciled": False,
        "historical_delisted_issuer_roster_included": False,
        "all_five_year_trading_days_archived": False,
        "point_in_time_total_return_model_approved": False,
        "live_database_restore_tested": False,
        "neon_rows_changed": 0,
        "line_modified": False,
        "neon_deletion_or_migration_approved": False,
        "paid_upgrade_requested": False,
        # Never serialize file paths, per-row stock IDs or source payload.
    }


def main():
    p = argparse.ArgumentParser(description="Audit private AES archive duplicate copies")
    p.add_argument("--local-manifest", type=Path, required=True)
    args = p.parse_args()
    path = args.local_manifest.expanduser().resolve()
    if (not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES):
        raise ValueError("A small existing local-only manifest is required")
    report = review_manifest(
        json.loads(path.read_text(encoding="utf-8")),
        hex_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
