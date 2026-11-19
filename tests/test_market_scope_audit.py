import unittest
from scripts.audit_market_scope import decode_csv, inspect_tdcc_csv


class MarketScopeAuditTests(unittest.TestCase):
    def test_decode_big5_csv(self):
        raw = "證券代號,證券名稱,市場別\\n0050,元大台灣50,上市\\n".encode("big5")
        text, encoding = decode_csv(raw)
        self.assertIn("證券代號", text)
        self.assertEqual(encoding, "big5")

    def test_inspect_master_reports_market_counts_without_claiming_history(self):
        raw = "證券代號,證券名稱,市場別\\n0050,ETF甲,上市\\n6488,公司乙,上櫃\\n".encode("utf-8")
        result = inspect_tdcc_csv(raw)
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["market_or_type_value_counts"]["market"]["市場別"], {"上市": 1, "上櫃": 1})
        self.assertEqual(result["status"], "source_parsed_schema_review_required")
        self.assertTrue(result["scope_limitations"])


if __name__ == "__main__":
    unittest.main()
