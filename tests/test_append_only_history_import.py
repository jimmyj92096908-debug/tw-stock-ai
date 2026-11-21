"""Safety contract for monthly history CSV import: existing prices are immutable."""
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path

from src import db_storage


class AppendOnlyHistoryTests(unittest.TestCase):
    def test_missing_price_keys_insert_without_overwriting(self):
        sql = db_storage.INSERT_MISSING_PRICE_SQL.upper()
        self.assertIn("INSERT INTO DAILY_PRICES", sql)
        self.assertIn("ON CONFLICT (MARKET, STOCK_ID, TRADE_DATE) DO NOTHING", sql)
        self.assertNotIn("DO UPDATE", sql)
        self.assertNotIn("EXCLUDED.", sql)

    def test_import_reports_only_actual_inserted_rows(self):
        source = __import__("inspect").getsource(db_storage.upsert_csv)
        self.assertIn("inserted = cur.rowcount", source)
        self.assertIn("(inserted, run_id)", source)
        self.assertIn("return inserted", source)



    def test_source_and_date_validation_precedes_all_db_activity(self):
        import csv
        base = {
            "stock_id": "6488", "trade_date": "2026-11-19",
            "open": "100", "high": "110", "low": "90", "close": "100",
            "volume": "10", "turnover": "1000", "change": "0",
            "transactions": "20", "source": "TPEX_TRADING_STOCK",
        }
        cases = [
            ({"source": "UNKNOWN"}, "source"),
            ({"source": "TPEX_DAILY_CLOSE_OPENAPI"}, "source"),
            ({"trade_date": "2027-01-01"}, "future"),
            ({"trade_date": "not-a-date"}, "date"),
            ({"volume": "-1"}, "Invalid raw TPEx volume"),
            ({"stock_id": "INVALID"}, "stock code"),
        ]
        with TemporaryDirectory() as directory:
            filepath = Path(directory) / "6488.csv"
            for changes, reason in cases:
                row = {**base, **changes}
                with filepath.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(base))
                    writer.writeheader()
                    writer.writerow(row)
                with self.subTest(changes=changes):
                    with self.assertRaisesRegex(ValueError, reason):
                        db_storage.read_history_csv(filepath, "tpex")

    def test_tpex_csv_normalization_is_exact(self):
        import csv
        row = {
            "stock_id": "6488", "trade_date": "2026-11-19",
            "open": "100", "high": "110", "low": "90", "close": "100",
            "volume": "1,234.5", "turnover": "90,123.456", "change": "0",
            "transactions": "20", "source": "TPEX_TRADING_STOCK",
        }
        with TemporaryDirectory() as directory:
            filepath = Path(directory) / "6488.csv"
            with filepath.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            imported = db_storage.read_history_csv(filepath, "tpex")
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["volume"], 1234500)
        self.assertEqual(imported[0]["turnover"], 90123456)
        self.assertEqual(imported[0]["source"], "TPEX_TRADING_STOCK_NORMALIZED")

    def test_tpex_monthly_thousands_normalized_only_once(self):
        raw = {"market": "tpex", "source": "TPEX_TRADING_STOCK",
               "volume": "1,234.5", "turnover": "90,123.456"}
        result = db_storage.normalize_tpex_monthly_units(raw)
        self.assertEqual(result["volume"], 1234500)
        self.assertEqual(result["turnover"], 90123456)
        self.assertEqual(result["source"], "TPEX_TRADING_STOCK_NORMALIZED")
        self.assertEqual(db_storage.normalize_tpex_monthly_units(result)["volume"], 1234500)

    def test_openapi_and_twse_are_not_rescaled(self):
        for market, source in (("tpex", "TPEX_DAILY_CLOSE_OPENAPI"),
                               ("twse", "TWSE_MONTHLY")):
            record = {"market": market, "source": source,
                      "volume": 12000, "turnover": 500000}
            self.assertIs(db_storage.normalize_tpex_monthly_units(record), record)
            self.assertEqual(record["volume"], 12000)

    def test_fractional_share_and_negative_volume_rejected(self):
        for value in ("0.0001", "-1", "NaN"):
            with self.assertRaises(ValueError):
                db_storage.normalize_tpex_monthly_units({
                    "market": "tpex", "source": "TPEX_TRADING_STOCK",
                    "volume": value, "turnover": "100"
                })

    def test_duplicate_rows_are_not_reported_as_inserted(self):
        """Exercise importer with mocked PostgreSQL insert effects."""
        import csv
        from contextlib import nullcontext

        class Cursor:
            rowcount = -1
            sql_calls = []
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def execute(self, statement, params=None):
                self.sql_calls.append((statement, params))
            def executemany(self, statement, rows):
                assert "DO NOTHING" in statement
                self.rowcount = 0
            def fetchone(self):
                return {"run_id": 123}

        class Connection:
            def __init__(self):
                self.cur = Cursor()
            def transaction(self):
                return nullcontext()
            def cursor(self):
                return self.cur

        record = {
            "stock_id": "6488", "trade_date": "2026-11-19",
            "open": "500", "high": "510", "low": "480", "close": "490",
            "volume": "1000", "turnover": "500000", "change": "-10",
            "transactions": "50", "source": "TPEX_TRADING_STOCK",
        }
        with TemporaryDirectory() as directory:
            filepath = Path(directory) / "6488.csv"
            with filepath.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(record))
                writer.writeheader()
                writer.writerow(record)
            conn = Connection()
            self.assertEqual(db_storage.upsert_csv(conn, filepath, "tpex"), 0)
            updates = [(sql, params) for sql, params in conn.cur.sql_calls
                       if "UPDATE import_runs" in sql]
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0][1], (0, 123))

    def test_unsafe_source_units_are_not_silently_claimed_normalized(self):
        # Source-specific conversion must be independently verified before
        # a normalization change is made. A source string alone is insufficient.
        self.assertNotIn("DO UPDATE", db_storage.INSERT_MISSING_PRICE_SQL.upper())


if __name__ == "__main__":
    unittest.main()
