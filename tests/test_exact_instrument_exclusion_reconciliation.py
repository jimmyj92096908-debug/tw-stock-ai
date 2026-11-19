import unittest

from scripts.reconcile_exact_instrument_exclusions import reconcile_exact_codes


class ExactInstrumentExclusionTests(unittest.TestCase):
    def test_only_exact_code_matches_are_excluded(self):
        rows = [
            {"stock_id": "0050", "name": "ETF", "market": "TWSE"},
            {"stock_id": "2330", "name": "TSMC", "market": "TWSE"},
            {"stock_id": "00411A", "name": "ETF", "market": "TPEX"},
        ]
        sources = {
            "twse_fund_basic": {"market": "TWSE", "category": "fund_or_etf", "codes": {"0050"}},
            "tpex_etf": {"market": "TPEX", "category": "etf", "codes": {"00411A"}},
        }
        result = reconcile_exact_codes(rows, sources)
        self.assertEqual(result["bucket_counts"], {"candidate": 1, "excluded": 2})
        self.assertEqual(result["records"][0]["exclusion_evidence"][0]["source_id"], "twse_fund_basic")
        self.assertEqual(result["records"][2]["exclusion_evidence"][0]["source_id"], "tpex_etf")
        self.assertFalse(result["common_stock_classification_confirmed"])

    def test_no_code_or_name_heuristics(self):
        rows = [{"stock_id": "2330", "name": "主動式基金名稱", "market": "TWSE"}]
        sources = {
            "tpex_etf": {"market": "TPEX", "category": "etf", "codes": {"00999"}}
        }
        result = reconcile_exact_codes(rows, sources)
        self.assertEqual(result["bucket_counts"], {"candidate": 1, "excluded": 0})

    def test_manual_exclusion_is_preserved_even_without_source_code_match(self):
        rows = [{"stock_id": "2330", "name": "TSMC", "market": "TWSE"}]
        manual = [{"stock_id": "1808", "name": "潤隆建設", "market": "TWSE",
                   "review_reason": "user_directed_exclusion"}]
        result = reconcile_exact_codes(rows, {}, manual)
        self.assertEqual(result["bucket_counts"], {"candidate": 1, "excluded": 1})
        self.assertEqual(result["records"][1]["stock_id"], "1808")
        self.assertEqual(result["records"][1]["bucket"], "excluded")
        self.assertEqual(result["records"][1]["manual_exclusion_reason"], "user_directed_exclusion")

    def test_duplicate_exchange_codes_rejected(self):
        rows = [
            {"stock_id": "2330", "name": "A", "market": "TWSE"},
            {"stock_id": "2330", "name": "B", "market": "TWSE"},
        ]
        with self.assertRaises(ValueError):
            reconcile_exact_codes(rows, {})


if __name__ == "__main__":
    unittest.main()
