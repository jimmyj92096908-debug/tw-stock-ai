"""Read-only release preflight for optional, independently dated LINE chip scores.

Never changes Neon privileges, score rows, LINE settings, or sends a message.
Use a monitoring/admin connection ONLY to inspect existing grant metadata.
The LINE reader is not impersonated and is never granted rights here.
"""
from __future__ import annotations

import json
import os

import psycopg
from psycopg.rows import dict_row


ROLE = "line_stock_reader"
DB = "twstock"
CHIP_TABLE = "public.daily_chip_scores"
PRIVATE_TABLE = "public.line_messages"
REQUIRED_COLUMNS = (
    "as_of_date", "coverage_weight", "institutional_score", "margin_score",
    "market", "stock_id", "total_score",
)

GRANT_CHECK_SQL = """
SELECT
  current_database() AS connected_database,
  EXISTS (SELECT 1 FROM pg_roles WHERE rolname='line_stock_reader') AS reader_role_exists,
  EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname='line_stock_reader'
      AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolbypassrls
  ) AS reader_is_unprivileged_login,
  has_schema_privilege('line_stock_reader', 'public', 'USAGE') AS public_schema_usage,
  ARRAY(
    SELECT req.column_name
    FROM unnest(%s::text[]) AS req(column_name)
    LEFT JOIN information_schema.columns c
      ON c.table_schema='public'
     AND c.table_name='daily_chip_scores'
     AND c.column_name=req.column_name
    WHERE CASE
      WHEN c.column_name IS NULL THEN TRUE
      ELSE NOT has_column_privilege(
        'line_stock_reader','public.daily_chip_scores',req.column_name,'SELECT')
    END
    ORDER BY req.column_name
  ) AS missing_chip_select_columns,
  has_table_privilege(
    'line_stock_reader','public.daily_chip_scores','SELECT'
  ) AS chip_table_wide_select,
  ARRAY(
    SELECT c.column_name FROM information_schema.columns c
    WHERE c.table_schema='public' AND c.table_name='daily_chip_scores'
      AND NOT (c.column_name=ANY(%s::text[]))
      AND has_column_privilege(
        'line_stock_reader','public.daily_chip_scores',c.column_name,'SELECT'
      )
    ORDER BY c.column_name
  ) AS unexpected_chip_select_columns,
  (
    has_any_column_privilege('line_stock_reader','public.daily_chip_scores','INSERT')
    OR has_any_column_privilege('line_stock_reader','public.daily_chip_scores','UPDATE')
    OR has_table_privilege('line_stock_reader','public.daily_chip_scores','DELETE')
    OR has_table_privilege('line_stock_reader','public.daily_chip_scores','TRUNCATE')
  ) AS chip_write_access,
  has_any_column_privilege(
    'line_stock_reader','public.line_messages','INSERT'
  ) AS private_line_message_insert,
  has_any_column_privilege(
    'line_stock_reader','public.line_messages','SELECT'
  ) AS any_private_line_message_select,
  has_table_privilege(
    'line_stock_reader','public.line_messages','SELECT'
  ) AS whole_private_line_message_select
"""

LATEST_DATES_SQL = """
SELECT
 (SELECT MAX(trade_date) FROM public.daily_prices
   WHERE market='twse' AND stock_id='2330' AND close IS NOT NULL)
   AS price_date,
 (SELECT MAX(trade_date) FROM public.daily_technicals
   WHERE market='twse' AND stock_id='2330')
   AS technical_date,
 (SELECT MAX(as_of_date) FROM public.daily_composite_scores
   WHERE market='twse' AND stock_id='2330' AND total_score IS NOT NULL)
   AS composite_date,
 (SELECT MAX(as_of_date) FROM public.daily_chip_scores
   WHERE market='twse' AND stock_id='2330'
   AND total_score IS NOT NULL AND coverage_weight >= 0.50)
   AS independently_publishable_chip_date,
 (SELECT total_score FROM public.daily_chip_scores
   WHERE market='twse' AND stock_id='2330'
     AND total_score IS NOT NULL AND coverage_weight >= 0.50
   ORDER BY as_of_date DESC LIMIT 1)
   AS independently_publishable_chip_score,
 (SELECT coverage_weight FROM public.daily_chip_scores
   WHERE market='twse' AND stock_id='2330'
     AND total_score IS NOT NULL AND coverage_weight >= 0.50
   ORDER BY as_of_date DESC LIMIT 1)
   AS chip_source_coverage
"""


