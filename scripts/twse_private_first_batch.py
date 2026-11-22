"""Safe two-stage first-batch TWSE backup: local prepare, private upload-check.

PREPARE: streaming repeatable-read SELECT -> private AES256 archive and an
independent nonsecret manifest. No storage URLs required while exporting.
UPLOAD-CHECK: verify existing archive + manifest *before* authenticated PUT;
independently fetch and verify the same private object without local source.
Never delete, overwrite, or write to Neon PostgreSQL; never touch LINE.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path

from scripts.twse_local_encrypted_archive import (
    KEY_ENV, _key, _safe_output, export_neon_readonly,
)
from scripts.twse_neon_private_object_archive import (
    DOWNLOAD_ENV, UPLOAD_ENV, _inspect_source_archive, approved_signed_url,
    upload_encrypted_archive,
)
from scripts.twse_neon_remote_restore import (
    BUCKET, EXPECTED_HOST, _object_key, _validate_manifest,
    create_backup_manifest, recover_remote_archive,
)


def _manifest_path(archive, manifest):
    """Refuse Git checkouts, existing files, cross-directory manifests."""
    path = Path(archive).expanduser().resolve()
    output = Path(manifest).expanduser().resolve()
    if (not path.parent.is_dir() or not output.parent.is_dir()
            or path.parent != output.parent or
            output.suffix != ".json" or
            not output.name.endswith(".manifest.json")
            or output == path or output.exists()):
        raise ValueError("An unused private .manifest.json alongside archive is required")
    for ancestor in (output.parent, *output.parents):
        if (ancestor / ".git").exists():
            raise ValueError("Private archive manifests must remain outside Git")
    return output


def _save_manifest_exclusive(output, manifest):
    """Atomic enough for local use: no overwritten manifest, flushed to disk."""
    serialized = (json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False) + "\n").encode()
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def prepare(*, database_url, hex_key, start, end,
            archive_path, manifest_path, object_key):
    """No provider writes; preserve archive even if a later stage fails."""
    _key(hex_key)
    if not database_url or type(start) is not date or type(end) is not date:
        raise ValueError("Private database credential and historical dates required")
    if start.year != end.year or end < start:
        raise ValueError("Use a nonoverlapping single-calendar-year archive")
    key = _object_key(object_key)
    if not key.startswith("market=twse/year=" + str(start.year) + "/"):
        raise ValueError("Archive object year must match source dates")
    local_file = _safe_output(archive_path)
    local_manifest = _manifest_path(local_file, manifest_path)
    exported = export_neon_readonly(
        database_url, start=start, end=end, archive_path=local_file,
        hex_key=hex_key,
    )
    manifest = create_backup_manifest(
        local_file, hex_key=hex_key, object_key=key,
    )
    if manifest["authenticated_rows"] != exported["rows"]:
        raise RuntimeError("Post-export source row count mismatch")
    _save_manifest_exclusive(local_manifest, manifest)
    return {
        "scope": "TWSE_PRIVATE_FIRST_BATCH_PREPARED_NOT_REMOTE_BACKED_UP",
        "source_rows_exported": exported["rows"],
        "ciphertext_sha256": manifest["encrypted_sha256"],
        "local_manifest_created": True,
        "private_object_remote_verified": False,
        "production_neon_rows_written_or_deleted": 0,
        "line_messages_sent": 0,
        "storage_limit_modified": False,
    }


def upload_check(*, archive_path, manifest_path, hex_key,
                 upload_url, download_url, session=None):
    """Require local proof, then remote-only recovery of the exact same key."""
    _key(hex_key)
    archive = Path(archive_path).expanduser().resolve()
    manifest_path = Path(manifest_path).expanduser().resolve()
    if not archive.is_file() or not manifest_path.is_file():
        raise ValueError("An existing local encrypted file and independent manifest are required")
    if manifest_path.parent != archive.parent:
        raise ValueError("Manifest must be retained in the same private folder")
    manifest = _validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    upload_host, upload_path = approved_signed_url(upload_url)
    down_host, down_path = approved_signed_url(download_url)
    wanted = "/" + BUCKET + "/" + manifest["object_key"]
    if (upload_host != EXPECTED_HOST or down_host != EXPECTED_HOST
            or upload_path != wanted or down_path != wanted):
        raise ValueError("PUT and GET must use the same manifested private Neon object")
    _, bytes_size, authenticated, digest = _inspect_source_archive(archive, hex_key)
    if (bytes_size != manifest["encrypted_bytes"]
            or digest != manifest["encrypted_sha256"]
            or authenticated["sample_rows"] != manifest["authenticated_rows"]
            or authenticated["canonical_rows_sha256"] !=
            manifest["canonical_rows_sha256"]):
        raise ValueError("Local encrypted archive no longer matches manifest")
    uploaded = upload_encrypted_archive(
        archive, hex_key=hex_key, url=upload_url, session=session,
    )
    # Deliberately verify from manifest + remote GET rather than checking
    # only a PUT status; no original local archive is needed by recovery.
    verified = recover_remote_archive(
        manifest, hex_key=hex_key, url=download_url, session=session,
    )
    if not (uploaded["encrypted_archive_uploaded"] and
            verified["remote_archive_recovery_verified"] and
            verified["authenticated_rows"] == manifest["authenticated_rows"]):
        raise RuntimeError("Private remote archival proof incomplete")
    return {
        "scope": "TWSE_PRIVATE_FIRST_BATCH_REMOTE_ARCHIVE_VERIFIED",
        "source_rows": verified["authenticated_rows"],
        "ciphertext_sha256": manifest["encrypted_sha256"],
        "remote_recovery_without_local_copy_verified": True,
        "five_year_source_coverage_proven": False,
        "production_neon_rows_written_or_deleted": 0,
        "line_messages_sent": 0,
        "storage_limit_modified": False,
        "production_deletion_authorized": False,
    }


def main():
    ap = argparse.ArgumentParser(description="No-cost private first-batch TWSE archive")
    ap.add_argument("action", choices=("prepare", "upload-check"))
    ap.add_argument("--archive", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--object-key")
    args = ap.parse_args()
    try:
        if args.action == "prepare":
            if args.start is None or args.end is None or not args.object_key:
                ap.error("prepare requires --start, --end and --object-key")
            result = prepare(
                database_url=os.environ.get("DATABASE_URL", ""),
                hex_key=os.environ.get(KEY_ENV, ""),
                start=args.start, end=args.end,
                archive_path=args.archive, manifest_path=args.manifest,
                object_key=args.object_key,
            )
        else:
            result = upload_check(
                archive_path=args.archive,
                manifest_path=args.manifest,
                hex_key=os.environ.get(KEY_ENV, ""),
                upload_url=os.environ.get(UPLOAD_ENV, ""),
                download_url=os.environ.get(DOWNLOAD_ENV, ""),
            )
    except Exception:
        # Never print source rows, signed URLs, database DSN or AES key.
        raise SystemExit("Private TWSE archive stage not verified; production unchanged") from None
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
