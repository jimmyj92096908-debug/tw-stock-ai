"""Isolated real-PostgreSQL tests for price-history indicator eligibility."""
import os
import unittest
from datetime import date,timedelta
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from src.batch_indicator_catchup import select_candidates


URL=os.getenv("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL,"Requires disposable localhost stock_ci_test")
class IndicatorEligibilityPGTests(unittest.TestCase):
    def test_only_sufficient_fresh_verified_history_is_selected(self):
        parsed=urlparse(URL)
        if parsed.hostname not in ("localhost","127.0.0.1") or parsed.path!="/stock_ci_test":
            raise RuntimeError("Unsafe external database URL")
        with psycopg.connect(URL,row_factory=dict_row) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS public.daily_prices
                (market text,stock_id text,trade_date date,close numeric,
                 PRIMARY KEY (market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.daily_technicals
                (market text,stock_id text,trade_date date,
                 PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.daily_smc
                (market text,stock_id text,trade_date date,
                 PRIMARY KEY(market,stock_id,trade_date))""")
            # 60 *genuine-looking test sessions*; all synthetic and local only.
            start=date(2026,9,20)
            for i in range(60):
                d=start+timedelta(days=i)
                conn.execute("""INSERT INTO public.daily_prices (market,stock_id,trade_date,close)
                    VALUES('twse','2999',%s,100)
                    ON CONFLICT (market,stock_id,trade_date) DO NOTHING""",(d,))
            for i in range(59):
                d=start+timedelta(days=i)
                conn.execute("""INSERT INTO public.daily_prices (market,stock_id,trade_date,close)
                    VALUES('tpex','2998',%s,120)
                    ON CONFLICT (market,stock_id,trade_date) DO NOTHING""",(d,))
            eligible=select_candidates(conn,"twse",3)
            self.assertIn("2999",[r["stock_id"] for r in eligible])
            limited=select_candidates(conn,"tpex",3)
            self.assertNotIn("2998",[r["stock_id"] for r in limited])

            # If all 60 sessions are already covered by technical + SMC,
            # the same candidate must not be recomputed.
            for i in range(60):
                d=start+timedelta(days=i)
                conn.execute("""INSERT INTO public.daily_technicals VALUES('twse','2999',%s)
                    ON CONFLICT DO NOTHING""",(d,))
                conn.execute("""INSERT INTO public.daily_smc VALUES('twse','2999',%s)
                    ON CONFLICT DO NOTHING""",(d,))
            already=select_candidates(conn,"twse",3)
            self.assertNotIn("2999",[r["stock_id"] for r in already])
