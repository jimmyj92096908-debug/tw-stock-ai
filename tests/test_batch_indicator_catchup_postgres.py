"""Isolated real-PostgreSQL tests for price-history indicator eligibility."""
import os
import unittest
from datetime import date,timedelta
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from src.batch_indicator_catchup import select_candidates
from src.stock_db_audit import INDICATOR_BACKLOG_SQL


URL=os.getenv("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL,"Requires disposable localhost stock_ci_test")
class IndicatorEligibilityPGTests(unittest.TestCase):
    def test_only_sufficient_fresh_verified_history_is_selected(self):
        parsed=urlparse(URL)
        if parsed.hostname not in ("localhost","127.0.0.1") or parsed.path!="/stock_ci_test":
            raise RuntimeError("Unsafe external database URL")
        with psycopg.connect(URL,row_factory=dict_row) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS public.daily_prices
                (market text,stock_id text,trade_date date,close numeric,source text,
                 PRIMARY KEY (market,stock_id,trade_date))""")
            # Older disposable test fixtures may have created the same table
            # without the source column used by the test INSERT statements.
            conn.execute("ALTER TABLE public.daily_prices ADD COLUMN IF NOT EXISTS source text")
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
                conn.execute("""INSERT INTO public.daily_prices (market,stock_id,trade_date,close,source)
                    VALUES('twse','2999',%s,100,'ISOLATED_TEST')
                    ON CONFLICT (market,stock_id,trade_date) DO NOTHING""",(d,))
            for i in range(59):
                d=start+timedelta(days=i)
                conn.execute("""INSERT INTO public.daily_prices (market,stock_id,trade_date,close,source)
                    VALUES('tpex','2998',%s,120,'ISOLATED_TEST')
                    ON CONFLICT (market,stock_id,trade_date) DO NOTHING""",(d,))
            eligible=select_candidates(conn,"twse",3)
            self.assertIn("2999",[r["stock_id"] for r in eligible])
            limited=select_candidates(conn,"tpex",3)
            self.assertNotIn("2998",[r["stock_id"] for r in limited])

            # Regression: legacy indicator rows may outnumber currently
            # usable close bars, while their newest date is still stale.
            # This is the real-world 8937 situation on 2026-11-20.
            for i in range(60):
                d=start+timedelta(days=i)
                conn.execute("""INSERT INTO public.daily_prices
                  (market,stock_id,trade_date,close,source)
                  VALUES('tpex','8937',%s,200,'ISOLATED_TEST')
                  ON CONFLICT DO NOTHING""",(d,))
            for i in range(61):
                d=start+timedelta(days=i-2)
                conn.execute("""INSERT INTO public.daily_technicals
                  VALUES('tpex','8937',%s) ON CONFLICT DO NOTHING""",(d,))
                conn.execute("""INSERT INTO public.daily_smc
                  VALUES('tpex','8937',%s) ON CONFLICT DO NOTHING""",(d,))
            date_stale=select_candidates(conn,"tpex",3)
            match=[r for r in date_stale if r["stock_id"]=="8937"]
            self.assertEqual(len(match),1)
            self.assertEqual(match[0]["close_days"],60)
            self.assertEqual(match[0]["technical_rows"],61)
            self.assertEqual(match[0]["smc_rows"],61)
            self.assertEqual(match[0]["last_technical"],start+timedelta(days=58))
            self.assertEqual(match[0]["latest_close"],start+timedelta(days=59))
            # The actual backlog SQL must classify exactly the same stale
            # symbol; mocking this SQL hid a real CTE projection bug.
            def backlog():
                return {x["market"]:x for x in
                        conn.execute(INDICATOR_BACKLOG_SQL).fetchall()}
            pending_before=backlog()["tpex"]["pending"]
            self.assertGreaterEqual(pending_before,1)
            # Restoring the latest real session clears this pending status;
            # excess older rows must not falsely keep it in the queue.
            latest=start+timedelta(days=59)
            conn.execute("""INSERT INTO public.daily_technicals
              VALUES('tpex','8937',%s) ON CONFLICT DO NOTHING""",(latest,))
            conn.execute("""INSERT INTO public.daily_smc
              VALUES('tpex','8937',%s) ON CONFLICT DO NOTHING""",(latest,))
            self.assertNotIn("8937",
                [r["stock_id"] for r in select_candidates(conn,"tpex",3)])
            self.assertEqual(pending_before-backlog()["tpex"]["pending"],1)

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
