"""LOCAL-ONLY encrypted TWSE source archive and fail-closed restoration verification.

Reads from production Neon using repeatable-read READ ONLY; writes encrypted
archive *only* to a user-owned, existing directory outside any git checkout.
No server-side DDL/DML; no file uploaded to GitHub; no restore INSERT/DELETE.
The locally generated archive is not by itself an independently backed-up,
audited migration and NEVER authorizes deleting Neon data.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import struct
import zlib

from scripts.twse_lossless_archive_feasibility import (
    FIELDS, SOURCE, _record, _restore,
)
from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

MAGIC = b"TWSELOCAL-AES256GCM-1\n"
VERSION = 1
ROWS_PER_CHUNK = 500
MAX_EXPORT_DAYS = 35
MAX_HEADER_BYTES = 4096
MAX_ENCRYPTED_FRAME_BYTES = 3_000_000
MAX_RAW_CHUNK_BYTES = 1_500_000
MAX_ROW_BYTES = 2048
KEY_ENV = "STOCK_ARCHIVE_KEY_HEX"

EXPORT_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT p.market,p.stock_id,p.trade_date,p.open,p.high,p.low,p.close,
       p.volume,p.turnover,p.price_change,p.transactions,p.source,p.retrieved_at
FROM public.daily_prices p
JOIN official_current_listed o
  ON o.market=p.market AND o.stock_id=p.stock_id
WHERE p.market='twse'
  AND p.source='TWSE_MI_INDEX_ALLBUT0999'
  AND p.trade_date BETWEEN %(start)s AND %(end)s
  AND p.stock_id<>'1589'
  AND NOT EXISTS (
    SELECT 1 FROM public.model_stock_exclusions x
    WHERE x.market=p.market AND x.stock_id=p.stock_id
  )
ORDER BY p.trade_date,p.stock_id
"""


def _key(hex_key):
    if not isinstance(hex_key, str) or len(hex_key) != 64:
        raise ValueError("A locally held 32-byte AES key is required")
    try:
        b = bytes.fromhex(hex_key)
    except ValueError as e:
        raise ValueError("Local AES key is not valid hex") from e
    if len(b) != 32:
        raise ValueError("AES-256 key required")
    return b


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False,
                      separators=(",", ":"), sort_keys=True,
                      allow_nan=False).encode("utf-8")


def _validate_dates(start, end):
    if (type(start) is not date or type(end) is not date or
        start > end or (end - start).days > MAX_EXPORT_DAYS or
        end > datetime.now(timezone.utc).date()):
        raise ValueError("A bounded nonfuture interval of at most 35 days is required")


def _safe_output(path):
    p = Path(path).expanduser().resolve()
    if not p.parent.is_dir() or p.is_dir():
        raise ValueError("Choose an existing owner-controlled private folder")
    # The user's repository is public; never accidentally stage the archive.
    if any((ancestor / ".git").exists() for ancestor in (p.parent, *p.parents)):
        raise ValueError("Encrypted price archives must remain outside git repositories")
    if p.exists():
        raise FileExistsError("Archive already exists; overwriting is prohibited")
    if p.suffix != ".twseenc":
        raise ValueError("Archive file must use .twseenc suffix")
    return p


def _read_exact(reader, size):
    data = reader.read(size)
    if len(data) != size:
        raise ValueError("Truncated or incomplete private archive")
    return data


def _frame(writer, cipher, aad_hash, prefix, index, kind, payload):
    if index < 0 or index >= 2**32:
        raise ValueError("Archive encrypted-frame limit exceeded")
    nonce = prefix + index.to_bytes(4, "big")
    sealed = cipher.encrypt(nonce, payload,
                            aad_hash + kind + index.to_bytes(4, "big"))
    if len(sealed) > MAX_ENCRYPTED_FRAME_BYTES:
        raise ValueError("Encrypted archive chunk too large")
    writer.write(kind + struct.pack(">I", len(sealed)) + sealed)


def _header(start, end):
    return {
        "format": VERSION,
        "source": SOURCE,
        "fields": list(FIELDS),
        "market": "twse",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "max_rows_per_chunk": ROWS_PER_CHUNK,
        "nonce_prefix": secrets.token_hex(8),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "current_official_issuer_survivors_only": True,
        "independent_historical_universe_proven": False,
        "production_database_writes": 0,
        "neon_source_migration_approved": False,
    }


