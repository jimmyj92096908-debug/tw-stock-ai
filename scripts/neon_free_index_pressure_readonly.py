"""Tiny, strictly read-only Neon Free table/index footprint audit.

This script is not a free-storage repair, importer, data-vacuum, or model.
It reads pg_catalog/statistics only, reports the 650 MB conservative
research-abstain condition and keeps all historical backfills BLOCKED.
An index scan counter (including zero) cannot authorize an index drop.
No AES, historical OHLCV rows, issuer IDs, LINE or billing API accessed.

Owner-private output only, exclusive create; CI uses synthetic rows only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os

import psycopg
from psycopg.rows import dict_row

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.neon_free_meter_guard import DB_WARN_BYTES, DB_STOP_BYTES

SCOPE = "NEON_FREE_FIVE_YEAR_HISTORY_TABLE_INDEX_PRESSURE_READONLY_BLOCKED"
TABLES = (
    "daily_prices", "daily_adjusted_prices", "daily_technicals",
    "daily_smc", "daily_composite_scores",
)
MAX_INDEXES = 40
MAX_OUTPUT_BYTES = 24000
MAX_STATEMENT_MS = 6000
STAGES = frozenset((
    "PRIVATE_OUTPUT", "READONLY_CATALOG", "METADATA_VALIDATION",
    "PRIVATE_REPORT_WRITE", "UNCLASSIFIED",
))

HEAD_SQL = """
SELECT pg_database_size(current_database())::bigint AS database_bytes,
       clock_timestamp() AS observed_at,
       (SELECT stats_reset FROM pg_stat_database
         WHERE datname=current_database()) AS index_stat_reset_at
"""
TABLE_SQL = """
SELECT c.relname AS table_name,
       pg_total_relation_size(c.oid)::bigint AS table_total_bytes,
       pg_relation_size(c.oid)::bigint AS heap_bytes,
       pg_indexes_size(c.oid)::bigint AS index_bytes,
       coalesce(s.n_live_tup, 0)::bigint AS estimated_live_rows,
       coalesce(s.n_dead_tup, 0)::bigint AS estimated_dead_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
WHERE n.nspname='public' AND c.relkind='r'
 AND c.relname = ANY(%s::text[])
ORDER BY c.relname
"""
INDEX_SQL = """
SELECT c.relname AS table_name,
       i.indexrelname AS index_name,
       pg_relation_size(i.indexrelid)::bigint AS index_bytes,
       coalesce(i.idx_scan, 0)::bigint AS index_scans
FROM pg_stat_user_indexes i
JOIN pg_class c ON c.oid=i.relid
WHERE c.relnamespace='public'::regnamespace
 AND c.relkind='r' AND c.relname = ANY(%s::text[])
