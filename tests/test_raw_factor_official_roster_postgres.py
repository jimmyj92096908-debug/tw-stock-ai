"""Execute actual roster queries against a disposable, loopback PostgreSQL fixture.

Synthetic rows verify selection behavior only; no real market or alpha claim.
Never accepts DATABASE_URL or a remote connection.
"""
import os
from datetime import date,timedelta
from unittest import TestCase,skipUnless

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scripts import tpex_whole_market_raw_factor_audit as tpex
from scripts import twse_raw_factor_canary as twse

TEST_URL=os.getenv("RAW_FACTOR_TEST_DATABASE_URL","")
LOCAL_URL="postgresql://postgres:test@127.0.0.1:5432/raw_factor_ci"
FIRST=date(2024,1,1)
LAST=FIRST+timedelta(days=240)


@skipUnless(TEST_URL,"Disposable PostgreSQL fixture not configured")
class OfficialRosterPostgresTests(TestCase):
    def setUp(self):
        self.assertEqual(TEST_URL,LOCAL_URL,"Only isolated loopback fixture permitted")
        self.conn=psycopg.connect(TEST_URL,row_factory=dict_row,connect_timeout=5)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.conn.execute("""
        CREATE TABLE public.official_issuer_weekly_snapshots(
            observed_at timestamptz, snapshot jsonb);
        CREATE TABLE public.official_issuer_snapshot_corrections(
            observed_at timestamptz, snapshot jsonb);
        CREATE TABLE public.model_stock_exclusions(market text,stock_id text);
        CREATE TABLE public.stock_master(market text,stock_id text);
        CREATE TABLE public.daily_prices(
            market text, stock_id text, trade_date date, open numeric,
            high numeric, low numeric, close numeric, volume bigint,
            turnover bigint, price_change numeric, transactions bigint, source text);
        CREATE TABLE public.daily_technicals(market text,stock_id text,trade_date date);
        CREATE TABLE public.daily_smc(market text,stock_id text,trade_date date);
        CREATE TABLE public.daily_adjusted_prices(market text,stock_id text,trade_date date);
        """)
        self.roster={"twse":["2330","2317","1589","9998"],
                     "tpex":["6488","8069","1589","9998"]}
        records=[{"market":m,"stock_id":s} for m,ids in self.roster.items() for s in ids]
        self.conn.execute(
            "INSERT INTO public.official_issuer_weekly_snapshots VALUES "
            "(CURRENT_TIMESTAMP-INTERVAL '1 day',%s)",(Jsonb({"records":records}),))
        old=[{"market":m,"stock_id":"9999"} for m in self.roster]
        self.conn.execute(
            "INSERT INTO public.official_issuer_weekly_snapshots VALUES "
            "(CURRENT_TIMESTAMP-INTERVAL '20 days',%s)",(Jsonb({"records":old}),))
        for market,ids in self.roster.items():
            self.conn.execute("INSERT INTO public.model_stock_exclusions VALUES (%s,'9998')",(market,))
            for sid in ids+["9999"]:
                self.conn.execute("INSERT INTO public.stock_master VALUES (%s,%s)",(market,sid))
                self.conn.execute("""
                    INSERT INTO public.daily_prices
                    SELECT %s,%s,%s::date+i,100,101,99,100,1000,100000,0,10,%s
                    FROM generate_series(0,240) i
                    """,(market,sid,FIRST,
                         "TPEX_DATED_OTC_EW" if market=="tpex" else "TWSE_MI_INDEX_ALLBUT0999"))
            self.conn.execute("""
                INSERT INTO public.daily_prices VALUES
                (%s,'9999',%s,100,101,99,100,1000,100000,0,10,%s)
                """,(market,LAST+timedelta(days=1),
                     "TPEX_DATED_OTC_EW" if market=="tpex" else "TWSE_MI_INDEX_ALLBUT0999"))

    def test_tpex_real_sql_filters_counts_bars_and_cutoff(self):
        meta=self.conn.execute(tpex.META_SQL).fetchone()
        self.assertEqual(meta["last_market_day"],LAST)
        rows=self.conn.execute(tpex.STOCK_COUNTS_SQL,(LAST,)*4).fetchall()
        self.assertEqual({r["stock_id"] for r in rows},{"6488","8069"})
        self.assertTrue(all(r["valid_source_days"]==241 for r in rows))
        bars=self.conn.execute(tpex.BARS_SQL,
            (LAST,320,["6488","8069","1589","9998","9999"])).fetchall()
        self.assertEqual({r["stock_id"] for r in bars},{"6488","8069"})
        self.assertEqual(len(bars),482)

    def test_twse_real_sql_filters_both_cohorts_and_direct_bars(self):
        for query in (twse.CANDIDATES_SQL,twse.RECENT_MATURED_SQL):
            rows=self.conn.execute(query).fetchall()
            self.assertEqual({r["stock_id"] for r in rows},{"2330","2317"})
            self.assertTrue(all(r["market_day"]==LAST for r in rows))
        self.assertEqual(len(self.conn.execute(twse.SOURCE_SQL,("2330",LAST,320)).fetchall()),241)
        for sid in ("1589","9998","9999","6488"):
            self.assertEqual(self.conn.execute(twse.SOURCE_SQL,(sid,LAST,320)).fetchall(),[])

    def test_stale_roster_never_falls_back_to_historical_master(self):
        self.conn.execute("UPDATE public.official_issuer_weekly_snapshots "
                          "SET observed_at=CURRENT_TIMESTAMP-INTERVAL '15 days'")
        self.assertIsNone(self.conn.execute(tpex.META_SQL).fetchone()["last_market_day"])
        self.assertEqual(self.conn.execute(tpex.STOCK_COUNTS_SQL,(LAST,)*4).fetchall(),[])
        self.assertEqual(self.conn.execute(tpex.BARS_SQL,(LAST,320,["6488"])).fetchall(),[])
        self.assertEqual(self.conn.execute(twse.CANDIDATES_SQL).fetchall(),[])
        self.assertEqual(self.conn.execute(twse.SOURCE_SQL,("2330",LAST,320)).fetchall(),[])

    def test_newer_correction_replaces_old_roster_without_fallback(self):
        self.conn.execute("INSERT INTO public.official_issuer_snapshot_corrections "
            "VALUES (CURRENT_TIMESTAMP,%s)",(Jsonb({"records":[
                {"market":"twse","stock_id":"2317"},
                {"market":"tpex","stock_id":"8069"}]}),))
        self.assertEqual([r["stock_id"] for r in self.conn.execute(
            twse.CANDIDATES_SQL).fetchall()],["2317"])
        self.assertEqual([r["stock_id"] for r in self.conn.execute(
            tpex.STOCK_COUNTS_SQL,(LAST,)*4).fetchall()],["8069"])
        self.assertEqual(self.conn.execute(twse.SOURCE_SQL,("2330",LAST,320)).fetchall(),[])