def encrypt_rows(rows, archive_path, *, start, end, hex_key):
    """Bounded-memory encrypted streaming export; synthetic rows allowed in tests."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _validate_dates(start, end)
    key = _key(hex_key)
    path = _safe_output(archive_path)
    header = _header(start, end)
    raw_header = _json_bytes(header)
    aad_hash = sha256(raw_header).digest()
    prefix = bytes.fromhex(header["nonce_prefix"])
    cipher = AESGCM(key)
    previous = None
    sample_hash = sha256()
    count = chunks = 0
    buffer = bytearray()

    # The output is exclusive-create and is removed on ordinary failure. An
    # interrupted/power-failed partial archive fails closed on verification.
    try:
        with path.open("xb") as writer:
            writer.write(MAGIC + struct.pack(">I", len(raw_header)) + raw_header)

            def flush():
                nonlocal chunks
                if not buffer:
                    return
                if len(buffer) > MAX_RAW_CHUNK_BYTES:
                    raise ValueError("Oversized plaintext source chunk")
                payload = gzip.compress(bytes(buffer), compresslevel=9, mtime=0)
                _frame(writer, cipher, aad_hash, prefix, chunks, b"C", payload)
                chunks += 1
                buffer.clear()

            for row in rows:
                values = _record(row)
                day = date.fromisoformat(values[2])
                if not start <= day <= end or values[1] == "1589":
                    raise ValueError("Row outside allowed dates or owner exclusion")
                k = (day, values[1])
                if previous is not None and k <= previous:
                    raise ValueError("Duplicate or unsorted source primary key")
                previous = k
                line = _json_bytes(values) + b"\n"
                if len(line) > MAX_ROW_BYTES:
                    raise ValueError("Unexpectedly oversized stock source row")
                if len(buffer) + len(line) > MAX_RAW_CHUNK_BYTES:
                    flush()
                buffer.extend(line)
                sample_hash.update(line)
                count += 1
                if count % ROWS_PER_CHUNK == 0:
                    flush()
            flush()
            if count == 0:
                raise ValueError("No eligible official source rows to archive")
            footer = {
                "rows": count, "chunks": chunks,
                "canonical_rows_sha256": sample_hash.hexdigest(),
                "first_key": None,  # never expose row-level identity in plaintext
                "neon_deletions_authorized": False,
            }
            _frame(writer, cipher, aad_hash, prefix, chunks, b"F",
                   _json_bytes(footer))
            writer.flush()
            os.fsync(writer.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"archive_created_locally": True, "encrypted_file": str(path),
            "rows": count, "chunks": chunks,
            "independent_backup_verified": False,
            "production_neon_deleted_rows": 0, "line_modified": False,
            "migration_approved": False}


def _gunzip_bounded(payload):
    obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
    data = obj.decompress(payload, MAX_RAW_CHUNK_BYTES + 1)
    if (len(data) > MAX_RAW_CHUNK_BYTES or not obj.eof or
        obj.unconsumed_tail or obj.unused_data):
        raise ValueError("Corrupted or too-large compressed archive chunk")
    return data


def verify_archive(archive_path, *, hex_key):
    """Authenticate ALL frames, exact DECIMAL strings, keys and final footer.

    Restore is verification-only: this intentionally has no SQL writes.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    cipher = AESGCM(_key(hex_key))
    total = chunks = 0
    sample_hash = sha256()
    previous = None
    with Path(archive_path).expanduser().open("rb") as reader:
        if _read_exact(reader, len(MAGIC)) != MAGIC:
            raise ValueError("Unsupported or corrupt private archive")
        header_size = struct.unpack(">I", _read_exact(reader, 4))[0]
        if header_size <= 0 or header_size > MAX_HEADER_BYTES:
            raise ValueError("Invalid archive header length")
        raw_header = _read_exact(reader, header_size)
        try:
            header = json.loads(raw_header)
            if _json_bytes(header) != raw_header:
                raise ValueError("Noncanonical archive header")
            if (header.get("format") != VERSION or header.get("market") != "twse"
                or header.get("source") != SOURCE
                or header.get("fields") != list(FIELDS)
                or header.get("max_rows_per_chunk") != ROWS_PER_CHUNK
                or header.get("current_official_issuer_survivors_only") is not True
                or header.get("neon_source_migration_approved") is not False):
                raise ValueError("Archive schema/provenance mismatch")
            start = date.fromisoformat(header["start"])
            end = date.fromisoformat(header["end"])
            _validate_dates(start, end)
            prefix = bytes.fromhex(header["nonce_prefix"])
            if len(prefix) != 8:
                raise ValueError("Invalid archive nonce format")
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("Malformed archive metadata") from e
        aad_hash = sha256(raw_header).digest()
        index = 0
        while True:
            kind = _read_exact(reader, 1)
            if kind not in (b"C", b"F"):
                raise ValueError("Unknown encrypted frame")
            size = struct.unpack(">I", _read_exact(reader, 4))[0]
            if size < 16 or size > MAX_ENCRYPTED_FRAME_BYTES:
                raise ValueError("Invalid encrypted frame length")
            sealed = _read_exact(reader, size)
            nonce = prefix + index.to_bytes(4, "big")
            content = cipher.decrypt(
                nonce, sealed, aad_hash + kind + index.to_bytes(4, "big")
            )
            if kind == b"F":
                footer = json.loads(content)
                if (index != chunks or footer.get("rows") != total
                    or footer.get("chunks") != chunks
                    or footer.get("canonical_rows_sha256") != sample_hash.hexdigest()
                    or footer.get("neon_deletions_authorized") is not False
                    or total < 1 or reader.read(1)):
                    raise ValueError("Archive footer or complete-data SHA mismatch")
                break
            if chunks >= 2**32 - 2:
                raise ValueError("Too many encrypted archive chunks")
            raw = _gunzip_bounded(content)
            lines = raw.splitlines(keepends=True)
            if not lines or len(lines) > ROWS_PER_CHUNK:
                raise ValueError("Empty or oversized source chunk")
            for line in lines:
                if len(line) > MAX_ROW_BYTES or not line.endswith(b"\n"):
                    raise ValueError("Noncanonical or oversized source line")
                vals = json.loads(line)
                if not isinstance(vals, list) or len(vals) != len(FIELDS):
                    raise ValueError("Malformed source row")
                recovered = _restore(vals)
                if _json_bytes(_record(recovered)) + b"\n" != line:
                    raise ValueError("Noncanonical row loses exact original precision")
                day, stock = recovered["trade_date"], recovered["stock_id"]
                k = (day, stock)
                if (not start <= day <= end or stock == "1589" or
                    previous is not None and k <= previous):
                    raise ValueError("Duplicate, excluded or nonchronological archive row")
                previous = k
                sample_hash.update(line)
                total += 1
            chunks += 1
            index += 1
    return {
        "archive_integrity_verified": True,
        "sample_rows": total,
        "chunks": chunks,
        "canonical_rows_sha256": sample_hash.hexdigest(),
        "all_decimal_values_and_retrieved_at_exactly_restored": True,
        "data_was_never_restored_to_neon": True,
        "independent_second_backup_verified": False,
        "delete_or_migrate_neon_authorized": False,
        "line_modified": False,
    }


