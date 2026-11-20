"""PostgreSQL 17 acceptance: a SQL error rolls back only one symbol.

Uses an isolated local throwaway database, never Neon. Fake market observations
are created ONLY in this disposable PostgreSQL CI service.
"""
from __future__ import annotations

from datetime import date, timedelta
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import psycopg

from src import batch_indicator_catchup as ind


def verify_ci_db_url():
    url = os.getenv("STOCK_CI_POSTGRES_URL", "")
    if not url:
        return None
    parsed = urlsplit(url)
    if (parsed.scheme not in ("postgresql", "postgres")
            or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.path != "/stock_ci_test"):
        raise ValueError("Only localhost/stock_ci_test is allowed for this integration")
    return url


@unittest.skipUnless(os.getenv("STOCK_CI_POSTGRES_URL"), "Local disposable PostgreSQL only")
class IndicatorSavepointPostgresTests(unittest.TestCase):
    def test_sql_error_after_partial_upsert_rolls_back_bad_and_commits_good(self):
        url = verify_ci_db_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                for table in (
                    "daily_adjusted_prices", "daily_technicals", "daily_smc"
                ):
                    cur.execute(f"DROP TABLE IF EXISTS public.{table}")
                    cur.execute(f"""
                      CREATE TABLE public.{table} (
                        market TEXT NOT NULL,
                        stock_id TEXT NOT NULL,
                        trade_date DATE NOT NULL,
                        PRIMARY KEY (market,stock_id,trade_date)
                      )
                    """)
        days = [date(2026, 8, 1) + timedelta(days=i) for i in range(60)]

        def select(conn,market,limit):
            # Opens the outer transaction exactly like the production SELECT;
            # nested .transaction() must then use a PostgreSQL savepoint.
            conn.execute("SELECT 1")
            if market != "twse":
                return []
            return [
                {"market":"twse", "stock_id":sid,"close_days":60}
                for sid in ("1001","1002")
            ]

        def insert(conn, table, market, sid):
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO public.{table} (market,stock_id,trade_date) VALUES (%s,%s,%s)",
                    [(market,sid,day) for day in days]
                )
            return len(days)

        def adjusted(conn,market,sid):
            return insert(conn,"daily_adjusted_prices",market,sid)

        def technical(conn,market,sid):
            if sid == "1001":
                # A genuine PostgreSQL error aborts the active savepoint.
                conn.execute("SELECT 1/0")
                return 0
            return insert(conn,"daily_technicals",market,sid)

        def smc(conn,market,sid):
            return insert(conn,"daily_smc",market,sid)

        with (
            patch.dict(os.environ,{"STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),
            patch.object(ind,"select_candidates",side_effect=select),
            patch.object(ind,"build_adjusted_stock",side_effect=adjusted),
            patch.object(ind,"calculate_technical_stock",side_effect=technical),
            patch.object(ind,"calculate_smc_stock",side_effect=smc),
        ):
            with self.assertLogs(ind.LOGGER,level="ERROR"):
                output = ind.run(url,apply=True,per_market=2)

        self.assertEqual([item["stock_id"] for item in output],["1001","1002"])
        self.assertEqual([item["status"] for item in output],["failed","verified"])
        self.assertEqual(output[1]["technical_rows"],60)
        self.assertEqual(output[1]["smc_rows"],60)
        with psycopg.connect(url) as conn:
            for table in ("daily_adjusted_prices","daily_technicals","daily_smc"):
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT stock_id,count(*) FROM public.{table} GROUP BY stock_id ORDER BY stock_id"
                    )
                    self.assertEqual(cur.fetchall(),[("1002",60)])
