"""Disposable PG17: official monthly TPEx sources count, not imaginary EW rows.

This test proves a legacy official tradingStock-only ticker can be certified
after authentic factor recalculation while the independently dated whole-
market TPEx EW-session count remains strictly EW-only.
"""
from datetime import date,timedelta
import os
import unittest
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from scripts import twse_240_release_gate as gate
from scripts import tpex_stale_factor_refresh as repair

URL=os.environ.get("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL,"Disposable local PostgreSQL17 required")
class TPExAlternateOfficialSourcePostgresTests(unittest.TestCase):
    def test_monthly_official_source_is_not_unverifiable_or_a_fictitious_ew_session(self):
        parsed=urlparse(URL)
        if parsed.hostname not in ("localhost","127.0.0.1") or parsed.path!="/stock_ci_test":
            raise RuntimeError("Refusing non-disposable Postgres database")
        with psycopg.connect(URL,row_factory=dict_row) as conn:
            conn.execute("""CREATE TABLE public.twse_history_day_progress (
                trade_date date PRIMARY KEY,status text NOT NULL)""")
            conn.execute("""CREATE TABLE public.daily_prices(
                market text, stock_id text, trade_date date, close numeric,
                volume bigint, turnover numeric, source text,
                retrieved_at timestamptz,
                PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_adjusted_prices(
                market text,stock_id text,trade_date date,volume numeric,
                turnover numeric,share_adjustment_factor numeric,
                calculated_at timestamptz,
                PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_technicals(
                market text,stock_id text,trade_date date,ma240 numeric,
                calculated_at timestamptz,
                PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_smc(
                market text,stock_id text,trade_date date,calculated_at timestamptz,
                PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_composite_scores(
                market text,stock_id text,as_of_date date,total_score numeric,
                calculated_at timestamptz,
                PRIMARY KEY(market,stock_id,as_of_date))""")
            dates=[date(2026,9,2)+timedelta(days=i) for i in range(80)]
            self.assertEqual(dates[-1],date(2026,11,20))
            stocks=[
                ("6488","TPEX_DATED_OTC_EW",1000,2000000),
                ("1240","TPEX_TRADING_STOCK",1,2000),
            ]
            with conn.cursor() as cur:
                for sid,source,raw_v,raw_turnover in stocks:
                    cur.executemany("""INSERT INTO public.daily_prices VALUES
                        ('tpex',%s,%s,100,%s,%s,%s,
                        '2026-11-20 01:00:00+00')""",
                        [(sid,d,raw_v,raw_turnover,source) for d in dates])
                    cur.executemany("""INSERT INTO public.daily_adjusted_prices
                        VALUES('tpex',%s,%s,%s,%s,1,
                        '2026-11-20 02:00:00+00')""",
                        [(sid,d,raw_v*(1000 if source=="TPEX_TRADING_STOCK" else 1),
                          raw_turnover*(1000 if source=="TPEX_TRADING_STOCK" else 1))
                         for d in dates])
                    cur.executemany("""INSERT INTO public.daily_technicals
                        VALUES('tpex',%s,%s,NULL,
                        '2026-11-20 02:00:00+00')""",
                        [(sid,d) for d in dates])
                    cur.executemany("""INSERT INTO public.daily_smc
                        VALUES('tpex',%s,%s,
                        '2026-11-20 02:00:00+00')""",
                        [(sid,d) for d in dates])
                    cur.execute("""INSERT INTO public.daily_composite_scores
                        VALUES('tpex',%s,%s,55,'2026-11-20 03:00:00+00')""",
                        (sid,dates[-1]))
            conn.commit()
            good=conn.execute(gate.STATE_SQL).fetchone()
            self.assertEqual(good["tpex_source_days"],80)
            self.assertEqual(good["tpex_eligible"],2)
            self.assertEqual(good["tpex_matched"],2)
            self.assertEqual(good["tpex_historical_factors_current"],2)
            self.assertEqual(repair.choose(conn),[])

            # The legacy official tradingStock feed was retrieved later;
            # its older factors and previously computed score are now stale.
            conn.execute("""UPDATE public.daily_prices
                SET retrieved_at='2026-11-21 01:00:00+00'
                WHERE stock_id='1240' AND trade_date=%s""",(dates[0],))
            conn.commit()
            stale=conn.execute(gate.STATE_SQL).fetchone()
            self.assertEqual(stale["tpex_source_days"],80)
            self.assertEqual(stale["tpex_matched"],2)
            self.assertEqual(stale["tpex_historical_factors_current"],1)
            missing=repair.choose(conn)
            self.assertEqual([x["stock_id"] for x in missing],["1240"])
            with self.assertRaisesRegex(RuntimeError,"missing or stale"):
                repair.verify_derived(conn,missing[0])

            for table in ("daily_adjusted_prices","daily_technicals","daily_smc"):
                conn.execute(f"""UPDATE public.{table}
                    SET calculated_at='2026-11-21 02:00:00+00'
                    WHERE market='tpex' AND stock_id='1240'""")
            conn.execute("""UPDATE public.daily_composite_scores
                SET calculated_at='2026-11-21 03:00:00+00'
                WHERE market='tpex' AND stock_id='1240'""")
            conn.commit()
            repaired=conn.execute(gate.STATE_SQL).fetchone()
            self.assertEqual(repaired["tpex_source_days"],80)
            self.assertEqual(repaired["tpex_historical_factors_current"],2)
            self.assertEqual(repair.choose(conn),[])
            self.assertEqual(conn.execute(
                "SELECT count(*)::int n FROM daily_prices").fetchone()["n"],160)


if __name__=="__main__":
    unittest.main()
