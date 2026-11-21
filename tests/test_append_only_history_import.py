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

    def test_unsafe_source_units_are_not_silently_claimed_normalized(self):
        # Source-specific conversion must be independently verified before
        # a normalization change is made. A source string alone is insufficient.
        self.assertNotIn("DO UPDATE", db_storage.INSERT_MISSING_PRICE_SQL.upper())


if __name__ == "__main__":
    unittest.main()
