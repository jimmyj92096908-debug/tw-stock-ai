"""Disaster recovery from PRIVATE encrypted Neon Object Storage alone.

An external immutable manifest and independently retained AES-256 key permit
recovering a complete source slice AFTER the local original is lost. This
module never modifies Postgres, bypasses stock exclusions, or sends LINE.
Encrypted archives are authenticated completely before any rows are released.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_neon_private_object_archive import (
    BUCKET, DOWNLOAD_ENV, KEY_ENV, MAX_ARCHIVE_BYTES,
    _inspect_source_archive, approved_signed_url, load_verified_research_slice,
)

# Bind remote-recovery to the *existing* verified private main-branch bucket.
EXPECTED_HOST = "br-purple-smoke-a1t9dmzz.storage.c-1.ap-southeast-1.aws.neon.tech"
OBJECT_PATTERN = re.compile(
    r"market=twse/year=20[0-9]{2}/[A-Za-z0-9._=-]+[.]twseenc"
)
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
MANIFEST_VERSION = 1


def _object_key(value):
    if (not isinstance(value, str) or len(value) > 250
            or not OBJECT_PATTERN.fullmatch(value)
            or "/../" in value or "//" in value):
        raise ValueError("A canonical private TWSE archive object key is required")
    return value


def create_backup_manifest(path, *, hex_key, object_key):
    """Build a nonsecret byte/row inventory from a fully authenticated archive."""
    key = _object_key(object_key)
    _, size, integrity, digest = _inspect_source_archive(path, hex_key)
    return {
        "manifest_version": MANIFEST_VERSION,
        "bucket": BUCKET,
        "object_key": key,
        "encrypted_bytes": size,
        "encrypted_sha256": digest,
        "authenticated_rows": integrity["sample_rows"],
        "canonical_rows_sha256": integrity["canonical_rows_sha256"],
        "format": "TWSELOCAL-AES256GCM-1",
        "does_not_authorize_source_deletion": True,
    }


def _validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("An independently retained archive manifest is required")
    expected = {
        "manifest_version", "bucket", "object_key", "encrypted_bytes",
        "encrypted_sha256", "authenticated_rows", "canonical_rows_sha256",
        "format", "does_not_authorize_source_deletion",
    }
    if (set(manifest) != expected
            or type(manifest.get("manifest_version")) is not int
            or manifest["manifest_version"] != MANIFEST_VERSION
            or manifest["bucket"] != BUCKET
            or manifest["format"] != "TWSELOCAL-AES256GCM-1"
            or manifest["does_not_authorize_source_deletion"] is not True
            or type(manifest["encrypted_bytes"]) is not int
            or not 0 < manifest["encrypted_bytes"] <= MAX_ARCHIVE_BYTES
            or type(manifest["authenticated_rows"]) is not int
            or not 0 < manifest["authenticated_rows"] <= 50000
            or not isinstance(manifest["encrypted_sha256"], str)
            or not SHA256_PATTERN.fullmatch(manifest["encrypted_sha256"])
            or not isinstance(manifest["canonical_rows_sha256"], str)
            or not SHA256_PATTERN.fullmatch(manifest["canonical_rows_sha256"])):
        raise ValueError("Invalid private archive manifest or safe size bounds")
    _object_key(manifest["object_key"])
    return manifest


def recover_remote_archive(manifest, *, hex_key, url, session=None, max_rows=None):
    """Retrieve ciphertext with exact manifest and AES proof; never write SQL.

    max_rows=None: return only aggregate restore proof.
    max_rows=1..50000: additionally return bounded research rows in memory,
    but only AFTER the entire downloaded file is authenticated.
    """
    proof = _validate_manifest(manifest)
    host, path = approved_signed_url(url)
    if (host != EXPECTED_HOST or
            path != f"/{BUCKET}/{proof['object_key']}"):
        raise ValueError("Signed URL does not address the manifested private object")
    if max_rows is not None and (
            type(max_rows) is not int or not 1 <= max_rows <= 50000
            or proof["authenticated_rows"] > max_rows):
        raise ValueError("Remote research data would exceed the bounded memory limit")

    if session is None:
        import requests
        session = requests

    with tempfile.TemporaryDirectory(prefix="neon-private-recovery-") as td:
        file = Path(td) / "recovered.twseenc"
        digest = sha256()
        length = 0
        try:
            with session.get(url, stream=True, timeout=(10, 120),
                             allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError("Private storage could not be read")
                with file.open("xb") as writer:
                    for chunk in response.iter_content(chunk_size=1024*1024):
                        if not chunk:
                            continue
                        length += len(chunk)
                        if (length > MAX_ARCHIVE_BYTES or
                                length > proof["encrypted_bytes"]):
                            raise ValueError("Remote archive exceeds manifested bytes")
                        writer.write(chunk)
                        digest.update(chunk)
            if (length != proof["encrypted_bytes"] or
                    digest.hexdigest() != proof["encrypted_sha256"]):
                raise ValueError("Remote ciphertext SHA-256 mismatch")
            authenticated = verify_archive(file, hex_key=hex_key)
            if (authenticated["sample_rows"] != proof["authenticated_rows"]
                    or authenticated["canonical_rows_sha256"] !=
                    proof["canonical_rows_sha256"]):
                raise ValueError("Remote source rows differ from audit manifest")
            rows = (
                load_verified_research_slice(file, hex_key=hex_key,
                                             max_rows=max_rows)
                if max_rows is not None else None
            )
        except Exception:
            # No source rows, signed bearer token, or filesystem path leak.
            raise RuntimeError("Private encrypted recovery could not be verified") from None

    public_proof = {
        "scope": "PRIVATE_REMOTE_TWSE_ARCHIVE_RECOVERY_ONLY",
        "remote_archive_recovery_verified": True,
        "original_local_archive_not_required": True,
        "authenticated_rows": authenticated["sample_rows"],
        "encrypted_sha256": digest.hexdigest(),
        "canonical_rows_sha256": authenticated["canonical_rows_sha256"],
        "exact_decimal_and_source_vintage_verified":
            authenticated["all_decimal_values_and_retrieved_at_exactly_restored"],
        "five_year_coverage_verified": False,
        "neon_rows_written": 0,
        "neon_source_deletions_authorized": False,
        "line_messages_sent": 0,
    }
    if rows is not None:
        return public_proof, rows
    return public_proof


def main():
    cli = argparse.ArgumentParser(
        description="Verify disaster recovery from a private Neon AES archive"
    )
    cli.add_argument("action", choices=("manifest", "recover"))
    cli.add_argument("--archive", type=Path)
    cli.add_argument("--object-key")
    cli.add_argument("--manifest", type=Path)
    args = cli.parse_args()
    hex_key = os.environ.get(KEY_ENV, "")
    if args.action == "manifest":
        if not args.archive or not args.object_key:
            cli.error("Manifest needs a verified local encrypted archive and object key")
        result = create_backup_manifest(
            args.archive, hex_key=hex_key, object_key=args.object_key,
        )
    else:
        if not args.manifest:
            cli.error("Recovery requires a separately retained local manifest")
        result = recover_remote_archive(
            json.loads(args.manifest.read_text(encoding="utf-8")),
            hex_key=hex_key, url=os.environ.get(DOWNLOAD_ENV, ""),
        )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
