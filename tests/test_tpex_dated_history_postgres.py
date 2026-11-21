"""Integration acceptance: dated TPEx whole-market backfill on disposable PG17.

No Neon access, no exchange network. Enforces evidence-backed same-date source,
append-only price rows and actual inserted-count reconciliation.
"""
from __future__ import annotations

import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg

from src import tpex_dated_history as importer
from src.tpex_dated_bulk_canary import parse_day

URL = os.environ.get("STOCK_CI_POSTGRES_URL")
DAY = date(2026, 11, 18)


@unittest.skipUnless(URL, "Disposable local PostgreSQL service required")
class TPExDatedHistoryPostgresTests(unittest.TestCase):
    def test_full_market_missing_only_with_existing_date_anchor(self):
        parsed = urlparse(URL)
        if parsed.hostname not in ("localhost", "127.0.0.1") or parsed.path != "/stock_ci_test":
            raise RuntimeError("Refusing non-disposable database")
        with psycopg.connect(URL) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS public.stock_master (
                market text NOT NULL, stock_id varchar(6) NOT NULL,
                PRIMARY KEY (market,stock_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.daily_prices (
                market text NOT NULL,stock_id varchar(6) NOT NULL,trade_date date NOT NULL,
                open numeric(18,4),high numeric(18,4),low numeric(18,4),close numeric(18,4),
                volume bigint,turnover numeric(24,2),price_change numeric(18,4),
                transactions bigint,source text,retrieved_at timestamptz DEFAULT now(),
                PRIMARY KEY(market,stock_id,trade_date)
            )""")
            for i in range(1000,1900):
                conn.execute("INSERT INTO stock_master(market,stock_id) VALUES('tpex',%s) ON CONFLICT DO NOTHING",
                             (str(i),))
            for i in range(1000,1015):
                conn.execute("""INSERT INTO daily_prices
                    (market,stock_id,trade_date,close,volume,source)
                    VALUES('tpex',%s,%s,100,99,'VERIFIED_ORIGINAL')
                    ON CONFLICT DO NOTHING""", (str(i),DAY))
            conn.commit()

        fields = ["代號","名稱","收盤","漲跌","開盤","最高","最低",
                  "成交股數","成交金額(元)","成交筆數"]
        rows = [[str(i),"TEST","100","0","100","110","90","1,000","100,000","10"]
                for i in range(1000,1900)]
        payload = {"stat":"ok", "tables":[{"fields":fields, "data":rows}]}
        verified = parse_day(payload,DAY,include_bars=True)
        self.assertEqual(verified["valid_four_digit_codes"],900)

        with (
            patch.dict(os.environ, {"STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED":"yes"}),
            patch.object(importer,"fetch_day",return_value=verified) as fetch,
        ):
            first = importer.run(URL,apply=True,batch_days=1,lookback=7,
                                 today=date(2026,11,21),pause_seconds=0)
            self.assertEqual(len(first),1)
            self.assertEqual(first[0]["date"], DAY.isoformat())
            self.assertEqual(first[0]["matched"],15)
            self.assertEqual(first[0]["inserted"],885)
            self.assertEqual(fetch.call_count,1)

            second = importer.run(URL,apply=True,batch_days=1,lookback=7,
                                  today=date(2026,11,21),pause_seconds=0)
            self.assertEqual(second,[])
            self.assertEqual(fetch.call_count,1)

        with psycopg.connect(URL) as conn:
            existing = conn.execute("""SELECT close,volume,source FROM daily_prices
                WHERE market='tpex' AND stock_id='1000' AND trade_date=%s""",(DAY,)).fetchone()
            self.assertEqual(existing,(Decimal("100.0000"),99,"VERIFIED_ORIGINAL"))
            new = conn.execute("""SELECT close,volume,source FROM daily_prices
                WHERE market='tpex' AND stock_id='1050' AND trade_date=%s""",(DAY,)).fetchone()
            self.assertEqual(new,(Decimal("100.0000"),1000,"TPEX_DATED_OTC_EW"))
            count = conn.execute("""SELECT count(*) FROM daily_prices
                WHERE market='tpex' AND trade_date=%s""",(DAY,)).fetchone()[0]
            self.assertEqual(count,900)