def _ymd(value):
    return value.isoformat() if value is not None else None


def inspect_readiness(conn) -> dict:
    """Inspect public stock metadata and privilege booleans, never user messages."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(GRANT_CHECK_SQL, (
            list(REQUIRED_COLUMNS), list(REQUIRED_COLUMNS)
        ))
        grants = cur.fetchone()
        if not grants:
            raise RuntimeError("Reader privilege metadata unavailable")
        if grants["connected_database"] != DB:
            raise RuntimeError("Refusing a connection outside the twstock database")
        cur.execute(LATEST_DATES_SQL)
        dates = cur.fetchone()
        if not dates:
            raise RuntimeError("Stock data metadata unavailable")

    missing = sorted(set(REQUIRED_COLUMNS) & set(
        grants["missing_chip_select_columns"] or []
    ))
    extra = sorted(grants["unexpected_chip_select_columns"] or [])
    reader_grants_ready = (
        bool(grants["reader_role_exists"])
        and bool(grants["reader_is_unprivileged_login"])
        and bool(grants["public_schema_usage"])
        and not missing
        and not extra
        and not grants["chip_table_wide_select"]
        and not grants["chip_write_access"]
    )
    private_scope_safe = not (
        grants["any_private_line_message_select"]
        or grants["whole_private_line_message_select"]
        or grants["private_line_message_insert"]
    )
    chip_date = _ymd(dates["independently_publishable_chip_date"])
    price_date = _ymd(dates["price_date"])
    composite_date = _ymd(dates["composite_date"])
    chip_valid_for_price = (
        chip_date is not None and price_date is not None and chip_date <= price_date
    )
    return {
        "assessment": (
            "optional_chip_read_query_preflight_pass"
            if reader_grants_ready and private_scope_safe and chip_valid_for_price
            else "blocked_or_inconclusive"
        ),
        "connected_database": DB,
        "stock": "twse/2330",
        "reader_role_exists": bool(grants["reader_role_exists"]),
        "reader_is_unprivileged_login": bool(grants["reader_is_unprivileged_login"]),
        "public_schema_usage": bool(grants["public_schema_usage"]),
        "missing_chip_select_columns": missing,
        "unexpected_chip_select_columns": extra,
        "chip_table_wide_select": bool(grants["chip_table_wide_select"]),
        "chip_write_access_detected": bool(grants["chip_write_access"]),
        "private_line_message_read_privilege_detected": bool(
            grants["any_private_line_message_select"]
            or grants["whole_private_line_message_select"]
        ),
        "private_line_message_insert_detected": bool(
            grants["private_line_message_insert"]
        ),
        "price_date": price_date,
        "technical_date": _ymd(dates["technical_date"]),
        "composite_date": composite_date,
        "standalone_chip_date": chip_date,
        "standalone_chip_score": (
            round(float(dates["independently_publishable_chip_score"]), 2)
            if dates["independently_publishable_chip_score"] is not None else None
        ),
        "standalone_source_coverage": (
            round(float(dates["chip_source_coverage"]), 2)
            if dates["chip_source_coverage"] is not None else None
        ),
        "chip_valid_for_price": chip_valid_for_price,
        "new_gateway_enabled_verified": False,
        "webhook_cutover_approved": False,
        "line_messages_sent": False,
        "production_database_modified": False,
    }


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required for read-only preflight")
    # Server-enforced read-only mode. No statements after this can write.
    with psycopg.connect(
        url, connect_timeout=15, options="-c default_transaction_read_only=on"
    ) as conn:
        report = inspect_readiness(conn)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
