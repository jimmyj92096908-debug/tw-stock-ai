"""Real PostgreSQL idempotency of official dated whole-market history writes.

Only uses disposable CI localhost stock_ci_test; never authorizes Neon writes.
"""
import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg
from src import twse_dated_history as history


URL = os.environ.get("STOCK_CI_POSTGRES_URL")
DAY = date(2026,11,19)


@unittest.skipUnless(URL, "Disposable local CI PostgreSQL service required")
class TWSEDateBackfillPGTests(unittest.TestCase):
    def test_uses_real_database_progress_and_preserves_original_prices(self):
        parsed=urlparse(URL)
        if parsed.hostname not in ("localhost","127.0.0.1") or parsed.path!="/stock_ci_test":
            raise RuntimeError("Refusing non-disposable database")
        with psycopg.connect(URL) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS public.stock_master (
                market text NOT NULL,stock_id text NOT NULL,
                PRIMARY KEY (market,stock_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.model_stock_exclusions (
                market text NOT NULL, stock_id text NOT NULL, reason text NOT NULL,
                excluded_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (market,stock_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.daily_prices (
                market text NOT NULL,stock_id text NOT NULL,trade_date date NOT NULL,
                open numeric,high numeric,low numeric,close numeric,
                volume bigint,turnover numeric,price_change numeric,
                transactions bigint,source text,
                PRIMARY KEY(market,stock_id,trade_date)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.official_issuer_weekly_snapshots (
                observed_at timestamptz NOT NULL, snapshot jsonb NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.official_issuer_snapshot_corrections (
                observed_at timestamptz NOT NULL, snapshot jsonb NOT NULL
            )""")
            stock_ids=[str(i) for i in range(1000,1700)]
            for stock_id in stock_ids:
                conn.execute("""INSERT INTO public.stock_master(market,stock_id)
                    VALUES('twse',%s) ON CONFLICT DO NOTHING""",(stock_id,))
            # Master-only symbol 1700 must be excluded from official active source.
            conn.execute("""INSERT INTO public.stock_master(market,stock_id)
                VALUES('twse','1700') ON CONFLICT DO NOTHING""")
            conn.execute("""INSERT INTO public.official_issuer_weekly_snapshots
                (observed_at,snapshot)
                SELECT now(),jsonb_build_object('records',
                   jsonb_agg(jsonb_build_object('market',market,'stock_id',stock_id)))
                FROM public.stock_master WHERE stock_id <> '1700'""")
            # A verified older record must not be overwritten by whole-market data.
            conn.execute("""INSERT INTO public.daily_prices
                (market,stock_id,trade_date,close,source)
                VALUES ('twse','1000',%s,88,'VERIFIED_ORIGINAL')
                ON CONFLICT (market,stock_id,trade_date) DO NOTHING""",(DAY,))

        bars=[{
            "market":"twse","stock_id":stock_id,"trade_date":DAY,
            "open":Decimal("99"),"high":Decimal("105"),
            "low":Decimal("97"),"close":Decimal("101"),
            "volume":100,"turnover":10000,"price_change":Decimal("2"),
            "transactions":10,"source":"TWSE_MI_INDEX_ALLBUT0999"
        } for stock_id in stock_ids+['1700']]
        real_connect=psycopg.connect
        # source/network mocked, but actual imports and progress use a real
        # local disposable database. Run once with a single weekday.
        with (
            patch.dict(os.environ,{"STOCK_TWSE_HISTORY_WRITE_ENABLED":"yes"}),
            patch.object(history,"fetch_official_day",return_value=bars) as source,
            patch.object(history,"schedule_dates",wraps=history.schedule_dates) as scheduler,
        ):
            result=history.run(URL,apply=True,today=date(2026,11,20),
                               batch_days=1,lookback_days=7,pause_seconds=0)
            self.assertEqual(result[0]["status"],"imported")
            self.assertEqual(result[0]["qualified"],700)
            self.assertEqual(result[0]["inserted"],699)
            self.assertEqual(source.call_count,1)
            self.assertEqual(scheduler.call_count,1)

            # Re-running may pick another unprocessed day but never re-import
            # a completed date; assert the processed-day set itself.
            with real_connect(URL) as conn:
                rows=conn.execute("""SELECT trade_date,status,qualified,inserted
                    FROM public.twse_history_day_progress""").fetchall()
                self.assertIn((DAY,"imported",700,699),rows)
                existing=conn.execute("""SELECT close,source FROM public.daily_prices
                    WHERE market='twse' AND stock_id='1000' AND trade_date=%s""",(DAY,)).fetchone()
                self.assertEqual(existing,(Decimal("88"),"VERIFIED_ORIGINAL"))
                new_count=conn.execute("""SELECT COUNT(*) FROM public.daily_prices
                    WHERE market='twse' AND trade_date=%s AND close IS NOT NULL""",(DAY,)).fetchone()[0]
                self.assertGreaterEqual(new_count,700)
                self.assertEqual(conn.execute("""SELECT count(*) FROM public.daily_prices
                    WHERE market='twse' AND stock_id='1700'""").fetchone()[0],0)