def export_neon_readonly(database_url, *, start, end, archive_path, hex_key):
    _validate_dates(start, end)
    if not database_url:
        raise ValueError("DATABASE_URL required for local read-only export")
    import psycopg
    from psycopg.rows import dict_row

    # Named cursor streams bounded chunks; all reads in one immutable
    # transaction snapshot. SQL lists currently official surviving stocks,
    # excludes owner's 1589 and all model_stock_exclusions, and reads no LINE.
    with psycopg.connect(
        database_url, connect_timeout=20, row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '120000ms'")
        with conn.cursor(name="twse_local_private_archive") as cur:
            cur.execute(EXPORT_SQL, {"start": start, "end": end})

            def stream():
                while True:
                    batch = cur.fetchmany(ROWS_PER_CHUNK)
                    if not batch:
                        break
                    for row in batch:
                        yield dict(row)

            result = encrypt_rows(stream(), archive_path,
                                  start=start, end=end, hex_key=hex_key)
    checked = verify_archive(archive_path, hex_key=hex_key)
    if checked["sample_rows"] != result["rows"]:
        raise AssertionError("Local encrypted archive verification count mismatch")
    return result | {"local_full_archive_integrity_verified": True}


def main():
    p = argparse.ArgumentParser(description="Local-only AES-256-GCM TWSE archive")
    p.add_argument("action", choices=("export", "verify"))
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat)
    args = p.parse_args()
    hex_key = os.environ.get(KEY_ENV, "")
    if args.action == "export":
        result = export_neon_readonly(
            os.environ.get("DATABASE_URL", ""),
            start=args.start, end=args.end,
            archive_path=args.archive, hex_key=hex_key,
        )
    else:
        result = verify_archive(args.archive, hex_key=hex_key)
    # File path/row count may be printed on the owner's private machine, not
    # on GitHub Actions. Never log the key or the raw/source payload.
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
