"""Encrypted TWSE research archive transport to private Neon Object Storage.

This layer NEVER uploads plaintext historical prices or keys, NEVER writes to
Postgres, and NEVER deletes original prices. Presigned URLs come from Neon's
private storage API and are supplied only in process environment variables.
Full authenticated roundtrip is required before counting a remote copy verified.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit

from scripts.twse_local_encrypted_archive import (
    _safe_output, verify_archive,
)

BUCKET = "tw-stock-ai-private-history"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
CONTENT_TYPE = "application/octet-stream"
UPLOAD_ENV = "NEON_PRIVATE_HISTORY_UPLOAD_URL"
DOWNLOAD_ENV = "NEON_PRIVATE_HISTORY_DOWNLOAD_URL"
KEY_ENV = "STOCK_ARCHIVE_KEY_HEX"
NEON_HOST = re.compile(
    r"br-[a-z0-9-]+\\.storage\\.c-[0-9]+\\.[a-z0-9-]+\\.aws\\.neon\\.tech"
)


def approved_signed_url(value):
    """Reject plain HTTP, unrelated endpoints, public hosts and unsigned URLs."""
    if not isinstance(value, str) or len(value) > 8000:
        raise ValueError("A temporary Neon private-storage signed URL is required")
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname
        or parts.port is not None or parts.username is not None
        or parts.password is not None or parts.fragment
        or not NEON_HOST.fullmatch(parts.hostname)
        or not unquote(parts.path).startswith(f"/{BUCKET}/")
        or not unquote(parts.path).endswith(".twseenc")):
        raise ValueError("Unexpected Neon private archive URL endpoint")
    q = parse_qs(parts.query, keep_blank_values=True)
    try:
        expires = int(q["X-Amz-Expires"][0])
        signatures = q["X-Amz-Signature"]
        algorithms = q["X-Amz-Algorithm"]
    except (KeyError, ValueError, IndexError) as exc:
        raise ValueError("Missing authenticated temporary upload/download signature") from exc
    if (not 1 <= expires <= 3600 or len(signatures) != 1
        or not signatures[0] or algorithms != ["AWS4-HMAC-SHA256"]):
        raise ValueError("Invalid or overly long presigned storage authorization")
    return parts.hostname, unquote(parts.path)


def _inspect_source_archive(path, hex_key):
    src = Path(path).expanduser().resolve()
    if not src.is_file() or src.suffix != ".twseenc":
        raise ValueError("A local encrypted .twseenc archive is required")
    length = src.stat().st_size
    if not 0 < length <= MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds bounded private storage upload limit")
    verified = verify_archive(src, hex_key=hex_key)
    fingerprint = sha256()
    with src.open("rb") as reader:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            fingerprint.update(block)
    return src, length, verified, fingerprint.hexdigest()


def upload_encrypted_archive(path, *, hex_key, url, session=None):
    """Upload only a previously AES-authenticated complete encrypted file."""
    approved_signed_url(url)
    src, length, proof, digest = _inspect_source_archive(path, hex_key)
    if session is None:
        import requests
        session = requests
    try:
        with src.open("rb") as stream:
            response = session.put(
                url, data=stream, headers={"Content-Type": CONTENT_TYPE},
                timeout=(10, 120), allow_redirects=False,
            )
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Private Neon upload rejected")
    except Exception:
        # Signed URLs can be embedded in HTTP errors: never echo exception.
        raise RuntimeError("Private Neon archive upload failed") from None
    return {
        "encrypted_archive_uploaded": True,
        "remote_download_and_integrity_verified": False,
        "encrypted_bytes": length,
        "encrypted_sha256": digest,
        "authenticated_source_rows": proof["sample_rows"],
        "neon_price_rows_deleted": 0,
        "archive_never_authorizes_neon_deletion": True,
    }


def verify_remote_copy(path, *, hex_key, url, session=None):
    """Download into a private temporary directory, authenticate and compare."""
    approved_signed_url(url)
    src, expected_length, expected_proof, expected_sha = _inspect_source_archive(path, hex_key)
    if session is None:
        import requests
        session = requests
    with tempfile.TemporaryDirectory(prefix="private-neon-history-") as td:
        received = Path(td) / "remote.twseenc"
        digest = sha256()
        total = 0
        try:
            with session.get(url, stream=True, timeout=(10, 120),
                             allow_redirects=False) as response:
                if not 200 <= response.status_code < 300:
                    raise ValueError("Private Neon download rejected")
                with received.open("xb") as output:
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        if not block:
                            continue
                        total += len(block)
                        if total > MAX_ARCHIVE_BYTES or total > expected_length:
                            raise ValueError("Oversized or mismatched remote archive")
                        output.write(block)
                        digest.update(block)
            if total != expected_length or digest.hexdigest() != expected_sha:
                raise ValueError("Remote encrypted bytes differ from local archive")
            restored = verify_archive(received, hex_key=hex_key)
        except Exception:
            # Never leak presigned URLs or source row values in logs.
            raise RuntimeError("Private Neon remote archive verification failed") from None
    if (restored["sample_rows"] != expected_proof["sample_rows"]
        or restored["canonical_rows_sha256"] != expected_proof["canonical_rows_sha256"]):
        raise RuntimeError("Neon remote source rows differ after authenticated recovery")
    return {
        "remote_download_and_integrity_verified": True,
        "exact_encrypted_archive_sha256": expected_sha,
        "authenticated_restored_rows": restored["sample_rows"],
        "exact_decimal_and_source_vintage_verified":
            restored["all_decimal_values_and_retrieved_at_exactly_restored"],
        "original_neon_rows_modified": 0,
        "neon_price_rows_deleted": 0,
        "archive_never_authorizes_neon_deletion": True,
        "independent_historical_source_universe_verified": False,
        "five_year_coverage_verified": False,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Private Neon Object Storage AES source archive transfer"
    )
    ap.add_argument("action", choices=("upload", "verify", "upload-verify"))
    ap.add_argument("--archive", type=Path, required=True)
    opts = ap.parse_args()
    key = os.environ.get(KEY_ENV, "")
    upload_url = os.environ.get(UPLOAD_ENV, "")
    download_url = os.environ.get(DOWNLOAD_ENV, "")
    if opts.action in ("upload", "upload-verify"):
        upload_host, upload_path = approved_signed_url(upload_url)
    if opts.action in ("verify", "upload-verify"):
        download_host, download_path = approved_signed_url(download_url)
    if opts.action == "upload-verify" and (
        upload_host != download_host or upload_path != download_path
    ):
        raise ValueError("Upload and download must target the exact same private object")
    reports = []
    if opts.action in ("upload", "upload-verify"):
        reports.append(upload_encrypted_archive(
            opts.archive, hex_key=key, url=upload_url
        ))
    if opts.action in ("verify", "upload-verify"):
        reports.append(verify_remote_copy(
            opts.archive, hex_key=key, url=download_url
        ))
    print(json.dumps({
        "scope": "PRIVATE_ENCRYPTED_TWSE_ARCHIVE_NO_PRODUCTION_DELETION",
        "reports": reports,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
    }, allow_nan=False))


if __name__ == "__main__":
    main()
