"""Prove on disposable PG17 that latest-only rows do NOT satisfy 240-day factor completeness."""
from datetime import date,timedelta
import os
import unittest
from urllib.parse import urlparse

import psycopg

from scripts import twse_240_research_catchup as task

URL=os.environ.get("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL,"Disposable local PostgreSQL required")
class TWSEFullHistoricalIndicatorPostgresTests(unittest.TestCase):
    def test_latest_indicators_without_240day_history_are_not_complete(self):
        p=urlparse(URL)
        if p.hostname not in ("localhost","127.0.0.1") or p.path!="/stock_ci_test":
            raise RuntimeError("Refusing non-disposable database")
        with psycopg.connect(URL) as conn:
            conn.execute("""CREATE TABLE public.daily_prices (
              market text,stock_id text,trade_date date,close numeric,
              volume bigint,source text,
              PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_adjusted_prices (
              market text,stock_id text,trade_date date,
              PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_technicals (
              market text,stock_id text,trade_date date,ma240 numeric,
              PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_smc (
              market text,stock_id text,trade_date date,
              PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_composite_scores (
              market text,stock_id text,as_of_date date,total_score numeric,
              PRIMARY KEY(market,stock_id,as_of_date))""")
            dates=[date(2026,1,1)+timedelta(days=i) for i in range(240)]
            with conn.cursor() as cur:
                cur.executemany("""INSERT INTO daily_prices
                  VALUES('twse','2330',%s,100,1000,'TWSE_MI_INDEX_ALLBUT0999')""",
                  [(d,) for d in dates])
                for table in ("daily_adjusted_prices","daily_smc"):
                    cur.executemany(
                        f"INSERT INTO {table}(market,stock_id,trade_date) VALUES('twse','2330',%s)",
                        [(d,) for d in dates[103:]])
                cur.executemany("""INSERT INTO daily_technicals
                  VALUES('twse','2330',%s,NULL)""",
                  [(d,) for d in dates[103:]])
            conn.execute("""INSERT INTO daily_composite_scores
              VALUES('twse','2330',%s,60)""",(dates[-1],))
            conn.commit()

            initial=task.capture(URL)
            self.assertEqual(initial["verified_source_days"],240)
            self.assertEqual(initial["eligible"],1)
            self.assertEqual(initial["current_indicators"],0)
            self.assertEqual(initial["current_scores"],0)
            with conn.cursor() as cur:
                for table in ("daily_adjusted_prices","daily_smc"):
                    cur.executemany(
                        f"INSERT INTO {table}(market,stock_id,trade_date) VALUES('twse','2330',%s)",
                        [(d,) for d in dates[:103]])
                cur.executemany("""INSERT INTO daily_technicals
                  VALUES('twse','2330',%s,NULL)""",
                  [(d,) for d in dates[:103]])
            conn.execute("""UPDATE daily_technicals SET ma240=200
                WHERE market='twse' AND stock_id='2330' AND trade_date=%s""",
                (dates[-1],))
            conn.commit()

        completed=task.capture(URL)
        self.assertEqual(completed["current_indicators"],1)
        self.assertEqual(completed["current_scores"],1)
