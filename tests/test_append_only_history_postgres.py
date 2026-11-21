"""Real PostgreSQL integration test against disposable localhost only.

No Neon credentials or production data. Confirms append-only conflict handling,
actual inserted counts, normalized TPEx source units, and re-run idempotence.
"""
from __future__ import annotations

import csv
import os
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from src import db_storage


URL = os.environ.get("STOCK_CI_POSTGRES_URL")


@unittest.skipUnless(URL, "Disposable CI PostgreSQL is required")
class AppendOnlyHistoryPostgresTests(unittest.TestCase):
    def test_real_import_idempotence_and_volume_normalization(self):
        parsed = urlparse(URL)
        if parsed.hostname not in ("localhost", "127.0.0.1") or parsed.path != "/stock_ci_test":
            raise RuntimeError("Refusing non-disposable PostgreSQL target")

        with psycopg.connect(URL, row_factory=dict_row) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS public.stock_master (
                market text NOT NULL, stock_id varchar(6) NOT NULL,
                PRIMARY KEY(market,stock_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.daily_prices (
                market text NOT NULL,stock_id varchar(6) NOT NULL,trade_date date NOT NULL,
                open numeric(18,4),high numeric(18,4),low numeric(18,4),close numeric(18,4),
                volume bigint,turnover numeric(24,2),price_change numeric(18,4),
                transactions bigint,source text,retrieved_at timestamptz DEFAULT now(),
                PRIMARY KEY(market,stock_id,trade_date)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS public.import_runs (
                run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                market text NOT NULL,stock_id varchar(6) NOT NULL,
                started_at timestamptz NOT NULL DEFAULT now(),
                finished_at timestamptz,rows_received int NOT NULL,
                rows_upserted int NOT NULL DEFAULT 0,
                status text NOT NULL,error_message text
            )""")
            conn.execute("INSERT INTO stock_master(market,stock_id) VALUES('tpex','6488') ON CONFLICT DO NOTHING")
            conn.execute("""INSERT INTO daily_prices (market,stock_id,trade_date,close,volume,source)
                VALUES('tpex','6488','2026-11-18',88,1234,'VERIFIED_ORIGINAL')
                ON CONFLICT DO NOTHING""")
            conn.commit()

            columns = ["stock_id", "trade_date", "volume", "turnover", "open",
                       "high", "low", "close", "change", "transactions", "source"]
            def bar(day):
                return {"stock_id": "6488", "trade_date": day, "volume": "1,234.5",
                        "turnover": "9,876.5", "open": "100", "high": "110",
                        "low": "90", "close": "102", "change": "2",
                        "transactions": "50", "source": "TPEX_TRADING_STOCK"}
            with TemporaryDirectory() as directory:
                file = Path(directory) / "6488.csv"
                with file.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=columns)
                    writer.writeheader()
                    writer.writerow(bar("2026-11-18"))
                    writer.writerow(bar("2026-11-19"))

                inserted_first = db_storage.upsert_csv(conn, file, "tpex")
                inserted_again = db_storage.upsert_csv(conn, file, "tpex")
                self.assertEqual((inserted_first, inserted_again), (1, 0))

            old = conn.execute("""SELECT close,volume,source FROM daily_prices
                WHERE market='tpex' AND stock_id='6488' AND trade_date='2026-11-18'""").fetchone()
            self.assertEqual(old, {"close": Decimal("88.0000"), "volume": 1234,
                                   "source": "VERIFIED_ORIGINAL"})
            new = conn.execute("""SELECT close,volume,turnover,source FROM daily_prices
                WHERE market='tpex' AND stock_id='6488' AND trade_date='2026-11-19'""").fetchone()
            self.assertEqual(new, {"close": Decimal("102.0000"), "volume": 1234500,
                                   "turnover": Decimal("9876500.00"),
                                   "source": "TPEX_TRADING_STOCK_NORMALIZED"})
            imported = conn.execute("""SELECT rows_received,rows_upserted,status
                FROM import_runs ORDER BY run_id""").fetchall()
            self.assertEqual(imported, [
                {"rows_received": 2, "rows_upserted": 1, "status": "success"},
                {"rows_received": 2, "rows_upserted": 0, "status": "success"},
            ])
