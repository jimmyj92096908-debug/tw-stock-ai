"""Real isolated PostgreSQL17: backfilled old dates invalidate latest score."""
from __future__ import annotations

from datetime import date,timedelta
import os
from urllib.parse import urlparse
import unittest

import psycopg
from psycopg.rows import dict_row

from scripts import tpex_stale_factor_refresh as refresh

URL=os.environ.get("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL,"Disposable localhost PostgreSQL required")
class TPExStaleFactorPostgresTests(unittest.TestCase):
    def test_older_newly_ingested_prices_force_historical_rebuild_and_score_stamp(self):
        parsed=urlparse(URL)
        if parsed.hostname not in ("localhost","127.0.0.1") or parsed.path!="/stock_ci_test":
            raise RuntimeError("Refusing all production database targets")
        with psycopg.connect(URL,row_factory=dict_row) as conn:
            conn.execute("""CREATE TABLE public.daily_prices (
              market text,stock_id text,trade_date date,close numeric,
              volume bigint,turnover numeric,source text,retrieved_at timestamptz,
              PRIMARY KEY(market,stock_id,trade_date))""")
            for table in ("daily_adjusted_prices","daily_technicals","daily_smc"):
                conn.execute(f"""CREATE TABLE public.{table} (
                  market text,stock_id text,trade_date date,
                  calculated_at timestamptz,
                  PRIMARY KEY(market,stock_id,trade_date))""")
            conn.execute("""CREATE TABLE public.daily_composite_scores (
              market text,stock_id text,as_of_date date,total_score numeric,
              calculated_at timestamptz,
              PRIMARY KEY(market,stock_id,as_of_date))""")
            dates=[date(2026,9,17)+timedelta(days=i) for i in range(65)]
            with conn.cursor() as cur:
                cur.executemany("""INSERT INTO public.daily_prices VALUES
                 ('tpex','6488',%s,100,1000,1000000,'TPEX_DATED_OTC_EW',
                  '2026-11-20 01:00:00+00')""",[(d,) for d in dates])
                for table in ("daily_adjusted_prices","daily_technicals","daily_smc"):
                    cur.executemany(f"""INSERT INTO public.{table}
                     VALUES('tpex','6488',%s,'2026-11-20 00:00:00+00')""",
                     [(d,) for d in dates[10:]])
            conn.execute("""INSERT INTO public.daily_composite_scores VALUES
                ('tpex','6488',%s,65,'2026-11-20 00:00:00+00')""",(dates[-1],))
            conn.commit()

            # Latest technical/SMC and score ALREADY EXIST, but 10 old
            # dated-source sessions were backfilled after factor calculation.
            before=refresh.choose(conn)
            self.assertEqual([x["stock_id"] for x in before],["6488"])
            self.assertEqual(before[0]["price_rows"],65)
            self.assertEqual(before[0]["technical_rows"],55)
            with self.assertRaisesRegex(RuntimeError,"missing or stale"):
                refresh.verify_derived(conn,before[0])
            with conn.cursor() as cur:
                for table in ("daily_adjusted_prices","daily_technicals","daily_smc"):
                    cur.executemany(f"""INSERT INTO public.{table}
                       VALUES('tpex','6488',%s,'2026-11-20 02:00:00+00')""",
                       [(d,) for d in dates[:10]])
                    cur.execute(f"""UPDATE public.{table}
                       SET calculated_at='2026-11-20 02:00:00+00'
                       WHERE stock_id='6488'""")
            conn.commit()
            checked=refresh.verify_derived(conn,before[0])
            self.assertEqual(checked["missing_derived_days"],0)
            self.assertEqual(checked["stale_derived_days"],0)
            self.assertEqual(len(refresh.choose(conn)),1)

            # Numeric score unchanged; explicitly record a REAL successful
            # post-factor audit, not a fake score improvement.
            with conn.cursor() as cur:
                cur.execute(refresh.STAMP_VERIFIED_SCORE_SQL,("6488",dates[-1]))
            conn.commit()
            refresh.verify_latest_score(conn,before[0])
            self.assertEqual(refresh.choose(conn),[])
            raw=conn.execute("SELECT count(*)::int n FROM daily_prices").fetchone()
            self.assertEqual(raw["n"],65)

            # A single STALE older factor date must be detected even though
            # the MAX calculated_at and the latest-day score remain fresh.
            conn.execute("""UPDATE public.daily_technicals
                SET calculated_at='2026-11-19 12:00:00+00'
                WHERE market='tpex' AND stock_id='6488' AND trade_date=%s""",
                (dates[0],))
            conn.commit()
            self.assertEqual(len(refresh.choose(conn)),1)
            with self.assertRaisesRegex(RuntimeError,"missing or stale"):
                refresh.verify_derived(conn,before[0])
            conn.execute("""UPDATE public.daily_technicals
                SET calculated_at='2026-11-20 02:00:00+00'
                WHERE market='tpex' AND stock_id='6488' AND trade_date=%s""",
                (dates[0],))
            conn.commit()
            self.assertEqual(refresh.choose(conn),[])

            # PostgreSQL MIN(calculated_at) ignores NULL: even one historical
            # NULL timestamp must still block model-factor completion.
            conn.execute("""UPDATE public.daily_smc
                SET calculated_at=NULL
                WHERE market='tpex' AND stock_id='6488' AND trade_date=%s""",
                (dates[0],))
            conn.commit()
            self.assertEqual(len(refresh.choose(conn)),1)
            with self.assertRaisesRegex(RuntimeError,"missing or stale"):
                refresh.verify_derived(conn,before[0])
            conn.execute("""UPDATE public.daily_smc
                SET calculated_at='2026-11-20 02:00:00+00'
                WHERE market='tpex' AND stock_id='6488' AND trade_date=%s""",
                (dates[0],))
            conn.commit()
            self.assertEqual(refresh.choose(conn),[])

            # A NEW independent historical source insertion invalidates the
            # previous proof without replacing a single old price.
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO public.daily_prices VALUES
                 ('tpex','6488','2026-09-16',100,1000,1000000,
                  'TPEX_DATED_OTC_EW','2026-11-21 01:00:00+00')""")
            conn.commit()
            self.assertEqual(len(refresh.choose(conn)),1)
            with self.assertRaisesRegex(RuntimeError,"missing or stale"):
                refresh.verify_derived(conn,before[0])
            self.assertEqual(conn.execute(
                "SELECT count(*)::int n FROM daily_prices").fetchone()["n"],66)
