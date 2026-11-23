"""Owner-only AES archive cold-copy + authenticated independent-folder restore rehearsal.

Never connects to Neon/LINE or restores to PostgreSQL. Never deletes originals.
A successful local copy/decrypt rehearsal is NOT proof of external physical-media
independence, historical PIT completeness, or permission to delete production rows.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_archives
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive, _key
from scripts.twse_archive_key_vault import resolve_archive_key

SCOPE = "OWNER_TWSE_2021_2022_AES_COLD_RESTORE_REHEARSAL_ONLY"
MAX_FILES = 144
MAX_TOTAL_BYTES = 4_000_000_000
COPY_CHUNK = 1024 * 1024
MIN_FREE_RESERVE_BYTES = 50_000_000


def _no_git_ancestors(path):
    if any((p / ".git").exists() for p in (path, *path.parents)):
        raise ValueError("Private AES backup and report must stay outside git")


def _fresh_restore_dir(raw, sources):
    p = Path(raw).expanduser()
    if p.is_symlink() or p.exists() or not p.parent.is_dir() or p.parent.is_symlink():
        raise ValueError("Choose an unused directory inside an existing private backup parent")
    resolved_parent = p.parent.resolve()
    _no_git_ancestors(resolved_parent)
    target = resolved_parent / p.name
    for source in sources:
        folder = source.resolve()
        # Do not nest a copy under any source directory or alias one of them.
        if target == folder or folder in target.parents or target in folder.parents:
            raise ValueError("Restore directory must be separate from original AES source folders")
    return target


def _file_sha256(path):
    hashed = sha256()
    with path.open("rb") as src:
        while True:
            block = src.read(COPY_CHUNK)
            if not block:
                break
            hashed.update(block)
    return hashed.hexdigest()


def _copy_exclusive(source, destination):
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst, length=COPY_CHUNK)
        dst.flush()
        os.fsync(dst.fileno())


def _audit(paths, key, year):
    start, end = (date(2021, 1, 1), date(2022, 1, 1)) if year == 2021 \
        else (date(2022, 1, 1), date(2023, 1, 1))
    result = authenticated_archive_days(paths, hex_key=key, start=start, end=end)
    if (result.get("full_file_integrity_verified") is not True or
        result.get("postgres_writes") != 0 or result.get("line_messages") != 0):
        raise ValueError("AES archive authenticated source census failed")
    return result


def rehearse(source_2021, source_2022, restore_dir, *, hex_key,
             expected_source_days=(28, 162)):
    """Perform actual ciphertext-copy and full AES-GCM row-level restore checks.

    expected_source_days is fixed by the owner CLI; tests may supply a tiny
    synthetic reference corpus. Production SQL and its guards are untouched.
    """
    _key(hex_key)
    if (not isinstance(expected_source_days, tuple) or
        len(expected_source_days) != 2 or
        any(type(n) is not int or n < 1 for n in expected_source_days)):
        raise ValueError("Invalid authenticated source calendar targets")
    folder21 = Path(source_2021).expanduser()
    folder22 = Path(source_2022).expanduser()
    if folder21.resolve() == folder22.resolve():
        raise ValueError("2021 and 2022 source folders must be separate")
    originals = {
        "2021": _private_archives(folder21),
        "2022": _private_archives(folder22),
    }
    all_sources = originals["2021"] + originals["2022"]
    if not 2 <= len(all_sources) <= MAX_FILES or len(set(all_sources)) != len(all_sources):
        raise ValueError("Duplicate or excessive private AES inventory")
    target = _fresh_restore_dir(restore_dir, (folder21, folder22))
    size_total = sum(p.stat().st_size for p in all_sources)
    if not 0 < size_total <= MAX_TOTAL_BYTES:
        raise ValueError("Encrypted restore rehearsal exceeds bounded copy budget")
    if shutil.disk_usage(target.parent).free < size_total + MIN_FREE_RESERVE_BYTES:
        raise ValueError("Insufficient free space for independent-folder restore copy")

    original_hashes = {str(p): _file_sha256(p) for p in all_sources}
    original_audits = {}
    for year, exp in zip(("2021", "2022"), expected_source_days):
        a = _audit(originals[year], hex_key, int(year))
        if len(a["days"]) != exp:
            raise ValueError("Original AES corpus differs from authenticated source-day baseline")
        original_audits[year] = a

    # Create the destination ONLY after source authenticity and capacity checks.
    # An interrupted run leaves untrusted partial copies; never overwrite them.
    target.mkdir(exist_ok=False)
    manifest = []
    mirrored = {"2021": [], "2022": []}
    for year in ("2021", "2022"):
        subdir = target / year
        subdir.mkdir(exist_ok=False)
        for src in originals[year]:
            dest = subdir / src.name
            if dest.exists() or dest.is_symlink():
                raise ValueError("Refusing to overwrite a restored archive")
            if _file_sha256(src) != original_hashes[str(src)]:
                raise ValueError("Original AES archive was modified before copying")
            _copy_exclusive(src, dest)
            copied_sha = _file_sha256(dest)
            if copied_sha != original_hashes[str(src)] or dest.stat().st_size != src.stat().st_size:
                raise ValueError("Copied archive differs byte-for-byte from original")
            original_check = verify_archive(src, hex_key=hex_key)
            restored_check = verify_archive(dest, hex_key=hex_key)
            for proof in (original_check, restored_check):
                if (proof.get("archive_integrity_verified") is not True or
                    proof.get("all_decimal_values_and_retrieved_at_exactly_restored") is not True or
                    proof.get("delete_or_migrate_neon_authorized") is not False):
                    raise ValueError("AES-GCM or exact-precision restore not proven")
            if (original_check["sample_rows"] != restored_check["sample_rows"] or
                original_check["canonical_rows_sha256"] != restored_check["canonical_rows_sha256"] or
                original_check["chunks"] != restored_check["chunks"]):
                raise ValueError("Recovered source rows do not match original encrypted archive")
            mirrored[year].append(dest)
            manifest.append({
                "source_year": int(year),
                "encrypted_filename": src.name,
                "encrypted_file_sha256": copied_sha,
                "encrypted_bytes": dest.stat().st_size,
                "authenticated_original_and_recovered_rows": restored_check["sample_rows"],
                "canonical_rows_sha256": restored_check["canonical_rows_sha256"],
            })
    copy_audits = {}
    for year, exp in zip(("2021", "2022"), expected_source_days):
        copied = _audit(mirrored[year], hex_key, int(year))
        before = original_audits[year]
        if (len(copied["days"]) != exp or copied["days"] != before["days"] or
            copied["authenticated_private_source_rows"] !=
            before["authenticated_private_source_rows"]):
            raise ValueError("Recovered authenticated TWSE source-day calendar changed")
        copy_audits[year] = copied
    # Last source hash check ensures the original was never rewritten while
    # another source file or copy was being decrypted.
    if any(_file_sha256(p) != original_hashes[str(p)] for p in all_sources):
        raise ValueError("Original AES source changed during restore rehearsal")

    report = {
        "schema_version": 1,
        "scope": SCOPE,
        "source_archives_copied_and_authenticated": len(all_sources),
        "encrypted_bytes_copied": size_total,
        "authenticated_2021_source_days": len(copy_audits["2021"]["days"]),
        "authenticated_2022_aes_source_days": len(copy_audits["2022"]["days"]),
        "original_vs_restored_ciphertext_sha256_all_equal": True,
        "original_vs_restored_canonical_OHLCV_rows_all_equal": True,
        "all_chunks_aes_gcm_authenticated": True,
        "source_files_modified": False,
        "encrypted_copy_recovery_receipt": manifest,
        "source_copy_proven_to_be_on_separate_physical_media": False,
        "recoverability_of_entire_neon_database_proven": False,
        "historical_point_in_time_listing_or_actions_complete": False,
        "restore_into_neon_tested": False,
        "authorized_to_delete_or_rewrite_neon_data": False,
        "safe_to_run_production_backfill": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_used": False,
    }
    receipt = target / "private-aes-cold-restore-receipt.json"
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-2021", required=True)
    parser.add_argument("--archive-2022", required=True)
    parser.add_argument("--key-vault", required=True)
    parser.add_argument("--restore-dir", required=True,
                        help="UNUSED owner-private directory on an independently controlled volume")
    opts = parser.parse_args()
    # No secret or raw row content is ever sent to stdout / GitHub.
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit("Owner AES cold restore rehearsal cannot run in CI")
    try:
        key = resolve_archive_key(
            vault_path=opts.key_vault,
            env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
        )
        result = rehearse(opts.archive_2021, opts.archive_2022,
                          opts.restore_dir, hex_key=key)
    except Exception:
        raise SystemExit(
            "Owner AES cold restore rehearsal FAILED; original source untouched, "
            "copied destination may be incomplete and must not be used for recovery; "
            "no Neon or LINE changes; no private details printed"
        ) from None
    print(json.dumps({
        "status": "OWNER_2021_2022_AES_COPY_AND_CRYPTO_RESTORE_REHEARSAL_PASS",
        "verified_archives": result["source_archives_copied_and_authenticated"],
        "authenticated_2021_source_days": result["authenticated_2021_source_days"],
        "authenticated_2022_aes_source_days": result["authenticated_2022_aes_source_days"],
        "physical_media_independence_proven": False,
        "neon_deleted_or_rewritten": False,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
