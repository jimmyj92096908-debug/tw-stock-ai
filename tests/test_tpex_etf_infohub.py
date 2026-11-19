import unittest

from scripts.audit_tpex_etf_infohub import describe_payload


class TpexEtfInfohubTests(unittest.TestCase):
    def test_list_payload(self):
        result = describe_payload([{"證券代號": "00999", "ETF名稱": "測試ETF"}])
        self.assertTrue(result["schema_validated"])
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["security_code_field_candidates"], ["證券代號"])

    def test_nested_payload(self):
        result = describe_payload({"data": [{"code": "00999"}]})
        self.assertEqual(result["records_container_key"], "data")
        self.assertTrue(result["schema_validated"])

    def test_unrecognized_payload_stays_unvalidated(self):
        result = describe_payload({"message": "not data"})
        self.assertFalse(result["schema_validated"])
        self.assertEqual(result["record_count"], 0)


if __name__ == "__main__":
    unittest.main()
