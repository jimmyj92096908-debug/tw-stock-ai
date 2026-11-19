import unittest
from scripts.audit_twse_current_list import normalize_payload

class TWSECurrentListTests(unittest.TestCase):
    def test_valid_current_snapshot_is_candidates_only(self):
        result = normalize_payload([
            {"公司代號":"2330","公司名稱":"台積電","上市日期":"1994/09/05","出表日期":"20261119"}
        ])
        self.assertEqual(result["candidate_count"], 1)
        self.assertTrue(result["snapshot_only"])
        self.assertFalse(result["historical_universe_accepted"])
        self.assertFalse(result["common_stock_classification_confirmed"])

    def test_duplicate_and_incomplete_rows_rejected(self):
        result = normalize_payload([
            {"公司代號":"2330","公司名稱":"台積電","上市日期":"1994/09/05"},
            {"公司代號":"2330","公司名稱":"重複","上市日期":"1994/09/05"},
            {"公司代號":"","公司名稱":"缺代號","上市日期":"20200101"}
        ])
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(len(result["rejected_rows"]), 2)

    def test_rejects_unexpected_payload(self):
        with self.assertRaises(ValueError):
            normalize_payload({"data":[]})

if __name__ == "__main__":
    unittest.main()
