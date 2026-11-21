"""Disposable Postgres validation: source-specific derived volume vs immutable raw."""
import os
import unittest
from decimal import Decimal
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from src import build_adjusted_prices as adjusted

URL = os.environ.get("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL, "Isolated localhost PostgreSQL fixture required")
class TPExDerivedVolumePostgresTests(unittest.TestCase):
    def test_only_adjusted_tpex_bars_receive_legacy_volume_multiplier(self):
        parsed = urlparse(URL)
        if parsed.hostname not in ("127.0.0.1", "localhost") or parsed.path != "/stock_ci_test":
            raise RuntimeError("Refusing non-disposable PostgreSQL target")
        with psycopg.connect(URL, row_factory=dict_row) as conn:
            conn.execute("""CREATE TABLE public.daily_prices(
              market text NOT NULL,stock_id varchar(6) NOT NULL,trade_date date NOT NULL,
              open numeric(18,4),high numeric(18,4),low numeric(18,4),close numeric(18,4),
              volume bigint,turnover numeric(24,2),price_change numeric(18,4),
              transactions bigint,source text,
              PRIMARY KEY(market,stock_id,trade_date)
            )""")
            conn.execute("""CREATE TABLE public.daily_adjusted_prices(
              market text NOT NULL,stock_id varchar(6) NOT NULL,trade_date date NOT NULL,
              open numeric(18,4),high numeric(18,4),low numeric(18,4),close numeric(18,4),
              volume numeric(24,4),turnover numeric(24,2),price_change numeric(18,4),
              transactions bigint,price_adjustment_factor numeric(18,6),
              share_adjustment_factor numeric(18,6),adjustment_status text,
              calculated_at timestamptz DEFAULT now(),
              PRIMARY KEY(market,stock_id,trade_date)
            )""")
            conn.execute("""CREATE TABLE public.corporate_actions(
              market text NOT NULL,stock_id varchar(6) NOT NULL,ex_date date NOT NULL,
              action_type text,price_factor numeric,share_factor numeric,
              cash_amount numeric,stock_amount numeric,verified boolean DEFAULT false
            )""")
            with conn.cursor() as cursor:
                cursor.executemany("""INSERT INTO public.daily_prices
                  (market,stock_id,trade_date,open,high,low,close,volume,turnover,source)
                  VALUES('tpex','6488',%s,100,110,90,105,%s,%s,%s)""",[
                ("2026-11-18",9367,5047518,"TPEX_TRADING_STOCK"),
                ("2026-11-19",9738,4906510,"TPEX_TRADING_STOCK"),
                ("2026-11-20",7958762,3920000000,"TPEX_DAILY_CLOSE_OPENAPI"),
            ])
            self.assertEqual(adjusted.build(conn,"tpex","6488"),3)
            original=conn.execute("""SELECT trade_date,volume,turnover FROM daily_prices
              ORDER BY trade_date""").fetchall()
            self.assertEqual([x["volume"] for x in original],
                             [9367,9738,7958762])
            transformed=conn.execute("""SELECT trade_date,volume,turnover FROM daily_adjusted_prices
              ORDER BY trade_date""").fetchall()
            self.assertEqual([x["volume"] for x in transformed],
                             [Decimal("9367000.0000"),Decimal("9738000.0000"),
                              Decimal("7958762.0000")])
            self.assertEqual(transformed[0]["turnover"],
                             Decimal("5047518000.00"))
            self.assertEqual(transformed[1]["turnover"],
                             Decimal("4906510000.00"))
            # Idempotent derived rebuild leaves raw table untouched.
            self.assertEqual(adjusted.build(conn,"tpex","6488"),3)
            self.assertEqual(
                conn.execute("SELECT volume FROM daily_prices WHERE trade_date='2026-11-18'").fetchone()["volume"],
                9367)
