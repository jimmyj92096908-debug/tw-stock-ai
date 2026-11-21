"""Disposable PostgreSQL17: latest TPEx score does NOT imply full backfill history."""
from datetime import date,timedelta
import os
import unittest
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from scripts import twse_240_release_gate as gate

URL=os.environ.get("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL,"No disposable local PostgreSQL")
class TPExGateFullHistoryIntegration(unittest.TestCase):
    def test_source_release_stays_blocked_until_all_dates_and_latest_scores_are_rebuilt(self):
        parsed=urlparse(URL)
        if parsed.hostname not in ("localhost","127.0.0.1") or parsed.path!="/stock_ci_test":
            raise RuntimeError("Refusing non-disposable database")
        with psycopg.connect(URL,row_factory=dict_row) as conn:
            conn.execute("""CREATE TABLE public.daily_prices(
              market text, stock_id text, trade_date date, close numeric,
              volume bigint, turnover numeric, source text,
              retrieved_at timestamptz,
              PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_adjusted_prices(
              market text, stock_id text, trade_date date, volume numeric,
              turnover numeric, share_adjustment_factor numeric,
              calculated_at timestamptz,
              PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_technicals(
              market text, stock_id text, trade_date date, ma240 numeric,
              calculated_at timestamptz,
              PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_smc(
              market text, stock_id text, trade_date date,
              calculated_at timestamptz,
              PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_composite_scores(
              market text, stock_id text, as_of_date date,
              total_score numeric, calculated_at timestamptz,
              PRIMARY KEY(market,stock_id,as_of_date))""")
            dates=[date(2026,8,29)+timedelta(days=i) for i in range(80)]
            with conn.cursor() as cur:
                cur.executemany("""INSERT INTO public.daily_prices
                  VALUES('tpex','6488',%s,100,1000,2000000,'TPEX_DATED_OTC_EW',
                         '2026-11-20 01:00:00+00')""",[(d,) for d in dates])
                for table in ("daily_adjusted_prices","daily_technicals","daily_smc"):
                    if table=="daily_adjusted_prices":
                        statement="""INSERT INTO public.daily_adjusted_prices
                            VALUES('tpex','6488',%s,1000,2000000,1,
                                   '2026-11-20 02:00:00+00')"""
                    elif table=="daily_technicals":
                        statement="""INSERT INTO public.daily_technicals
                            VALUES('tpex','6488',%s,NULL,'2026-11-20 02:00:00+00')"""
                    else:
                        statement="""INSERT INTO public.daily_smc
                            VALUES('tpex','6488',%s,'2026-11-20 02:00:00+00')"""
                    cur.executemany(statement,[(d,) for d in dates[20:]])
            conn.execute("""INSERT INTO public.daily_composite_scores
                VALUES('tpex','6488',%s,65,'2026-11-20 03:00:00+00')""",
                         (dates[-1],))
            conn.commit()

            first=conn.execute(gate.STATE_SQL).fetchone()
            self.assertEqual(first["tpex_eligible"],1)
            self.assertEqual(first["tpex_matched"],1)
            self.assertEqual(first["tpex_historical_factors_current"],0)

            with conn.cursor() as cur:
                for table in ("daily_adjusted_prices","daily_technicals","daily_smc"):
                    if table=="daily_adjusted_prices":
                        stmt="""INSERT INTO public.daily_adjusted_prices
                            VALUES('tpex','6488',%s,1000,2000000,1,
                                   '2026-11-20 02:00:00+00')"""
                    elif table=="daily_technicals":
                        stmt="""INSERT INTO public.daily_technicals
                            VALUES('tpex','6488',%s,NULL,'2026-11-20 02:00:00+00')"""
                    else:
                        stmt="""INSERT INTO public.daily_smc
                            VALUES('tpex','6488',%s,'2026-11-20 02:00:00+00')"""
                    cur.executemany(stmt,[(d,) for d in dates[:20]])
            conn.commit()
            second=conn.execute(gate.STATE_SQL).fetchone()
            self.assertEqual(second["tpex_historical_factors_current"],1)
            self.assertEqual(second["tpex_matched"],1)
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM daily_prices").fetchone()["n"],80)

            # A SINGLE older dated factor with an obsolete timestamp
            # invalidates full history even when all historical rows and the
            # very latest score exist and the maximum timestamp is fresh.
            conn.execute("""UPDATE public.daily_technicals
                 SET calculated_at='2026-11-19 01:00:00+00'
                 WHERE market='tpex' AND stock_id='6488' AND trade_date=%s""",
                 (dates[0],))
            conn.commit()
            stale=conn.execute(gate.STATE_SQL).fetchone()
            self.assertEqual(stale["tpex_matched"],1)
            self.assertEqual(stale["tpex_historical_factors_current"],0)
            conn.execute("""UPDATE public.daily_technicals
                 SET calculated_at='2026-11-20 02:00:00+00'
                 WHERE market='tpex' AND stock_id='6488' AND trade_date=%s""",
                 (dates[0],))
            conn.commit()
            self.assertEqual(conn.execute(gate.STATE_SQL).fetchone()[
                "tpex_historical_factors_current"],1)

            # Another independently sourced OLDER date invalidates the
            # previously complete calculation even if the last-date score is there.
            conn.execute("""INSERT INTO public.daily_prices
                VALUES('tpex','6488',%s,100,1000,2000000,'TPEX_DATED_OTC_EW',
                       '2026-11-21 01:00:00+00')""",(dates[0]-timedelta(days=1),))
            conn.commit()
            final=conn.execute(gate.STATE_SQL).fetchone()
            self.assertEqual(final["tpex_matched"],1)
            self.assertEqual(final["tpex_historical_factors_current"],0)
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM daily_prices").fetchone()["n"],81)
