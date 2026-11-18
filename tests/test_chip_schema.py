from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ChipSchemaDocumentationTests(unittest.TestCase):
    def test_documents_existing_canonical_tables(self):
        text = (ROOT / "sql" / "chip_schema.sql").read_text(encoding="utf-8")
        for table in ("institutional_flows", "margin_short", "tdcc_share_distribution", "insider_holdings"):
            self.assertIn(table, text)

    def test_does_not_create_parallel_or_conflicting_tables(self):
        text = (ROOT / "sql" / "chip_schema.sql").read_text(encoding="utf-8").upper()
        self.assertNotIn("CREATE TABLE", text)
        self.assertNotIn("DROP TABLE", text)
        self.assertNotIn("ALTER TABLE", text)

if __name__ == "__main__":
    unittest.main()
