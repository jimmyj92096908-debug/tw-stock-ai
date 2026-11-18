from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ChipSchemaTests(unittest.TestCase):
    def test_all_four_chip_tables_exist(self):
        sql = (ROOT / "sql" / "chip_schema.sql").read_text(encoding="utf-8")
        for table in ("institutional_daily", "margin_daily", "tdcc_distribution_weekly", "insider_holdings"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", sql)

    def test_raw_payload_and_source_are_retained(self):
        sql = (ROOT / "sql" / "chip_schema.sql").read_text(encoding="utf-8")
        self.assertGreaterEqual(sql.count("raw_payload JSONB"), 4)
        self.assertGreaterEqual(sql.count("source TEXT NOT NULL"), 4)

    def test_tdcc_table_is_weekly(self):
        sql = (ROOT / "sql" / "chip_schema.sql").read_text(encoding="utf-8")
        self.assertIn("tdcc_distribution_weekly", sql)
        self.assertIn("report_date", sql)

if __name__ == "__main__":
    unittest.main()
