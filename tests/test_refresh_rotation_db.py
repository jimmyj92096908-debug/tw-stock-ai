"""PostgreSQL integration test for fair TWSE/TPEx rotation.

Only runs against the isolated disposable CI database on localhost. Tests
create TEMP tables, never query a user's Neon database or download market data.
"""
from datetime import date
import os
import unittest
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from full_market_refresh import select_batch


TEST_URL = os.environ.get("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(TEST_URL, "Requires disposable CI Postgres on localhost")
class RefreshRotationDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parsed = urlparse(TEST_URL)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/stock_ci_test":
            raise AssertionError("Refusing to connect to non-CI PostgreSQL")
        cls.conn = psycopg.connect(TEST_URL, row_factory=dict_row)
        with cls.conn.transaction():
            cls.conn.execute("""
                CREATE TEMP TABLE stock_master (
                    market TEXT NOT NULL, stock_id VARCHAR(6) NOT NULL,
                    stock_name TEXT NOT NULL
                ) ON COMMIT PRESERVE ROWS
            """)
            cls.conn.execute("""
                CREATE TEMP TABLE daily_prices (
                    market TEXT NOT NULL, stock_id VARCHAR(6) NOT NULL,
                    trade_date DATE NOT NULL, close NUMERIC
                ) ON COMMIT PRESERVE ROWS
            """)
            cls.conn.execute("""
                CREATE TEMP TABLE market_data_refresh_state (
                    market TEXT NOT NULL, stock_id VARCHAR(6) NOT NULL,
                    last_attempt_at TIMESTAMPTZ
                ) ON COMMIT PRESERVE ROWS
            """)
            for stock in ("1001", "1002", "1003", "1004", "2001", "2002", "2003"):
                cls.conn.execute(
                    "INSERT INTO stock_master VALUES ('twse', %s, 'mock')", (stock,)
                )
                cls.conn.execute(
                    "INSERT INTO market_data_refresh_state VALUES ('twse', %s, NULL)",
                    (stock,),
                )
            cls.conn.execute("INSERT INTO stock_master VALUES ('tpex', '9001', 'mock')")
            cls.conn.execute(
                "INSERT INTO market_data_refresh_state VALUES ('tpex','9001', NULL)"
            )
            cls.conn.execute(
                "INSERT INTO daily_prices VALUES ('twse','2001','2026-10-30',100)"
            )
            cls.conn.execute(
                "INSERT INTO daily_prices VALUES ('twse','2002','2026-11-18',80)"
            )
            cls.conn.execute(
                "INSERT INTO daily_prices VALUES ('twse','2002','2026-11-19',NULL)"
            )
            cls.conn.execute(
                "INSERT INTO daily_prices VALUES ('twse','2003','2026-11-19',60)"
            )

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_interleaves_missing_and_existing_without_duplicates(self):
        result = select_batch(self.conn, "twse", 6)
        ids = [r["stock_id"] for r in result]
        self.assertEqual(ids, ["1001", "2001", "1002", "2002", "1003", "2003"])
        self.assertEqual(len(set(ids)), 6)
        self.assertEqual(result[3]["latest_trade_date"], date(2026, 11, 18))

    def test_fills_entire_batch_when_one_category_is_exhausted(self):
        result = select_batch(self.conn, "twse", 7)
        ids = [r["stock_id"] for r in result]
        self.assertEqual(ids, ["1001", "2001", "1002", "2002",
                               "1003", "2003", "1004"])

    def test_preserves_market_filter(self):
        self.assertEqual(
            [r["stock_id"] for r in select_batch(self.conn, "tpex", 5)],
            ["9001"],
        )


if __name__ == "__main__":
    unittest.main()
