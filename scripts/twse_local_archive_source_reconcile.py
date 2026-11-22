"""Private, live Neon READ-ONLY reconciliation against verified AES TWSE archives.

This does not create an archive or touch production rows. For each owner-local
AES archive pair, it recomputes the exact canonical per-row SHA256 using a
single repeatable-read Neon snapshot with the SAME allowlisted source query
as export. Mismatched counts or digests fail closed. All outputs are aggregate
and stay on the owner's local computer; no GitHub CI Neon credentials.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path

from scripts.twse_local_encrypted_archive import (
    EXPORT_SQL, MAX_EXPORT_DAYS, ROWS_PER_CHUNK, _json_bytes,
)
from scripts.twse_local_archive_custody_audit import (
    MAX_ARCHIVES, MAX_MANIFEST_BYTES, verify_pair,
)
from scripts.twse_lossless_archive_feasibility import _record


def canonical_source_digest(rows, *, start, end):
    """Exact export-order reconstruction; no row contents in the report."""
    h = sha256()
    last_key = None
    count = 0
    for row in rows:
        values = _record(row)
        day = date.fromisoformat(values[2])
        k = (day, values[1])
        if (not start <= day <= end or values[1] == "1589"
                or last_key is not None and k <= last_key):
            raise ValueError("Unacceptable source order, date or excluded stock")
        last_key = k
        h.update(_json_bytes(values) + b"\n")
        count += 1
    return count, h.hexdigest()


def reconcile_archive_set(manifest, *, database_url, hex_key):
    if not database_url or not isinstance(manifest, dict):
        raise ValueError("Local full archive plan and Neon read-only URL required")
    try:
        start, end = date.fromisoformat(manifest["start"]), date.fromisoformat(manifest["end"])
        pairs = manifest["pairs"]
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError("Malformed owner-local archive inventory") from e
    if (not isinstance(pairs, list) or not 1 <= len(pairs) <= MAX_ARCHIVES
            or end < start or (end - start).days > 5*366):
        raise ValueError("Archive count and window must be bounded")

    proofs = []
    previous = None
    # Authenticate everything locally before opening the live database.
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {"primary", "backup"}:
            raise ValueError("Two local copies are required per archive period")
        p = verify_pair(pair["primary"],pair["backup"],hex_key=hex_key)
        first, last = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        if ((last-first).days > MAX_EXPORT_DAYS or first < start or last > end
            or previous is not None and first <= previous):
            raise ValueError("Unsorted, overlapping or outside archive date periods")
        previous = last
        proofs.append((first,last,p))

    import psycopg
    from psycopg.rows import dict_row
    checked = 0
    with psycopg.connect(
        database_url,connect_timeout=20,row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '120000ms'")
        for first,last,p in proofs:
            with conn.cursor(name="twse_local_archive_reconcile") as cursor:
                cursor.execute(EXPORT_SQL,{"start":first,"end":last})

                def stream():
                    while True:
                        batch = cursor.fetchmany(ROWS_PER_CHUNK)
                        if not batch:
                            break
                        for r in batch:
                            yield dict(r)

                count,digest = canonical_source_digest(stream(),start=first,end=last)
            if count != p["rows"] or digest != p["canonical_rows_sha256"]:
                raise ValueError("Live official source and authenticated local backup differ")
            checked += count
    contiguous = (
        proofs[0][0]==start and proofs[-1][1]==end and all(
            (right[0]-left[1]).days==1 for left,right in zip(proofs,proofs[1:])
        )
    )
    return {
        "schema_version":1,
        "scope":"LOCAL_TWSE_AES_ARCHIVE_VS_LIVE_NEON_SOURCE_READONLY",
        "archive_pairs_verified":len(proofs),
        "archive_rows_reconciled_to_live_source":checked,
        "all_archived_rows_matched_single_readonly_neon_snapshot":True,
        "consecutive_calendar_window_coverage":contiguous,
        "same_official_current_listed_survivor_filter_and_exclusions_used":True,
        "historical_asof_universe_reconstructed":False,
        "source_rows_outside_requested_date_windows_proven_complete":False,
        "actual_independent_key_recovery_and_physical_backup_proven":False,
        "isolated_database_restore_test_passed":False,
        "approved_for_neon_deletion":False,
        "approved_for_model_trading":False,
        "neon_database_writes":0,
        "line_modified":False,
        "paid_upgrade_requested":False,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Owner-local AES private archive versus live Neon read-only audit")
    parser.add_argument("--local-manifest",type=Path,required=True)
    a=parser.parse_args()
    manifest_path=a.local_manifest.expanduser()
    if not manifest_path.is_file() or manifest_path.stat().st_size>MAX_MANIFEST_BYTES:
        raise ValueError("Only a small private local manifest is supported")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    result=reconcile_archive_set(
        manifest,database_url=os.environ.get("DATABASE_URL",""),
        hex_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""),
    )
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
