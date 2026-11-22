"""Recover an authenticated TWSE AES archive into DISPOSABLE LOCAL PostgreSQL TEMP.

No production connections permitted. Target is 127.0.0.1/localhost with
exact dbname+role stock_ci_restore; no connection string query parameters.
Only a session-local TEMP table ON COMMIT DROP is written. After full
authenticated-source restore and exact DECIMAL/ISO vintage+SHA comparison,
the TEMP table is destroyed. A corrupt footer or mismatch rolls back.

This is a RESTORATION DRILL, not a durable data migration, independent
physical backup, permission to delete Neon rows, or model publication.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from scripts.twse_local_encrypted_archive import (
    FIELDS, ROWS_PER_CHUNK, _json_bytes, _record, verify_archive,
)

DISPOSABLE_NAME = "stock_ci_restore"
LOCAL_HOSTS = frozenset(("localhost", "127.0.0.1"))
TEMP_TABLE = "pg_temp.twse_archive_restore_drill"

TEMP_CREATE = """
CREATE TEMP TABLE twse_archive_restore_drill (
    market text NOT NULL,
    stock_id text NOT NULL,
    trade_date date NOT NULL,
    open numeric, high numeric, low numeric, close numeric,
    volume bigint, turnover numeric, price_change numeric,
    transactions bigint, source text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    retrieved_at_iso text NOT NULL,
    PRIMARY KEY (market, stock_id, trade_date)
) ON COMMIT DROP
"""

COPY_SQL = """
COPY pg_temp.twse_archive_restore_drill (
 market, stock_id, trade_date, open, high, low, close, volume,
 turnover, price_change, transactions, source, retrieved_at, retrieved_at_iso
) FROM STDIN
"""

READ_BACK_SQL = """
SELECT market, stock_id, trade_date, open, high, low, close, volume,
turnover, price_change, transactions, source, retrieved_at, retrieved_at_iso
FROM pg_temp.twse_archive_restore_drill
ORDER BY trade_date, stock_id
"""


def validate_disposable_target(url: str) -> None:
    """Reject remote Neon, socket, implicit DB, tunnels with URL overrides."""
    if not isinstance(url, str) or not url:
        raise ValueError("Explicit disposable localhost PostgreSQL URL required")
    try:
        parsed = urlsplit(url)
        acceptable = (
            parsed.scheme in ("postgresql", "postgres")
            and parsed.hostname in LOCAL_HOSTS
            and parsed.port == 5432
            and parsed.username == DISPOSABLE_NAME
            and parsed.path == "/" + DISPOSABLE_NAME
            and not parsed.query and not parsed.fragment
            and parsed.password is not None
        )
    except ValueError as e:
        raise ValueError("Invalid local Postgres target address") from e
    if not acceptable:
        raise ValueError("Only disposable localhost stock_ci_restore database/role allowed")


def drill(archive: Path, *, hex_key: str, local_database_url: str) -> dict:
    validate_disposable_target(local_database_url)
    # Validate the entire encrypted file before starting any PG operation.
    authenticated = verify_archive(archive, hex_key=hex_key)

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(local_database_url, connect_timeout=10,
                         row_factory=dict_row) as conn:
        if conn.info.dbname != DISPOSABLE_NAME or conn.info.user != DISPOSABLE_NAME:
            raise ValueError("Target session identity is not disposable")
        with conn.transaction():
            with conn.cursor() as cur:
                identity = cur.execute(
                    "SELECT current_database() AS db, current_user AS role"
                ).fetchone()
                if (identity["db"] != DISPOSABLE_NAME
                        or identity["role"] != DISPOSABLE_NAME):
                    raise ValueError("Unexpected PostgreSQL database or role")
                cur.execute("SET LOCAL statement_timeout = '60000ms'")
                cur.execute(TEMP_CREATE)
                with cur.copy(COPY_SQL) as copy:
                    def consume(row):
                        values = tuple(row[k] for k in FIELDS)
                        copy.write_row(values + (row["retrieved_at"].isoformat(),))

                    # A tampered final footer rolls back all local TEMP writes.
                    receipt = verify_archive(
                        archive, hex_key=hex_key, on_verified_row=consume
                    )
                if (receipt["sample_rows"] != authenticated["sample_rows"]
                        or receipt["canonical_rows_sha256"]
                        != authenticated["canonical_rows_sha256"]):
                    raise ValueError("Encrypted archive changed since precheck")

                cur.execute(READ_BACK_SQL)
                digest = sha256()
                restored = 0
                while True:
                    fetched = cur.fetchmany(ROWS_PER_CHUNK)
                    if not fetched:
                        break
                    for entry in fetched:
                        raw_time = datetime.fromisoformat(entry["retrieved_at_iso"])
                        if (raw_time.tzinfo is None
                                or entry["retrieved_at"] != raw_time):
                            raise ValueError("PostgreSQL timestamptz did not roundtrip")
                        entry["retrieved_at"] = raw_time
                        exact = _record(entry)
                        digest.update(_json_bytes(exact) + b"\n")
                        restored += 1
                if (restored != authenticated["sample_rows"]
                    or digest.hexdigest() != authenticated["canonical_rows_sha256"]):
                    raise ValueError("PostgreSQL exact raw/source restore SHA mismatch")
        # ON COMMIT DROP: the disposable table must no longer exist.
        after = conn.execute(
            "SELECT to_regclass('pg_temp.twse_archive_restore_drill') AS table_name"
        ).fetchone()
        if after["table_name"] is not None:
            raise AssertionError("Disposable drill TEMP table survived commit")

    return {
        "schema_version": 1,
        "scope": "DISPOSABLE_LOCAL_POSTGRESQL_TEMP_RESTORE_DRILL_ONLY",
        "verified_rows_restored_into_temporary_table": restored,
        "exact_decimal_and_timezone_source_sha256_passed": True,
        "authenticated_archive_sha256": authenticated["canonical_rows_sha256"],
        "only_localhost_disposable_db_role_accepted": True,
        "postgres_temp_table_dropped_at_transaction_commit": True,
        "persistent_database_rows_written": 0,
        "neon_database_connected": False,
        "independent_real_private_backup_verified": False,
        "real_owner_archive_restoration_tested": False,
        "five_year_history_coverage_verified": False,
        "neon_deletion_or_migration_approved": False,
        "line_modified": False,
        "live_trading_approved": False,
        "paid_upgrade_requested": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local AES TWSE archive ephemeral Postgres restore drill")
    parser.add_argument("--archive", type=Path, required=True)
    opts = parser.parse_args()
    report = drill(
        opts.archive,
        hex_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
        local_database_url=os.environ.get("STOCK_CI_RESTORE_URL", ""),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
