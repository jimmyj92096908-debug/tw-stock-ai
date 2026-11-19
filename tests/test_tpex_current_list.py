import unittest
from scripts.audit_tpex_current_list import normalize_payload

class TPExCurrentListTests(unittest.TestCase):
    def test_valid_snapshot_is_candidates_only(self):
        result = normalize_payload([{
            "SecuritiesCompanyCode": "6488",
            "CompanyName": "環球晶圓股份有限公司",
            "CompanyAbbreviation": "環球晶"
        }])
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["market"], "TPEX")
        self.assertTrue(result["snapshot_only"])
        self.assertFalse(result["historical_universe_accepted"])
        self.assertFalse(result["common_stock_classification_confirmed"])

    def test_duplicate_and_incomplete_rows_rejected(self):
        result = normalize_payload([
            {"SecuritiesCompanyCode":"6488","CompanyName":"環球晶圓"},
            {"SecuritiesCompanyCode":"6488","CompanyName":"重複"},
            {"SecuritiesCompanyCode":"","CompanyName":"缺代號"}
        ])
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(len(result["rejected_rows"]), 2)

    def test_rejects_unexpected_payload(self):
        with self.assertRaises(ValueError):
            normalize_payload({"data":[]})

if __name__ == "__main__":
    unittest.main()
