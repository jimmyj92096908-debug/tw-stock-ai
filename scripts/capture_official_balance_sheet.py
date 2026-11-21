"""Bounded official TWSE/TPEx GENERAL balance snapshots, first observed only.

Two fixed source GETs, validated before a single Neon insert-only transaction.
No backdated history, raw price mutation, model training, LINE, or trades.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.official_balance_sheet_archive import SOURCES, parse_snapshot

MAX_BYTES_PER_SOURCE = 8_000_000
MAX_DATABASE_BYTES = 800_000_000
SIZE_SQL = "SELECT pg_database_size(current_database())::bigint AS bytes"
COUNT_SQL = "SELECT COUNT(*)::bigint AS n FROM public.official_balance_sheet_observations"
INSERT_SQL = """
INSERT INTO public.official_balance_sheet_observations
(market,stock_id,fiscal_year,fiscal_quarter,period_end,official_table_date,
 assets_thousands_ntd,liabilities_thousands_ntd,equity_thousands_ntd,
 current_assets_thousands_ntd,current_liabilities_thousands_ntd,
 parent_equity_thousands_ntd,accounting_identity_verified,
 first_observed_at,source_url,payload_sha256)
SELECT %(market)s::text,%(stock_id)s::varchar(6),
 %(fiscal_year)s::integer,%(fiscal_quarter)s::smallint,
 %(period_end)s::date,%(official_table_date)s::date,
 %(assets_thousands_ntd)s::numeric(24,3),
 %(liabilities_thousands_ntd)s::numeric(24,3),
 %(equity_thousands_ntd)s::numeric(24,3),
 %(current_assets_thousands_ntd)s::numeric(24,3),
 %(current_liabilities_thousands_ntd)s::numeric(24,3),
 %(parent_equity_thousands_ntd)s::numeric(24,3),
 %(accounting_identity_verified)s::boolean,
 %(first_observed_at)s::timestamptz,
 %(source_url)s::text,%(payload_sha256)s::char(64)
WHERE EXISTS (
 SELECT 1 FROM public.stock_master sm
 WHERE sm.market=%(market)s::text
   AND sm.stock_id=%(stock_id)s::varchar(6)
)
ON CONFLICT (market,stock_id,period_end,payload_sha256) DO NOTHING
"""


def fetch_official(market, *, session=None, observed_at=None):
    if market not in SOURCES:
        raise ValueError("Only two explicit official source hosts allowed")
    response = (session or requests).get(
        SOURCES[market],
        headers={"Accept": "application/json",
                 "User-Agent": "tw-stock-ai-balance-first-seen-archive/1.0"},
        timeout=(10, 30), allow_redirects=False)
    received = urlparse(response.url)
    expected = urlparse(SOURCES[market])
    if response.status_code != 200 or received.scheme != "https" or        received.hostname != expected.hostname:
        raise RuntimeError("Balance-sheet source not verified or redirect forbidden")
    if len(response.content) > MAX_BYTES_PER_SOURCE:
        raise RuntimeError("Official balance-sheet source exceeded 8MB")
    try:
        rows = response.json()
    except ValueError as ex:
        raise RuntimeError("Official balance-sheet source is not JSON") from ex
    stamp = observed_at if observed_at is not None else datetime.now(ZoneInfo("Asia/Taipei"))
    return parse_snapshot(market, rows, observed_at=stamp)


def _size(cur):
    cur.execute(SIZE_SQL)
    value = cur.fetchone()["bytes"]
    if type(value) is not int or not 0 < value < MAX_DATABASE_BYTES:
        raise RuntimeError("Neon Free 800MB official first-seen archive stop line")
    return value


def capture(url, *, apply=False, report_path=None, session=None, observed_at=None):
    if apply and os.getenv("STOCK_OFFICIAL_BALANCE_WRITE") != "yes":
        raise PermissionError("Owner-approved official balance-sheet write gate missing")
    if apply and observed_at is not None:
        raise ValueError("Cannot supply historical first-observed timestamp on live write")
    if not apply and observed_at is not None:
        rows = {m: fetch_official(m, session=session, observed_at=observed_at)
                for m in SOURCES}
    else:
        rows = {m: fetch_official(m, session=session) for m in SOURCES}
    report = {
        "schema_version": 1,
        "source": "TWSE_TPEX_GENERAL_INDUSTRY_QUARTERLY_BALANCE_FIRST_SEEN",
        "validated_rows": {m: len(v) for m, v in rows.items()},
        "accounting_identity_verified": {
            m: sum(bool(x["accounting_identity_verified"]) for x in v)
            for m, v in rows.items()
        },
        "first_observed_after_completed_http": observed_at is None,
        "issuer_actual_publication_timestamp_known": False,
        "historical_backdating_prohibited": True,
        "cashflow_coverage_approved": False,
        "rouses_production_model": False,
        "new_paid_services": False,
        "line_messages_sent": False,
        "live_trading_enabled": False,
        "inserted": 0, "persisted": False,
    }
    if apply:
        if not url:
            raise ValueError("Existing protected Neon connection required")
        with psycopg.connect(url, connect_timeout=15, autocommit=True,
                             row_factory=dict_row) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout='30000ms'")
                    before = _size(cur)
                    cur.execute((ROOT / "sql/official_balance_sheet_observation_schema.sql")
                                .read_text(encoding="utf-8"))
                    cur.execute(COUNT_SQL)
                    n0 = cur.fetchone()["n"]
                    for market in SOURCES:
                        cur.executemany(INSERT_SQL, rows[market])
                    cur.execute(COUNT_SQL)
                    n1 = cur.fetchone()["n"]
                    if n1 < n0 or n1 - n0 > sum(map(len, rows.values())):
                        raise RuntimeError("Impossible append-only official balance count delta")
                    after = _size(cur)
                    report.update({
                        "inserted": n1 - n0, "persisted": True,
                        "database_before_bytes": before,
                        "database_after_bytes": after,
                    })
    if report_path:
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description="Official latest-quarter balance first-seen; no model writes")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", type=Path,
                    default=Path("balance-sheet-first-seen-evidence.json"))
    args = ap.parse_args()
    print(json.dumps(capture(os.getenv("DATABASE_URL", ""), apply=args.apply,
                             report_path=args.report), ensure_ascii=False))


if __name__ == "__main__":
    main()
