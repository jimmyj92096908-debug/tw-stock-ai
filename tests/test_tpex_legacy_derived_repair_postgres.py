"""Disposable PG17 source-unit acceptance with never-changing raw TPEx prices."""
import os
import unittest
from decimal import Decimal
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from scripts import tpex_legacy_derived_repair as repair

URL = os.environ.get("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL, "Local disposable PostgreSQL required")
class LegacyDerivedAuditIntegration(TestCase if False else unittest.TestCase):
    def test_legacy_volume_checks_fail_closed_on_bad_units(self):
        parsed = urlparse(URL)
        if parsed.hostname not in ("127.0.0.1","localhost") or parsed.path != "/stock_ci_test":
            raise RuntimeError("Refusing non-disposable database")
        with psycopg.connect(URL,row_factory=dict_row) as conn:
            conn.execute("""CREATE TABLE public.daily_prices(
                market text NOT NULL,stock_id text NOT NULL,trade_date date NOT NULL,
                close numeric,volume bigint,turnover numeric,source text,
                PRIMARY KEY(market,stock_id,trade_date)
            )""")
            conn.execute("""CREATE TABLE public.daily_adjusted_prices(
                market text NOT NULL,stock_id text NOT NULL,trade_date date NOT NULL,
                volume numeric,turnover numeric,share_adjustment_factor numeric,
                PRIMARY KEY(market,stock_id,trade_date)
            )""")
            conn.execute("""CREATE TABLE public.daily_technicals(
                market text NOT NULL,stock_id text NOT NULL,trade_date date NOT NULL,
                PRIMARY KEY(market,stock_id,trade_date)
            )""")
            conn.execute("""CREATE TABLE public.daily_smc(
                market text NOT NULL,stock_id text NOT NULL,trade_date date NOT NULL,
                PRIMARY KEY(market,stock_id,trade_date)
            )""")
            conn.execute("""INSERT INTO daily_prices
                (market,stock_id,trade_date,close,volume,turnover,source)
                VALUES('tpex','6488','2026-11-19',490,9738,4906510,'TPEX_TRADING_STOCK')""")
            conn.execute("""INSERT INTO daily_adjusted_prices
                (market,stock_id,trade_date,volume,turnover,share_adjustment_factor)
                VALUES('tpex','6488','2026-11-19',9738000,4906510000,1)""")
            conn.execute("""INSERT INTO daily_technicals
                VALUES('tpex','6488','2026-11-19')""")
            conn.execute("""INSERT INTO daily_smc
                VALUES('tpex','6488','2026-11-19')""")
            stock={"stock_id":"6488","last_price":"2026-11-19"}
            proof=repair.verify_derived(conn,stock)
            self.assertEqual(proof,{"legacy_rows":1,"bad_volume":0,"bad_turnover":0})
            raw_before=conn.execute("SELECT volume,turnover FROM daily_prices").fetchone()
            self.assertEqual(raw_before,{"volume":9738,"turnover":Decimal("4906510")})

            conn.execute("""UPDATE daily_adjusted_prices
                SET volume=9738 WHERE market='tpex' AND stock_id='6488'""")
            with self.assertRaisesRegex(RuntimeError,"mismatch"):
                repair.verify_derived(conn,stock)
            raw_after=conn.execute("SELECT volume,turnover FROM daily_prices").fetchone()
            self.assertEqual(raw_after,raw_before)