ORDER BY c.relname,i.indexrelname
LIMIT 41
"""


class AuditError(ValueError):
    def __init__(self, stage):
        self.stage = stage if stage in STAGES else "UNCLASSIFIED"
        super().__init__(self.stage)


def _phase(stage, fn, *args, **kwargs):
    if stage not in STAGES:
        raise AuditError("UNCLASSIFIED")
    try:
        return fn(*args, **kwargs)
    except AuditError:
        raise
    except Exception:
        raise AuditError(stage) from None


def safe_error(stage):
    if stage not in STAGES:
        stage = "UNCLASSIFIED"
    return (
        "Neon Free owner-only index audit FAILED safely; diagnostic_stage="
        + stage + "; no database URI, stock data, token or local path disclosed"
    )


def _nonneg(value, label, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError("Unverified numeric catalog field: " + label)
    return value


def _timestamp(value, label, *, allow_null=False):
    if allow_null and value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Unverified catalog observation time: " + label)
    return value.astimezone(timezone.utc).isoformat()


def assess(meta, table_rows, index_rows):
    """No inference of storage reclaimability or Neon billable allowance."""
    if not isinstance(meta, dict):
        raise ValueError("Missing PostgreSQL database size evidence")
    total = _nonneg(meta.get("database_bytes"), "database_bytes", positive=True)
    observed = _timestamp(meta.get("observed_at"), "observed_at")
    reset = _timestamp(
        meta.get("index_stat_reset_at"), "index_stat_reset_at",
        allow_null=True,
    )
    if not isinstance(table_rows, list) or len(table_rows) != len(TABLES):
        raise ValueError("Five known large public table receipts required")
    if not isinstance(index_rows, list) or not 5 <= len(index_rows) <= MAX_INDEXES:
        raise ValueError("Bounded all-index receipt required")
    table_sizes = {}
    cumulative_bytes = 0
    for row in table_rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed table catalog row")
        name = row.get("table_name")
        if name not in TABLES or name in table_sizes:
            raise ValueError("Missing or unexpected public relation")
        rel = _nonneg(row.get("table_total_bytes"), "table_total_bytes", positive=True)
        heap = _nonneg(row.get("heap_bytes"), "heap_bytes", positive=True)
        indices = _nonneg(row.get("index_bytes"), "index_bytes")
        nlive = _nonneg(row.get("estimated_live_rows"), "estimated_live_rows")
        ndead = _nonneg(row.get("estimated_dead_rows"), "estimated_dead_rows")
        if rel < heap + indices or indices >= rel:
            raise ValueError("Impossible table/index size accounting")
        table_sizes[name] = {
            "table_total_bytes": rel,
            "table_heap_bytes": heap,
            "table_index_bytes": indices,
            "approximate_live_rows_not_source_coverage": nlive,
            "approximate_dead_rows_not_reclaimable_bytes": ndead,
        }
        cumulative_bytes += rel
    if set(table_sizes) != set(TABLES) or cumulative_bytes > total:
        raise ValueError("Incomplete or larger-than-database physical table totals")

    indices = []
    seen_index_names = set()
    sum_by_table = {name: 0 for name in TABLES}
    for row in index_rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed index catalog row")
        table = row.get("table_name")
        name = row.get("index_name")
        if table not in TABLES or not isinstance(name, str) or not name:
            raise ValueError("Unexpected index relation or table")
        if name in seen_index_names:
            raise ValueError("Repeated index name")
        seen_index_names.add(name)
        bytes_used = _nonneg(row.get("index_bytes"), "index_bytes", positive=True)
        scans = _nonneg(row.get("index_scans"), "index_scans")
        sum_by_table[table] += bytes_used
        indices.append({
            "table_name": table, "index_name": name,
            "index_bytes": bytes_used,
            "index_scan_count_since_stats_reset_not_lifetime_use": scans,
            "zero_scans_does_not_authorize_deletion": True,
        })
    if not all(sum_by_table.values()):
        raise ValueError("One large relation has no cataloged indexes")
    # pg_indexes_size() and individual pg_relation_size(indexrelid)
    # are collected in one read-only repeatable-read snapshot. Require
    # equal sums; never use a partial LIMIT result to recommend drops.
    for name in TABLES:
        if sum_by_table[name] != table_sizes[name]["table_index_bytes"]:
            raise ValueError("Some index footprint evidence was not collected")

    pressure = (
        "ABSTAIN_STORAGE_WARN"
        if total >= DB_WARN_BYTES else
        "BELOW_WARN_READONLY_OBSERVATION_ONLY"
    )
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "observed_at_utc": observed,
        "index_scan_statistics_reset_at_utc_or_unknown": reset,
        "database_bytes_from_pg_database_size": total,
        "conservative_free_workflow_warning_bytes": DB_WARN_BYTES,
        "conservative_production_hard_stop_bytes": DB_STOP_BYTES,
        "database_bytes_below_hard_stop": total < DB_STOP_BYTES,
        "storage_workflow_preflight_status": pressure,
        "existing_650mb_free_gate_blocks_expensive_research": (
            total >= DB_WARN_BYTES),
        "major_table_total_bytes": cumulative_bytes,
        "major_table_count": len(table_sizes),
        "all_inspected_index_count": len(indices),
        "tables": table_sizes,
        "indexes": indices,
        "source_price_rows_or_private_aes_read": 0,
        "index_scan_stats_prove_index_safe_to_drop": False,
        "indexes_approved_to_remove_or_rebuild": [],
        "dead_tuple_counts_prove_reclaimable_disk_bytes": False,
        "production_price_backfill_approved": False,
        "production_index_ddl_approved": False,
        "neon_billing_quota_verified_by_this_script": False,
        "historical_stock_point_in_time_universe_verified": False,
        "owner_aes_and_neon_five_year_per_stock_coverage_completed_here": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "additional_paid_services_used": False,
    }


def capture(*, database_url):
    if not database_url:
        raise ValueError("Protected owner Neon URL required")
    with psycopg.connect(
        database_url, row_factory=dict_row, connect_timeout=10,
        options="-c default_transaction_read_only=on",
        autocommit=True,
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                cursor.execute(
                    "SET LOCAL statement_timeout = '6000ms'"
                )
                cursor.execute(HEAD_SQL)
                meta = dict(cursor.fetchone())
                cursor.execute(TABLE_SQL, (list(TABLES),))
                tables = [dict(x) for x in cursor.fetchall()]
                cursor.execute(INDEX_SQL, (list(TABLES),))
                indexes = [dict(x) for x in cursor.fetchall()]
                return assess(meta, tables, indexes)


def run_owner(*, database_url, out):
    target = _phase("PRIVATE_OUTPUT", _private_file, out, should_exist=False)
    report = _phase("READONLY_CATALOG", capture, database_url=database_url)
    encoded = _phase(
        "METADATA_VALIDATION",
        lambda: json.dumps(
            report, ensure_ascii=False, indent=2, allow_nan=False
        ) + "\n",
    )
    if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise AuditError("METADATA_VALIDATION")
    def write():
        with target.open("x", encoding="utf-8") as fd:
            fd.write(encoded)
    _phase("PRIVATE_REPORT_WRITE", write)
    print(json.dumps({
        "status": "OWNER_NEON_FREE_INDEX_PRESSURE_READONLY_AUDIT_PASS",
        "database_bytes": report["database_bytes_from_pg_database_size"],
        "workflow_storage_gate": report["storage_workflow_preflight_status"],
        "inspected_tables": report["major_table_count"],
        "inspected_indexes": report["all_inspected_index_count"],
        "backfill_approved": False,
        "index_ddl_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0, "line_messages_sent": 0,
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        run_owner(database_url=os.environ.get("DATABASE_URL", ""), out=args.out)
    except AuditError as exc:
        raise SystemExit(safe_error(exc.stage)) from None
    except Exception:
        raise SystemExit(safe_error("UNCLASSIFIED")) from None


if __name__ == "__main__":
    main()
