"""Isolated PostgreSQL integration tests for no-replacement snapshot inserts."""
import os
import unittest
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

import psycopg

from official_snapshot_ingest import INSERT_MISSING_SQL, write_missing, run


TEST_URL = os.getenv("STOCK_CI_POSTGRES_URL")
DAY = date(2026,11,19)


def quote(code):
    return {
        "market":"twse","stock_id":code,"trade_date":DAY,
        "open":Decimal("100"),"high":Decimal("105"),
        "low":Decimal("98"),"close":Decimal("102"),
        "volume":1000,"turnover":102000,
        "price_change":Decimal("2"),"transactions":15,
        "source":"TWSE_MI_INDEX_ALLBUT0999",
    }


@unittest.skipUnless(TEST_URL,"Requires disposable local stock_ci_test PostgreSQL")
class StockSnapshotDBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url=urlparse(TEST_URL)
        if url.hostname not in ("localhost","127.0.0.1") or url.path!="/stock_ci_test":
            raise RuntimeError("Refusing non-disposable database for integration test")
        cls.conn=psycopg.connect(TEST_URL)
        with cls.conn.transaction():
            cls.conn.execute("CREATE TABLE public.daily_prices (market text NOT NULL,stock_id text NOT NULL,trade_date date NOT NULL,open numeric,high numeric,low numeric,close numeric,volume bigint,turnover numeric,price_change numeric,transactions bigint,source text NOT NULL,PRIMARY KEY(market,stock_id,trade_date))")
            cls.conn.execute("CREATE TABLE public.stock_master (market text NOT NULL,stock_id text NOT NULL,PRIMARY KEY(market,stock_id))")
            cls.conn.execute("INSERT INTO stock_master VALUES ('twse','2330'),('twse','6213')")
            cls.conn.execute("INSERT INTO daily_prices (market,stock_id,trade_date,close,source) VALUES ('twse','2330','2026-11-19',99,'ORIGINAL_MONTHLY_SOURCE')")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_no_replacement_idempotency_and_date_guard(self):
        self.assertIn("ON CONFLICT (market,stock_id,trade_date) DO NOTHING",INSERT_MISSING_SQL)
        bars=[quote("2330"),quote("6213")]
        inserted=write_missing(self.conn,"twse",DAY,bars)
        self.assertEqual(inserted,1)
        inserted_again=write_missing(self.conn,"twse",DAY,bars)
        self.assertEqual(inserted_again,0)
        rows=self.conn.execute("SELECT stock_id,close,source FROM daily_prices ORDER BY stock_id").fetchall()
        self.assertEqual(rows[0][1],Decimal("99"))
        self.assertEqual(rows[0][2],"ORIGINAL_MONTHLY_SOURCE")
        self.assertEqual(rows[1][1],Decimal("102"))
        with self.assertRaisesRegex(ValueError,"Mixed dates"):
            write_missing(self.conn,"twse",DAY,[{**quote("6213"),"trade_date":date(2026,11,18)}])

    def test_live_apply_needs_a_second_explicit_gate(self):
        previous=os.environ.pop("STOCK_SNAPSHOT_WRITE_ENABLED",None)
        try:
            with self.assertRaisesRegex(ValueError,"disabled"):
                run("postgresql://not-real.invalid/test",apply=True)
        finally:
            if previous is not None:
                os.environ["STOCK_SNAPSHOT_WRITE_ENABLED"]=previous


if __name__=="__main__":
    unittest.main()
