"""Lossless TWSE raw OHLCV archive feasibility proof, without storing the archive.

READ-ONLY Neon: a small bounded current-listed, owner-allowed official-source
sample is loaded into ephemeral runner RAM, deterministically gzip-compressed,
decoded and hash-verified. Export ONLY size/hash aggregate evidence. Neither
raw rows nor compressed price archive are written to disk, CI artifacts or a
public GitHub repository. This is NOT a durable migration, backup or consent
to delete source rows/indexes.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path

from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

MAX_SAMPLE_ROWS = 10_000
MAX_SAMPLE_CALENDAR_DAYS = 10
FIELDS = (
    "market", "stock_id", "trade_date",
    "open", "high", "low", "close", "volume",
    "turnover", "price_change", "transactions",
    "source", "retrieved_at",
)
DECIMAL_FIELDS = frozenset((
    "open", "high", "low", "close", "turnover", "price_change",
))
INTEGER_FIELDS = frozenset(("volume", "transactions"))
SOURCE = "TWSE_MI_INDEX_ALLBUT0999"

READ_ONLY_QUERY = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT p.market,p.stock_id,p.trade_date,p.open,p.high,p.low,p.close,
       p.volume,p.turnover,p.price_change,p.transactions,p.source,p.retrieved_at
FROM public.daily_prices p
JOIN official_current_listed o
  ON o.market=p.market AND o.stock_id=p.stock_id
WHERE p.market='twse'
  AND p.source='TWSE_MI_INDEX_ALLBUT0999'
  AND p.trade_date BETWEEN %(start)s AND %(end)s
  AND NOT EXISTS (
    SELECT 1 FROM public.model_stock_exclusions x
    WHERE x.market=p.market AND x.stock_id=p.stock_id
  )
ORDER BY p.trade_date,p.stock_id
LIMIT %(max_rows)s
"""


def _encode_value(name, value):
    if value is None:
        if name in ("market", "stock_id", "trade_date", "source", "retrieved_at"):
            raise ValueError("Missing mandatory official price provenance")
        return None
    if name in DECIMAL_FIELDS:
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("Unverifiable exact PostgreSQL numeric for " + name)
        return str(value)
    if name in INTEGER_FIELDS:
        if type(value) is not int or value < 0:
            raise ValueError("Unverifiable exact integer for " + name)
        return value
    if name == "trade_date":
        if type(value) is not date:
            raise ValueError("Invalid trade date")
        return value.isoformat()
    if name == "retrieved_at":
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("Missing timestamp source-vintage timezone")
        return value.isoformat()
    if name == "market":
        if value != "twse":
            raise ValueError("Non-TWSE sample")
    elif name == "source":
        if value != SOURCE:
            raise ValueError("Non-official bulk source")
    elif name == "stock_id":
        if not isinstance(value, str) or len(value) != 4 or not value.isdigit():
            raise ValueError("Unsupported stock identifier")
    return value


def _record(row):
    if not isinstance(row, dict):
        raise ValueError("Expected original PostgreSQL column dictionary")
    return [_encode_value(key, row.get(key)) for key in FIELDS]


def _restore(array):
    if not isinstance(array, list) or len(array) != len(FIELDS):
        raise ValueError("Archived row schema mismatch")
    restored = {}
    for key, value in zip(FIELDS, array):
        if key in DECIMAL_FIELDS and value is not None:
            if not isinstance(value, str):
                raise ValueError("Decimal exactness lost")
            value = Decimal(value)
        elif key == "trade_date":
            value = date.fromisoformat(value)
        elif key == "retrieved_at":
            value = datetime.fromisoformat(value)
        restored[key] = value
    if _record(restored) != array:
        raise ValueError("Lossy gzip round-trip")
    return restored


def prove(rows, *, min_rows=1):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SAMPLE_ROWS:
        raise ValueError("Bounded actual source sample required")
    if type(min_rows) is not int or min_rows < 1 or len(rows) < min_rows:
        raise ValueError("Insufficient verified archive sample")
    previous_key = None
    day_set = set()
    serialized = bytearray()
    for row in rows:
        values = _record(row)
        day = date.fromisoformat(values[2])
        key = (day, values[1])
        if previous_key is not None and key <= previous_key:
            raise ValueError("Non-unique or incorrectly ordered official source keys")
        previous_key = key
        day_set.add(day)
        serialized.extend(
            (json.dumps(values, ensure_ascii=False, separators=(",", ":"),
                        allow_nan=False) + "\n").encode("utf-8")
        )
    raw = bytes(serialized)
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    decompressed = gzip.decompress(compressed)
    if decompressed != raw:
        raise AssertionError("Archive compressed checksum mismatch")
    restored = [_restore(json.loads(line)) for line in
                decompressed.decode("utf-8").splitlines()]
    if len(restored) != len(rows):
        raise AssertionError("Archive recovery row count mismatch")
    if any(_record(a) != _record(b) for a, b in zip(rows, restored)):
        raise AssertionError("Original and recovered source values differ")
    return {
        "schema_version": 1,
        "scope": "TWSE_EPHEMERAL_OFFICIAL_PRICE_COMPRESSION_SAMPLE_ONLY",
        "source": SOURCE,
        "sample_rows": len(rows),
        "sample_distinct_trade_dates": len(day_set),
        "canonical_jsonl_bytes": len(raw),
        "gzip_compressed_bytes": len(compressed),
        "indicative_compression_ratio": round(len(raw) / len(compressed), 4),
        "source_sha256_recovered_exactly": sha256(raw).hexdigest(),
        "restored_rows_equal_original_including_exact_decimal_and_vintage": True,
        "same_sample_is_not_a_durable_backup": True,
        "sample_does_not_prove_covered_five_year_archival": True,
        "compressed_size_is_not_neon_pg_storage_savings": True,
        "production_neon_rows_written": 0,
        "production_neon_indexes_dropped": 0,
        "raw_or_compressed_price_rows_uploaded_to_public_repository": False,
        "production_migration_approved": False,
        "line_messages_sent": 0,
        "live_trading_approved": False,
        "paid_upgrade_requested": False,
    }


def sample_readonly(database_url, *, start: date, end: date):
    if (not database_url or type(start) is not date or type(end) is not date
            or start > end or (end - start).days > MAX_SAMPLE_CALENDAR_DAYS
            or end > datetime.now(timezone.utc).date()):
        raise ValueError("A protected read-only connection and bounded historic dates are required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(
        database_url, connect_timeout=20, row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '45000ms'")
        rows = [dict(r) for r in conn.execute(
            READ_ONLY_QUERY,
            {"start": start, "end": end, "max_rows": MAX_SAMPLE_ROWS},
        ).fetchall()]
    return prove(rows, min_rows=1000)


def main():
    parser = argparse.ArgumentParser(description="RAM-only lossless TWSE price archive proof")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = sample_readonly(os.getenv("DATABASE_URL", ""),
                             start=args.start, end=args.end)
    report = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    # Only aggregate proof; never write the row-level or compressed payload.
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
